# Tryout - Tasks

Overview: [README.md](README.md). Code map: [docs/system-design.md](docs/system-design.md).
Why each task exists: [docs/backend-audit.md](docs/backend-audit.md) (IDs like `B1`, `D3`, `F5` point there).
What v2 must do: [docs/requirements.md](docs/requirements.md) (IDs like `R5`, `O4` point there).
Run: `./run.sh start | stop | restart | status | logs | dev | test | sim [persona]`.

## Decisions

- **Backend first.** The backend is redesigned and verified before the main frontend work. Small frontend changes
  are made along the way only where needed to test a backend change by hand (marked `[UI]`).
- **Database: managed cloud Postgres only** (Neon or Supabase). No JSON files and no local database server in the
  running app. Tests use in-memory SQLite through the same SQLAlchemy models, so they stay fast and offline.
- **Original files** (JDs, resumes) go to the provider's object storage, not the server disk.
- Stack stays: Python 3.12, FastAPI, Pydantic, Groq. Added: SQLAlchemy 2.0 (async), asyncpg, Alembic.
- Every task ends with tests green (`./run.sh test`) and a short manual check where it says so.
- **Simple over clever** (ponytail plugin installed): the shortest code that a new reader can follow. Structure is
  added only where it removes confusion that exists today (agents in three places, `app.py` doing five jobs), not
  "for later".

## Done (v1 prototype)

- [x] Role from JD or document, AI brief + rubric, plain-language refine, manual edit
- [x] Candidates with private links, resume prep, fit %, personalised openers, claims to verify
- [x] Voice / text interview engine with section timing, probe limits, code-controlled section switching
- [x] Evaluator with verified quotes, weighted score, resume flags, candidate feedback
- [x] Recruiter report, ranking, decision, release feedback, reset
- [x] Groq client with fallback chain and rate-limit retry; fake-LLM tests; real-LLM simulator

---

## Phase 0 - Setup (today)

- [x] 0.1 Create the cloud Postgres project (Neon or Supabase) and a separate database / branch for development.
- [x] 0.2 Add `DATABASE_URL` and storage credentials to `.env.example` (no secrets committed).
- [x] 0.3 Add `ruff` for lint + format; `./run.sh lint`.
- [x] 0.4 Test helpers: `fake_llm` fixture shared across test files (`tests/conftest.py`).
- [x] 0.5 Baseline: record current `./run.sh sim vague` output (turn latency, score) to compare after the refactor.
  Baseline (`.run/baseline-sim-vague.txt`): 30 turns, score 3.0, avg turn 5.5 s (about 1 s when not rate limited),
  18 LLM calls, 41.6k prompt tokens, 186 s total. 23 Groq 429s: 7 fallback "say that once more" turns, up to 5 in a
  row. The free tier cannot carry one interview plus the simulated candidate; needs a paid tier before launch.

## Phase 1 - Correctness fixes on the current code

Small, local fixes that survive the restructure. One test per fix.

- [x] 1.1 `B1` Retrying after an LLM failure must call the LLM again (mark fallback turns, skip duplicate guard).
- [x] 1.2 `B11` Slot status only moves forward (`missing -> vague -> filled`), except to `conflict`.
- [x] 1.3 `B12` Count per-slot probes even when the Turn Agent omits `gap`.
- [x] 1.4 `B5` Clamp each criterion score into its rating band.
- [x] 1.5 `B6` Search all candidate turns when a quote is not in the cited turn; correct the turn id.
- [x] 1.6 `B4` Derive the recommendation in code from verified ratings and weights.
- [x] 1.7 `B2` Evaluation failure is visible: `EVAL_FAILED` state + error; `reevaluate` returns 503 on failure.
- [x] 1.8 `B3` Prep failure is visible: `prep_status` + error on the plan; `POST /api/candidates/{id}/prepare`.
- [x] 1.9 `B7` One `extract_text()` for PDF / DOCX / text, used by role and resume upload.
- [x] 1.10 `B13` Keep the original role document; store the summary separately.
- [x] 1.11 `B8` `TIME_BUDGET_SEC` from `.env` is the only default length.
- [x] 1.12 `B9` Manual role edits go through the same validator as compiled ones.
- [x] 1.13 `C6` Single-pass prompt rendering; escape closing data tags in user text.
- [x] 1.14 `C8` Upload limits (audio size / duration, document size); ffmpeg timeout.
- [x] 1.15 `C13` Replace `on_event("startup")` with `lifespan`.
- [x] 1.16 `[UI]` Show "prep failed - retry" on the candidate row and "evaluation failed - retry" on the report.
- [ ] Manual check: run one interview by voice, kill the LLM key mid-interview, confirm recovery and visible errors.

