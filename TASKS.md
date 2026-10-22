# Tryout - Tasks

Overview: [README.md](README.md). Code map: [docs/system-design.md](docs/system-design.md).
Why each task exists: [docs/backend-audit.md](docs/backend-audit.md) (IDs like `B1`, `D3`, `F5` point there).
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
- [ ] 3.8 (moved to Phase 7) Run `/ponytail-audit` on the backend; cut what it finds unless the audit gives a reason to keep it.
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

## Phase 5 - Jobs and lifecycle

- [ ] 5.1 `jobs` table runner: evaluation and prep retries run as jobs with attempts and errors (`A3`).
- [ ] 5.2 On startup, re-queue `queued` / `running` jobs.
- [ ] 5.3 Idle sweeper: interviews with no turn for 10 min are ended and evaluated.
- [ ] 5.4 `A4` Reset / delete during evaluation cannot resurrect or orphan data.
- [ ] 5.5 `C1`, `B10`, `D6` `decision` separate from interview status; decision and feedback only after a report.
- [ ] 5.6 `D10` `decisions` audit log.
- [ ] 5.7 `[UI]` Decision buttons disabled until a report exists; show decision history.
- [ ] Manual check: restart the server mid-evaluation and mid-interview; both finish with a report.

## Phase 6 - Auth and privacy

- [ ] 6.1 `A1` Recruiter accounts, login, session cookie; all recruiter routes return 401 without it.
- [ ] 6.2 Candidate tokens stored hashed, with expiry and revoke; reset issues a new link.
- [ ] 6.3 Roles and candidates scoped to the recruiter who owns them.
- [ ] 6.4 `C11` Candidate view shows progress only, no coverage.
- [ ] 6.5 Data retention setting: purge resumes and transcripts after N days.
- [ ] 6.6 `[UI]` Login page and logout.
- [ ] Manual check: `./run.sh share`, open the public link logged out, confirm nothing recruiter-side is reachable.

## Phase 7 - Backend sign-off

- [ ] 7.1 Every P0 and P1 finding in the audit closed or explicitly deferred.
- [ ] 7.2 Tests cover each agent's tools, the engine rules, and each service flow.
- [ ] 7.3 Sim personas (strong, vague, bluffer, injector) all produce sensible reports.
- [ ] 7.4 Docs updated: README architecture table, system design, audit marked with what was fixed.

## Phase 8 - Frontend (after backend sign-off)

- [ ] 8.1 Review the recruiter app and interview room against the new API.
- [ ] 8.2 Recruiter: role versions and diffs, candidate list states (prep, interviewing, evaluating, failed, decided).
- [ ] 8.3 Report: evidence timeline with flags, evaluation history.
- [ ] 8.4 Candidate room: clearer errors and retry for voice and network failures.

## Later

- [ ] `F10` Integrity signals: tab switches, paste, answer timing, shown on the report timeline (never scored).
- [ ] Proctoring: face presence, second voice.
- [ ] Email invites and reminders.
- [ ] Bulk candidate import (CSV).
- [ ] Evaluator calibration: run twice, flag disagreements.
- [ ] ATS webhooks.
