# Render deployment (Biz-Agent 5.0)

## Architecture

- Render Docker Web Service runs FastAPI and serves the bundled frontend at `/app/`.
- Neon PostgreSQL stores persistent application data.
- SQLite remains the default for local development.
- Uploaded documents are stored under the configured temporary uploads directory. On Render Free this filesystem is ephemeral; source files can disappear on restart/redeploy. Uploads are currently recorded as metadata and may be needed for later investigation runs, so do not expect source-file persistence until object storage is added.

## 1. Create Neon database

Create a PostgreSQL project in Neon and copy its connection string. Use the pooled connection string if Neon provides one. It should look like a PostgreSQL URL. Do not commit it.

## 2. Deploy to Render

1. Open Render Dashboard and choose **New → Blueprint**.
2. Connect `v-vekpawar/Biz-Agent`.
3. Select the `main` branch and approve `render.yaml`.
4. In the service environment settings, add `DATABASE_URL` using the Neon connection string.
5. Add the provider keys you have (Google, Groq, OpenRouter, Tavily). Cerebras is optional.
6. Deploy. Render health check uses `/health`.

The Docker image starts one Uvicorn worker and caps concurrent requests to reduce memory use. Render Free services can sleep when idle; do not use artificial ping/keep-alive services to evade this.

## 3. Local development

Local SQLite remains the default:
```bash
cd backend
python -m venv .venv
# activate the environment
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

Or run the Docker image locally:
```bash
docker build -t biz-agent .
docker run --rm -p 8000:8000 -e PORT=8000 -e BIZAGENT_ENV=development biz-agent
```

## 4. Deployment workflow

Use `main` as the deploy branch. Test locally, commit and push to GitHub, then Render automatically deploys the new commit. For a safer workflow, develop on a separate branch and merge reviewed changes into `main`.

## Notes

- Migrations run at application startup (`BIZAGENT_AUTO_MIGRATE=1`).
- Keep `BIZAGENT_SECRET_KEY` stable; Render Blueprint generates one on initial service creation.
- Do not add `.env`, database files, or uploaded documents to Git.
- If you later want uploaded source documents to persist, add object storage (for example, Supabase Storage or S3-compatible storage) rather than storing them on Render's ephemeral filesystem.