## Phase 2 - Agent contract

Make every agent look the same: inputs, outputs, code tools, failure behaviour. See audit 5.2.

- [x] 2.1 `agents/base.py`: `AgentSpec` + `run_agent()` returning result + `Usage(model, prompt_version, tokens, latency)`.
- [x] 2.2 Pydantic output model per agent; parse with `model_validate` + one repair; prompt example generated from it.
  Output models are lenient on harmless sloppiness (nulls, junk list items). Prompt examples stay hand-written:
  generating them would change every prompt for no gain, and the models now document the shape in `spec.py`.
- [x] 2.3 Move each agent into its own folder (`spec.py`, `prompt.md`, `tools.py`, tests):
  - [x] Role Compiler
  - [x] Role Refine (split out of `role_compiler.py`)
  - [x] Candidate Prep
  - [x] Turn Agent (moved out of `engine/engine.py`)
  - [x] Evaluator
  Tests stay in `tests/` (`test_agents.py`, `test_evaluator.py`, `test_engine.py`) next to the shared fixtures in
  `conftest.py`; a `tests/` folder per agent would need its own conftest wiring for no gain.
- [x] 2.4 `C5` Per-agent timeout and token limit from the spec.
- [x] 2.5 `C3`, `C4` Usage recorded for every agent; reports record model + prompt version.
- [x] 2.6 `FakeLLM` validates handler output against the agent's output model.
- [x] 2.8 Token and call efficiency (Groq caches exact prompt prefixes; cached tokens are half price and do not count
  toward rate limits, gpt-oss models only):
  - every prompt puts fixed instructions first and per-call data last (test guards it); prompt_version 2
  - the wrap-up answer makes no LLM call (one Turn Agent call saved per interview)
  - rate-limited models are skipped until their limit clears, shared across requests; no request is sent that is
    known to fail; when all are limited, wait only within the agent's budget (turn 15 s), else fail without a call
  - a model that rejects `reasoning_effort` is remembered (no rejected request per call)
  - usage counts repair calls and cached tokens; the interview usage summary shows both
- [x] 2.7 Engine has no LLM imports; split `engine.py` into `state_machine.py` + `heuristics.py`; PII to `safety/pii.py`.
- [ ] Manual check: `./run.sh sim vague` and `sim bluffer` match the Phase 0 baseline in quality and latency.

## Phase 3 - Services layer

HTTP handlers become thin; orchestration lives in one place. See audit 5.1 and system design B3.

- [x] 3.1 `services/roles.py`, `candidates.py`, `interviews.py`, `evaluation.py`.
- [x] 3.2 `api/recruiter.py`, `api/candidate.py`, `api/views.py`; `app.py` only builds the app.
- [x] 3.3 `integrations/`: `llm.py`, `groq.py` (shared transport + retry, `C9`), `stt.py` (+ noise filter), `tts.py`, `documents.py`.
- [x] 3.4 Only `services/` calls `store.py`; routes, agents and the engine never touch storage.
- [x] 3.5 Update [docs/system-design.md](docs/system-design.md) Part A to the new layout.
- [x] 3.6 Hard-coded values: anything a recruiter or operator would tune (probe limits, wrap-up reserve, default
  length, model limits, upload caps) moves to `config.py` or the role's policy. True constants (`_STOP`,
  `_FILLERS`, `_SCORES`, `_NOISE`, `BASE_VOCAB`, PII regexes) stay in code next to the function that uses them,
  each with a one-line reason.
