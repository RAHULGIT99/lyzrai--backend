import os

import requests
from dotenv import load_dotenv
from fastapi import Body, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from github import Auth, Github

load_dotenv()

AUTH_TOKEN = os.getenv("auth_token")
LYZR_API_KEY = os.getenv("lyzr_api_key")

if not AUTH_TOKEN:
	print("[INIT] No default GitHub token found in environment; requests must supply one.")

if not LYZR_API_KEY:
	raise RuntimeError("Missing Lyzr API key in environment variable 'lyzr_api_key'.")

USER_ID = "rahulvalavoju123@gmail.com"
AGENT_ID = "69253dc97c7d73f7cbe83e06"
SESSION_ID = "69253dc97c7d73f7cbe83e06-2rtcfnzp80a"
LYZR_URL = "https://agent-prod.studio.lyzr.ai/v3/inference/chat/"


app = FastAPI(title="Lyzr PR Reviewer")
app.add_middleware(
	CORSMiddleware,
	allow_origins=["*"],
	allow_credentials=True,
	allow_methods=["*"],
	allow_headers=["*"],
)


def _resolve_token(override_token):
	token = (override_token or AUTH_TOKEN or "").strip()
	if not token:
		raise HTTPException(status_code=401, detail="GitHub token is required.")
	return token


def _get_github_client(override_token=None):
	token = _resolve_token(override_token)
	auth = Auth.Token(token)
	return Github(auth=auth)


def _fetch_diff_text(pr, token):
	diff_url = pr.diff_url
	headers = {"Authorization": f"token {token}"}
	response = requests.get(diff_url, headers=headers, timeout=30)
	response.raise_for_status()
	return response.text


def _generate_review(diff_text):
	payload = {
		"user_id": USER_ID,
		"agent_id": AGENT_ID,
		"session_id": SESSION_ID,
		"message": diff_text,
	}
	headers = {
		"x-api-key": LYZR_API_KEY,
		"Content-Type": "application/json",
	}
	response = requests.post(LYZR_URL, json=payload, headers=headers, timeout=60)
	response.raise_for_status()
	data = response.json()
	return data.get("response") or data.get("message")


def _post_review_comment(repo_full_name, pr_number, body, token):
	url = f"https://api.github.com/repos/{repo_full_name}/issues/{pr_number}/comments"
	payload = {"body": body}
	headers = {
		"Authorization": f"token {token}",
		"Content-Type": "application/json",
	}
	response = requests.post(url, json=payload, headers=headers, timeout=30)
	response.raise_for_status()


def _get_repo(repo_full_name, token_override=None):
	client = _get_github_client(token_override)
	try:
		return client.get_repo(repo_full_name)
	except Exception as exc:
		raise HTTPException(status_code=404, detail=f"Repository not found: {exc}")


@app.post("/prs")
def list_pull_requests(payload: dict = Body(...)):
	repo_name = (payload.get("repo") or "").strip()
	if "/" not in repo_name:
		raise HTTPException(status_code=422, detail="Repository must be in 'owner/name' format.")

	username = (payload.get("username") or "").strip()
	override_token = (payload.get("token") or "").strip() or None
	print(
		f"[LIST_PRS] Fetching pull requests for repo={repo_name} username={username} token_override={bool(override_token)}"
	)

	repo = _get_repo(repo_name, override_token)
	try:
		pull_requests = repo.get_pulls(state="open", sort="created")
	except Exception as exc:
		print(f"[LIST_PRS] Failed to fetch pull requests: {exc}")
		raise HTTPException(status_code=502, detail=f"Failed to fetch pull requests: {exc}")

	items = []
	for pr in pull_requests:
		items.append({
			"number": pr.number,
			"title": pr.title,
			"author": pr.user.login,
		})

	print(f"[LIST_PRS] Found {len(items)} open pull request(s)")

	return {"pull_requests": items}


@app.post("/reviews")
def publish_reviews(payload: dict = Body(...)):
	repo_name = (payload.get("repo") or "").strip()
	pr_numbers = payload.get("pull_request_numbers") or []
	override_token = (payload.get("token") or "").strip() or None

	if "/" not in repo_name:
		raise HTTPException(status_code=422, detail="Repository must be in 'owner/name' format.")

	if not isinstance(pr_numbers, list) or not pr_numbers:
		raise HTTPException(status_code=422, detail="Provide at least one pull request number.")

	if any((not isinstance(number, int)) or number <= 0 for number in pr_numbers):
		raise HTTPException(status_code=422, detail="Pull request numbers must be positive integers.")

	resolved_token = _resolve_token(override_token)

	print(
		f"[REVIEWS] Starting review flow for repo={repo_name} prs={pr_numbers} token_override={bool(override_token)}"
	)

	repo = _get_repo(repo_name, resolved_token)
	results = []

	for pr_number in pr_numbers:
		print(f"[REVIEWS] Processing PR #{pr_number}")
		try:
			pr = repo.get_pull(pr_number)
		except Exception as exc:
			print(f"[REVIEWS] Unable to fetch PR #{pr_number}: {exc}")
			results.append({
				"number": pr_number,
				"status": "error",
				"message": f"Unable to fetch PR: {exc}",
			})
			continue

		comment_title = f"PR #{pr.number} - {pr.title}" if pr.title else f"PR #{pr.number}"
		print(f"[REVIEWS] Title resolved: {comment_title}")

		try:
			diff_text = _fetch_diff_text(pr, resolved_token)
			print(f"[REVIEWS] Diff retrieved for PR #{pr.number}")
		except Exception as exc:
			print(f"[REVIEWS] Diff fetch failed for PR #{pr.number}: {exc}")
			results.append({
				"number": pr.number,
				"status": "error",
				"comment_title": comment_title,
				"message": f"Failed to fetch diff: {exc}",
			})
			continue

		try:
			review_comment = _generate_review(diff_text)
			print(f"[REVIEWS] Review generated for PR #{pr.number}: {bool(review_comment)}")
		except Exception as exc:
			print(f"[REVIEWS] Review generation failed for PR #{pr.number}: {exc}")
			results.append({
				"number": pr.number,
				"status": "error",
				"comment_title": comment_title,
				"message": f"Failed to generate review: {exc}",
			})
			continue

		if not review_comment:
			print(f"[REVIEWS] No review returned for PR #{pr.number}")
			results.append({
				"number": pr.number,
				"status": "skipped",
				"comment_title": comment_title,
				"message": "No review content returned from Lyzr.",
			})
			continue

		comment_body = f"### {comment_title}\n\n{review_comment}"

		try:
			_post_review_comment(repo_name, pr.number, comment_body, resolved_token)
			results.append({
				"number": pr.number,
				"status": "comment_posted",
				"comment_title": comment_title,
				"comment_body": comment_body,
			})
		except Exception as exc:
			results.append({
				"number": pr.number,
				"status": "error",
				"comment_title": comment_title,
				"message": f"Failed to post review comment: {exc}",
			})

	print(f"[REVIEWS] Completed review flow for repo={repo_name}")

	return {"results": results}


@app.get("/health")
def health_check():
	return {"status": "ok"}
