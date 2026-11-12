# Biz-Agent 5.0

**Find out whether people want your idea before you build it.**

Biz-Agent finds what is most likely to sink a business idea, then helps you test the riskiest part
with real people against a pass/fail rule you **lock before any data arrives**. The verdict is computed
by code from real signups, not written by an AI.

```
 Idea ──► Risk scan ──► Customer test ──► Verdict + brief
          (AI + web     (public page,     (Go / Pivot / Stop,
           research,     locked rule,      computed by a fixed
           ranked)       real signups)     statistical rule)
```

| Step | What happens | Who decides |
|---|---|---|
| **Risk scan** | Extracts the assumptions the idea depends on, searches for evidence for *and against* each, checks the sources, ranks the risks | AI proposes, code ranks |
| **Customer test** | A hosted public page + interview log. The claim, thresholds, sample size and deadline are **pre-registered** (sha256 fingerprint) when you lock | You set the bar once |
| **Verdict** | Wilson score interval vs. your locked floor/target. Early readings are labelled as such | **Code**, never an LLM |
| **Evidence dossier** | Read-only public link: locked rule, counts, verdict, every exclusion you made. Never shows emails | You choose to share it |
| **Decision brief** | 2-page PDF (verdict, top risks, test + results, sources). Generated on click, streamed to the browser, **never stored** | n/a |

Why this is not "just ask ChatGPT": see [docs/PRODUCT.md](docs/PRODUCT.md).

## Quick start (Windows / macOS / Linux)

```bash
git clone <your-repo> && cd biz-agent-5.0
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r backend/requirements.txt
cp .env.example .env                                   # Windows: copy .env.example .env
# edit .env: set BIZAGENT_SECRET_KEY and one or more free-tier LLM keys;
# Gemini/Groq are supported, with optional Cerebras and OpenRouter free-model fallbacks.
# Add TAVILY_API_KEY for web research. Leave BIZAGENT_ENV=development locally.
cd backend
uvicorn app.main:app --reload --port 8000
```

Open <http://localhost:8000> (the API serves the app at `/app`). Migrations run automatically on startup.
Interactive API docs: <http://localhost:8000/docs>.

**No API keys yet?** Everything except the AI parts works: accounts, ideas, writing a test by hand, the
public page, signups, the verdict engine, the dossier, and the PDF. The scan and "Generate with AI" report
a clear message instead of failing silently.

## Hosting it

The app is one process serving the API, the web app and the public test pages.

## What's new in 5.0

- **Free-first multi-provider LLM fallback:** Gemini → Groq → Cerebras → OpenRouter, using only configured providers. OpenRouter is pinned to `openrouter/free` by default and rejects paid model IDs. Configure `BIZAGENT_LLM_ORDER` to change the order.
- **Provider status:** signed-in users can open "AI providers" in the top bar or call `/api/v1/ai/providers`. It shows configuration only, never API keys.
- **Faster risk scans:** independent Tavily search requests run concurrently with a bounded worker count (`BIZAGENT_SCAN_SEARCH_CONCURRENCY`, default 3). Prompts, evidence verification, assessment rules and risk ranking are unchanged; database writes remain serial.
- **Idea-specific landing pages:** AI-generated drafts now select from safe design palettes and layout styles suited to the business category. Founders can edit the palette and style before locking.
- **Multiple experiments per idea:** a Validation Hub lets a founder create, run and switch between separate, independently locked tests for different hypotheses.

### Free-tier and billing safeguards

Biz-Agent never automatically chooses a paid OpenRouter model. Its default OpenRouter target is `openrouter/free`, which routes only to free models. For Cerebras, Gemini and Groq, the API key's account tier and billing settings are controlled by those providers and cannot be inspected by Biz-Agent. Use their free accounts/tiers and set any available provider-side spending limits. Free-tier rate limits still apply; failover improves resilience but cannot guarantee uninterrupted service.


```bash
cp .env.example .env     # set BIZAGENT_ENV=production, BIZAGENT_SECRET_KEY, BIZAGENT_PUBLIC_URL, LLM keys
docker compose up -d --build
```

Checklist for a real deployment:
- **HTTPS** in front (Caddy, nginx, or your host's TLS) and `BIZAGENT_PUBLIC_URL=https://your.domain` so share links are correct.
- **Persistent storage** for `/data` (SQLite + uploads) or set `DATABASE_URL` to Postgres (`pip install "psycopg[binary]"`).
- **One worker.** Scan jobs run in-process and the rate limiter is in-memory. Scale up only after moving both out of process.
- Configure at least two free-tier LLM providers if you want automatic provider failover. OpenRouter free requests are rate-limited and are a last-resort fallback, not unlimited capacity.
- Set `BIZAGENT_ALLOW_REGISTRATION=false` once your testers have accounts if you don't want open sign-up.
- Behind a proxy, set `BIZAGENT_TRUST_PROXY=1` so rate limits use the real client IP.
- Back up the database. It contains your testers' signups.

## Tests

```bash
cd backend && pip install -r requirements-dev.txt && pytest -q          # 86 tests, ~30 s, no network
python scripts/e2e_smoke.py                                             # browser end-to-end (needs a running server + Playwright)
python scripts/simulate_traffic.py <page-url> --visitors 60 --signups 12 # fake visitors, to see verdicts (testing only)
```

The unit/API tests run the Alembic migrations from scratch on every test, stub the LLM and search providers,
and cover: the statistics, auth and cross-user isolation, pre-registration immutability, the public page and
its CSP, visitor/signup de-duplication, rate limits, verdict progression, exclusions, the dossier, the scan job
(including failure policy), AI-draft validation, and the PDF.

## Project layout

```
backend/app/
  api/            routes, schemas, dependencies (auth + ownership checks live in deps.py)
  services/       stats.py (verdict engine) · sprints.py (pre-registration lifecycle) · riskscan.py ·
                  testkit.py (AI draft) · brief.py · research engine: extraction/investigation/verification/assessment
  repositories/   the only write path to the database (append-only where it matters)
  reports/        brief_pdf.py (ReportLab, bundled Roboto fonts)
  web/pages.py    public test page, owner preview, dossier (self-contained HTML, no third-party requests)
  domain/         SQLAlchemy models + enums
backend/alembic/  migrations (v4 = 4a1d7c9e2b30)
frontend/         vanilla JS single-page app, no build step
docs/             TESTING_WALKTHROUGH.md · PRODUCT.md · ARCHITECTURE.md · STATS.md
evaluation/       backtest case template
```

## Honest limits

- **Not exercised against live AI providers.** This version was built and tested without live credentials for
  Gemini, Groq, Cerebras, OpenRouter or Tavily. The scan and AI draft are covered by stubbed tests and by running the
  real wiring up to the network call (which fails with a clear message). Run one real scan with your keys before
  you demo it, and read the first output critically.
- **The Docker image has not been built here** (no Docker in the build environment). The Dockerfile is straightforward, but verify it.
- **A waitlist signup is evidence of interest, not of willingness to pay.** The product says so everywhere; the
  higher-commitment step (pre-order, paid pilot) is what the "interview commitment" metric is for.
- **Desk research can only find reasons an idea may fail.** It can't show demand.
- **No email verification or password reset.** Add them before opening registration to the public.
- Pre-v4 data (v3 databases) is not migrated to user accounts; those rows stay in the file but are unreachable.
- The v3 research API (hypotheses, evidence, assessments, experiments) is still present under `/api/v1` and
  owner-scoped, but the new UI drives it only through the scan.
- Google Fonts load from Google for the app UI (the public test pages and dossier use system fonts and make no third-party requests).