- [~] 3.7 Readability pass: imports at the top (no inline `import re, zipfile`), one job per function, names that
  say what they do (`Target` -> `Section` in code and API, matching what the prompts and UI call it).
  Imports at the top and one job per function: done. `Target` -> `Section` moves to Phase 4: the name is also
  a JSON field (`target_id`) in saved data, two prompts and the frontend, so it changes once, with the new schema.
  Model limits (tokens, timeouts) stay in each agent's `spec.py`, next to the prompt they belong to.
- [ ] 3.8 (moved to 5.4) Run `/ponytail-audit` on the backend; cut what it finds unless the audit gives a reason to keep it.
- [ ] Manual check: full recruiter -> candidate -> report flow in the browser, nothing changed for the user.

## Phase 4 - Cloud database

Schema from audit 8.4, lean variant (decided 2026-10-22): 12 tables in [backend/tables.py](backend/tables.py);
nested structures (a brief's sections and criteria, a plan, a session's engine state, a report) are JSON columns.
Supabase free tier, Session pooler (IPv4). Every table has RLS on with no policies: the app connects as owner, the
public REST API is blocked. `alembic upgrade head` applies migrations; `TEST_DATABASE_URL` runs tests on Postgres.

- [x] 4.0 `Target` -> `Section` in code, API, prompts (version bump) and frontend; the import maps old field names.
- [x] 4.1 SQLAlchemy models + Alembic `0001_initial` for all tables in audit 8.4.
- [x] 4.2 `db.py` (engine + async session) and `tables.py`; services query through SQLAlchemy directly, no
  repository layer on top. Tests run the same code on in-memory SQLite.
- [x] 4.3 `D1`, `D2`, `A2` Role versions: compile / refine / edit create a new version; plans and evaluations point at one.
- [x] 4.4 `D3` A turn is one transaction: insert turn, update slot and section states, insert llm_call.
- [x] 4.5 `D4` Every evaluation run is kept; one is current.
- [~] 4.6 `D8` Original files to object storage; `documents` table keeps extracted text.
  Text is kept for every upload. File upload to Supabase Storage is built and off until `SUPABASE_URL` and
  `SUPABASE_SECRET_KEY` are in `.env` (free tier; the `documents` bucket exists).
- [x] 4.7 `D9`, `C7` Indexed token lookup; ranking as one query.
- [x] 4.8 `scripts/import_json.py`: import existing `data/*.json`, then verify counts and one report by hand.
- [x] 4.9 Remove `store.py` and `data/` usage.
- [x] 4.10 `[UI]` Warn when editing a role that has invited candidates; show which brief version a candidate got.
- [ ] Manual check: two candidates on brief v1, refine role, third candidate on v2; reports score against their own version.

---

# v2 - deployed product (planned 2026-11-25)

