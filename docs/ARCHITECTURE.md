# Architecture

One FastAPI process: JSON API (`/api/v1`), the web app (`/app`), public pages (`/p/{slug}`, `/d/{token}`), `/health`.

```
Browser (vanilla JS SPA) ──► routes ──► services ──► repositories ──► SQLite/Postgres
Public visitor ───────────► /p/{slug} (server-rendered HTML + 2 JSON endpoints)
                                │
              scan job (BackgroundTasks) ──► research engine ──► LLM / Tavily (lazy, optional)
```

Layering rules: routes do HTTP only; services hold use-cases and rules; repositories are the only write path.
Provider SDKs are imported lazily, so the app boots with no keys.

## Data model

| Table | Notes |
|---|---|
| `users` | email (unique, lowercase), scrypt password hash, display name |
| `business_cases` | `owner_id` -> users (cascade). Every query is owner-scoped |
| `hypotheses`, `evidence`, `hypothesis_evidence`, `hypothesis_assessments`, `investigation_runs`, `uploaded_documents`, `experiments`, `experiment_outcomes`, `experiment_criteria_revisions` | research engine (v3). Assessments are append-only |
| `scan_jobs` | persisted state of a scan (status, step, progress, warnings, result). Interrupted jobs are failed at startup |
| `sprints` | `content` + `protocol` JSON (frozen at lock), `protocol_hash`, `locked_at`, `slug` (public), `dossier_token` (separate secret), `dossier_enabled` |
| `sprint_visits` | unique `(sprint, visitor_hash)`; hash = HMAC(secret, slug:browser-id). No IP/UA |
| `sprint_signups` | unique `(sprint, email)`; exclusions have `excluded_at` + reason, never deleted |
| `sprint_signals` | logged conversations, same exclusion model |
| `sprint_verdicts` | immutable snapshot (inputs + output + protocol hash) written on conclude |

State machine: `draft -> running <-> paused -> concluded`. Locking is one-way; after the deadline or conclusion the public
endpoints return 410 so the sample can't be extended.

## Security model

- Auth: scrypt hashes; HS256 JWT (7-day default); generic login errors; constant-time verification even for unknown emails.
- Authorisation: ownership is enforced in the dependency layer (`deps.py`). Other users' ids return 404, not 403.
- Public endpoints: per-IP rate limits, honeypot field, consent required, identical response for new/duplicate/honeypot signups.
- Public HTML: all dynamic text escaped; per-request CSP nonce on the one inline script; `frame-ancestors 'none'`, `noindex`, `no-referrer`.
- App UI: dynamic text is set with `textContent` (a DOM builder; no `innerHTML`).
- CSV export neutralises formula injection. Uploads are extension- and size-checked.
- Secrets: production refuses to boot without `BIZAGENT_SECRET_KEY`. `.env` is git-ignored.

## Failure policy of the scan

Fatal (job fails with a clear message, nothing invented): assumption extraction fails, the planner can't plan,
assessment fails, the AI provider is unreachable. Non-fatal (recorded as warnings, scan continues): no search key, no
source fetcher, per-source verification trouble. Missing evidence becomes "no usable evidence found", ranked as an **open** risk.

## Extending

- Move scan jobs to a real queue (RQ/Celery) and the rate limiter to Redis before running more than one worker.
- Add email verification and password reset before open registration.
- A paid-pilot / pre-order metric would strengthen the commitment evidence beyond a waitlist.
