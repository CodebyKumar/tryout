# TryOut

An AI screening interviewer. A recruiter describes a role, TryOut drafts the interview and a scoring rubric, each
candidate talks with an AI interviewer from a private link, and the recruiter gets a report in which every rating
rests on a quote the candidate actually said, checked against the transcript. The AI suggests; a person decides.

## What it does

1. **Create a role** from a job description, a document or a template. The Role Compiler drafts timed interview
   parts (what to find out in each) and weighted criteria with bars. Edit by hand or in plain language; every change
   is a new version, and each candidate is scored on the version they were interviewed on.
2. **Invite candidates.** Each gets a private link that works any time or inside a window you set. Invite opens a
   ready-to-send message in your Gmail (or mail app), with a calendar file for scheduled interviews.
3. **The interview.** A voice conversation in the browser: Whisper transcribes, the Turn Agent writes the next line,
   Deepgram speaks it (or the browser's own voice). It follows up on vague answers and probes resume claims; code
   keeps the time, the order and the follow-up limits.
4. **The report.** Each criterion: rating, score out of 10, the quotes behind it linked to the transcript. Resume fit,
   integrity signals (never scored), the candidate's rating of the interview, and "How it decided": every turn's
   proposal from the model and what code kept or overrode.
5. **Decide.** Advance, hold or reject, only once there is a report; every change is logged.

## Engineering choices

| Area | What was built |
|---|---|
| Agents | One folder each (prompt, output model, code tools). The LLM proposes; code verifies quotes, computes scores and the suggestion, decides section changes, and replaces replies that judge an answer. |
| Context | The Turn Agent reads slot states, not the transcript: input at turn 40 is the size of turn 5 (tested). Static prompt text first, so Groq's prefix cache can hit. |
| Accounts | Sign up, admin approval, read-only demo. scrypt passwords; the login cookie's token is stored only as SHA-256. Every query is scoped to its owner; a test proves 404 on every route for another recruiter's ids. |
| Concurrency | Async FastAPI; no DB connection held during an LLM call. Background work is persisted jobs (claimed once, retried, requeued after a restart). Version-checked session writes, one tab per interview, and a cap on live interviews for the free LLM tier. |
| Integrity | Tab, focus, full screen, copy and paste, second screen and extension signals. Strict mode per role: full screen to start and a pause when it's left, copy, paste and right-click blocked, no start while a detectable extension is on. What a page cannot detect is said plainly. |
| Storage | Supabase Postgres (free tier) through SQLAlchemy 2 async and Alembic; tests run the same code on SQLite. |

Code map, routes, flows and the v2 design: [docs/system-design.md](docs/system-design.md).

## Run it

Needs [uv](https://docs.astral.sh/uv/), ffmpeg, a [Groq API key](https://console.groq.com/keys) and a Postgres URL
(a free Supabase project works). A [Deepgram key](https://console.deepgram.com) is optional: without it the room
uses the browser's voice.

```bash
./run.sh            # first run creates .env: add GROQ_API_KEY, DATABASE_URL and ADMIN_EMAIL, then run again
./run.sh migrate    # create the tables
./run.sh seed-demo  # optional: one real interview in the read-only demo account
```

Open http://localhost:8000 and sign up with your `ADMIN_EMAIL`: that account is the admin and is active at once.

| Command | What it does |
|---|---|
| `./run.sh start / stop / restart / status / logs` | Manage the server |
| `./run.sh dev` | Run with auto-reload |
| `./run.sh test` / `lint` | Tests (fake LLM, SQLite, offline) and lint |
| `./run.sh sim [strong\|vague\|bluffer\|injector]` | A full interview with a simulated candidate on the real LLM |
| `./run.sh share` | Public HTTPS link through a Cloudflare quick tunnel |
| `./run.sh docker` | Build and run the production image on port 7860 |

## Principles

- Every rating is backed by a verified quote from the candidate.
- Same brief and rubric for every candidate of a role version.
- Never scores accent, fluency (unless the role needs it) or protected attributes; integrity signals are never scored.
- The interviewer never says whether an answer is right and never helps the candidate answer.
- Consent and a clear AI notice before the interview.

Requirements: [docs/requirements.md](docs/requirements.md). Plan: [docs/tasks.md](docs/tasks.md).