Requirements: [docs/requirements.md](docs/requirements.md). Design (HLD and LLD):
[docs/system-design.md Part B](docs/system-design.md#part-b---v2-design). Decisions taken 2026-11-25:

- Sign-up is open, and an admin approves an account before it can run interviews. A shared demo account is read-only.
- Frontend stays vanilla ES modules with no build step: one file per screen, a small router, a small store.
- Hosting: Hugging Face Spaces (free Docker, 16 GB RAM). Database and files stay on Supabase free tier.
- Invites: one click opens a filled-in Gmail draft (or `mailto:`, or copy the text), plus a calendar file. No mail
  server.
- Voice out: Deepgram Aura-2 (free $200 credit, no card), with browser speech as fallback; Piper is removed to keep
  the server light.
- One server process (uvicorn, one worker). Anything that must stay correct with more than one process (jobs, turn
  writes) is guarded in the database, not in memory.

Each phase ends with `./run.sh test` green, and with the manual check where one is listed.

## Phase 5 - Cleanup (started 2026-11-25)

- [x] 5.1 Remove leftovers: `scripts/import_json.py`, `config.DATA_DIR`, `docs/architecture.md` and the v1 spec
  `docs/README.md` (replaced by system-design.md and requirements.md).
- [x] 5.2 Fold `docs/product-roadmap.md` into this file (Phases 9 to 12 and Later), then delete it.
- [ ] 5.3 Land the work in progress (integrity signals, role templates, scores out of 10, cobalt UI) as one reviewed
  change before v2 starts, so v2 starts from a clean tree.
- [ ] 5.4 `/ponytail-audit` on backend and frontend; delete what it finds unless there is a reason to keep it.

## Phase 6 - Jobs, lifecycle, concurrency (`R5`)

- [ ] 6.1 `services/jobs.py`: prep and evaluation run as rows in `jobs` (attempts, error, backoff). One worker loop
  claims a job with `FOR UPDATE SKIP LOCKED`, so a job never runs twice (`A3`). Replaces `asyncio.create_task`.
- [ ] 6.2 On startup, jobs left `running` by a crash go back to `queued`.
- [ ] 6.3 Idle sweeper (same loop): an interview with no turn for 10 minutes is ended and queued for evaluation.
- [ ] 6.4 Turn writes use a `version` column on `sessions` (update only if unchanged), so two tabs or a double
  submit get 409 instead of a corrupt transcript. The in-memory lock map stays as a fast path and is bounded.
- [ ] 6.5 Admission control: `MAX_LIVE_INTERVIEWS` (counted from the database). Over the limit, the candidate sees
  "all interview slots are busy, try again in a few minutes"; nothing is started.
- [ ] 6.6 `A4` Reset or delete during evaluation cannot bring data back or leave orphans.
- [ ] 6.7 `C1`, `B10`, `D6` Hiring decision is separate from interview status; `decisions` audit log (`D10`).
- [ ] Tests: job claimed once by two workers; restart requeues; idle sweep; 409 on stale write; admission limit.
- [ ] Manual check: restart the server mid-interview and mid-evaluation; both finish with a report.

## Phase 7 - Accounts and multi-user (`R2`, `R3`)

- [ ] 7.1 Migration `0004`: `recruiters` gains `name`, `status` (pending / active / disabled), `is_admin`;
  `auth_sessions` table (hashed token, expiry); `roles.recruiter_id` required; candidates get `token_hash`,
  `opens_at`, `closes_at`; drop `feedback_released`. Existing data moves to the admin account.
- [ ] 7.2 `services/accounts.py`: sign up, log in, log out. Passwords with `hashlib.scrypt` (standard library).
  Session cookie: HttpOnly, Secure, SameSite=Lax, 14 days. Login attempts limited per email.
- [ ] 7.3 `api/deps.py`: `current_recruiter` and `current_admin` dependencies; every recruiter and admin route uses
  one. Pending accounts can sign in and see the demo, but cannot create roles or invite.
- [ ] 7.4 Ownership: every service query on roles, candidates, sessions and reports filters by recruiter. One
  helper loads an owned role or raises NotFound (404, never 403, so ids are not probed).
- [ ] 7.5 Admin: list recruiters, approve, disable; usage per recruiter (LLM calls, interviews); live interviews.
  First admin from `ADMIN_EMAIL` in `.env`.
- [ ] 7.6 Candidate tokens stored hashed; reset issues a new link; link outside its window says when it opens.
- [ ] 7.7 Demo account: seeded role from a template with one finished interview, read-only.
- [ ] Tests: every recruiter route returns 401 logged out, and 404 for another recruiter's ids (one parametrised
  test over the route list); pending account cannot invite; admin-only routes refuse recruiters.

## Phase 8 - Scheduling, candidates, reports (`R4`)

- [ ] 8.1 Schedule: set an interview window when adding or editing a candidate; the room shows it.
- [ ] 8.2 Invite and reminder: Gmail compose link, `mailto:` link and copy-text, all from one template; `.ics`
  calendar file endpoint.
- [ ] 8.3 Candidate list per role: one status column (invited, scheduled, in progress, evaluating, ready, decided,
  failed) with inline retry; edit, delete, reset.
- [ ] 8.4 Reports: per-candidate report, ranking per role, read-only share link with expiry.
- [ ] Tests: window enforced in the candidate API; ics content; share link expires.

## Phase 9 - Agent context and intent regulation (`R6`, `O3`, `O4`)

- [ ] 9.1 Context budget: a test runs a 40-turn interview on the fake LLM and asserts the Turn Agent input stays
  under a fixed token count (slots are the memory, not the transcript).
- [ ] 9.2 Intent regulation in code: when the agent flags injection or off-topic, the engine keeps the section and
  asks the bridge question; a reply that answers the question for the candidate is replaced. Sim `injector` passes.
