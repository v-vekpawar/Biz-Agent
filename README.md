# Autonomous Multi-Agent Business Planning System

Capstone project. Phase 0 scaffold — see `build-order.md` for the full plan (not included in this repo, comes from your project docs).

## Repo structure

```
biz-agent-system/
├── backend/
│   ├── app/
│   │   ├── __init__.py
│   │   └── main.py          # FastAPI app — Phase 0 has just one hello endpoint
│   ├── requirements.txt
│   └── .env.example         # copy to .env and fill in real keys
├── frontend/
│   ├── index.html           # Tailwind via CDN, no build step
│   └── app.js
└── .gitignore
```

## 1. Get your free API keys

You need three. All have generous free tiers as of early 2026 — double check current limits on each site since they do change.

| Service | What it's for | Where to get it |
|---|---|---|
| **Groq** | Fast inference for the specialist agents (Llama 3.3 70B) | [console.groq.com/keys](https://console.groq.com/keys) — sign up, create an API key |
| **Google AI Studio (Gemini)** | Critic/Verifier + Synthesizer agents (Gemini Flash) | [aistudio.google.com/apikey](https://aistudio.google.com/apikey) — sign in with Google, create a key |
| **Tavily** | Web search tool for agents | [tavily.com](https://tavily.com) — sign up, key is on your dashboard |

Once you have all three, copy the example env file and fill it in:

```bash
cd backend
cp .env.example .env
# then open .env and paste in your three keys
```

`.env` is already in `.gitignore` — it will never get committed.

## 2. Backend setup

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

Note: `requirements.txt` includes everything for the *whole* build (LangGraph, ChromaDB, WeasyPrint, etc.), not just Phase 0, so you only do this install once. If any single package fails on your OS (WeasyPrint has some native dependency quirks on Windows), you can comment it out for now and revisit at Phase 7 — it won't block Phase 0-6 work.

Run the server:

```bash
uvicorn app.main:app --reload --port 8000
```

You should see it come up on `http://127.0.0.1:8000`. Visit `http://127.0.0.1:8000/api/hello` directly in a browser — you should get back:

```json
{"message": "Hello from FastAPI — your Phase 0 checkpoint works."}
```

## 3. Frontend setup

No build step, no npm. Just serve the folder statically so `fetch()` works properly (opening `index.html` directly via `file://` can cause CORS quirks in some browsers, so a tiny local server is safer):

```bash
cd frontend
python3 -m http.server 5500
```

Then open `http://127.0.0.1:5500` in your browser.

Click **"Ping backend"** — if the backend is running, you'll see a green success message. That's your Phase 0 checkpoint, done.

## Troubleshooting

- **CORS error in browser console**: confirm the backend is actually running on port 8000 and that `app.js`'s `API_BASE_URL` matches.
- **`ModuleNotFoundError`**: make sure your virtual environment is activated before `pip install` and before `uvicorn`.
- **Port already in use**: change `--port 8000` to something else, and update `API_BASE_URL` in `app.js` to match.

## What's next

Do **not** start building the LangGraph pipeline directly into this FastAPI app yet. Per the build order, Phase 1 (orchestrator + first specialist agents) should be built and tested as a standalone Python script or notebook first — only once that works end-to-end do you wrap it in FastAPI (Phase 8). Wiring agents straight into the backend now will make debugging LangGraph much harder.
