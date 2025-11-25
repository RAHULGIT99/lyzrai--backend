**⚙️ Backend Stack

- 🤖 Lyzr Agent API – delegates review reasoning to our hosted agent.
- 🐙 PyGithub – convenient Python client for traversing repositories and pull requests.
- 🔐 GitHub REST API – final authority for fetching diffs and publishing review comments.
- 🌐 FastAPI + Uvicorn – lightweight web layer serving the review endpoints with built-in CORS.
- 🔄 Requests – HTTP utility used for both GitHub and Lyzr interactions.
- 🔑 python-dotenv – loads local environment variables (tokens, API keys) for secure configuration.
- ☁️ Hugging Face Spaces (Planned Hosting) – deploy backend for sharing the end-to-end reviewer experience.

Create a .env in the same directory and replace your github auth token:

auth_token = #your_github_token
lyzr_api_key = #your lyzrapikey