- [ ] 9.3 Latency: time from candidate audio received to reply audio ready, per turn, in `llm_calls`; p50 and p95
  in the sim output and the admin page.
- [ ] 9.4 Agent trace view (recruiter): per turn, slot updates, the gap chosen, what code overrode, tokens,
  latency. This is the page that shows how the system works (`O6`).
- [ ] 9.6 TTS: `integrations/tts.py` calls Deepgram Aura-2 when `DEEPGRAM_API_KEY` is set; otherwise the room uses
  browser speech. Remove `piper-tts` and `PIPER_MODEL`. Test: fallback chosen without a key.
- [ ] 9.5 Room reconnect: a dropped network resumes the same session; the candidate can interrupt playback.

## Phase 10 - Strict integrity (`R7`, `O5`)

- [ ] 10.1 Role setting `integrity`: standard (signals only) or strict.
- [ ] 10.2 Strict: full screen required to start; leaving it pauses the interview behind an overlay until back;
  copy, paste, right-click and text selection blocked in the room; one open tab per link (6.4).
- [ ] 10.3 Extension check before start: known injected markers (for example Grammarly attributes, AI sidebar
  elements), `chrome-extension://` resources, and unknown elements injected into the page. Strict mode blocks the
  start and names what was found; the report lists it. The lobby says plainly what cannot be checked.
- [ ] 10.4 Report: integrity timeline next to the transcript; never part of the score.
- [ ] Tests: summary levels; strict start refused with a found extension; events capped.

## Phase 11 - Brand, design system, home page (`R1`, `R10`, `R11`)

- [ ] 11.1 Name TryOut; logo (SVG mark + wordmark), favicon, used in every page header, the room and the invite.
- [ ] 11.2 Design system: `tokens.css` (colour, type, spacing, radius), `base.css`, `components.css` (button,
  field, table, badge, card, toast, dialog, the loading / empty / error state). One accent.
- [ ] 11.3 Home page: what TryOut does, how one interview flows, what the report shows, sign in and sign up, try
  the demo. Every sentence describes a feature that exists. Screens are real screenshots.
- [ ] 11.4 Login, sign up, pending approval pages.

## Phase 12 - Frontend structure and screens (`R8`, `R10`)

- [ ] 12.1 `frontend/js/lib/`: `api.js` (fetch, errors, 401 to login), `store.js`, `router.js`, `dom.js`, `ui.js`.
- [ ] 12.2 Recruiter app, one module per screen: roles, role brief, candidates, report, compare, trace, settings.
- [ ] 12.3 Admin app: recruiters, usage, live interviews.
- [ ] 12.4 Room: lobby (mic check, consent, AI notice, extension check), interview, done. Split `interview.js`.
- [ ] 12.5 Every data region has loading, empty and error states; state is in the URL.
- [ ] 12.6 Mobile: every screen checked at 375 px and 768 px; the room works on a phone browser in standard mode
  (strict mode needs a desktop and says so).

## Phase 13 - Deploy (`R12`)

- [ ] 13.1 `Dockerfile`: python 3.12 slim, ffmpeg, uv; port 7860;
  `alembic upgrade head` before start.
- [ ] 13.2 Production Supabase project (Mumbai region) separate from dev; secrets in the Space settings.
- [ ] 13.3 GitHub Actions: lint and tests on every push.
- [ ] 13.4 Hugging Face Space from the repo; health check; demo account seeded.
- [ ] Manual check: sign up on the live URL, approve as admin, run an interview on desktop and phone, read the report.

## Phase 14 - Sign-off

- [ ] 14.1 Every requirement in docs/requirements.md met or deferred with a reason.
- [ ] 14.2 Sim personas (strong, vague, bluffer, injector) give sensible reports on the live build.
- [ ] 14.3 Docs: README (what, how it works, diagram, run, deploy), system design matches the code.
- [ ] 14.4 Resume and portfolio text that lists only what was built.

## Later

- Fairness check in the sim (swap name and pronouns, scores must not move).
- Evaluator calibration: run twice on borderline scores, flag disagreement.
- Proctoring with camera: face presence, second voice.
- Bulk candidate import (CSV).
