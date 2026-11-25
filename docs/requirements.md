# TryOut - Product requirements (v2)

Recorded 2026-11-25 from the owner's brief. This is the source of truth for what v2 must do. The plan that builds
it is [TASKS.md](../TASKS.md); the design is [system-design.md](system-design.md). When a requirement changes,
change it here first and date the change.

## 1. Goal

A deployed, public AI screening interviewer that goes on the owner's portfolio and resume. It should feel like a
standard product: few features, each one engineered well, and code a new reader can trace end to end.

What it demonstrates (the "objectives"):

| ID | Objective | What must be true |
|----|-----------|-------------------|
| O1 | Recreate the AI interview experience | Live two-way voice interview in the browser that adapts follow-ups to answers and the resume. |
| O2 | Scoring system | Rubric scoring per criterion, every rating backed by a verified quote, weighted score computed in code. |
| O3 | Context awareness | The interviewer knows the role brief, the resume, what is covered and what is missing, and the time left. |
| O4 | Intent regulation | The interviewer stays on task: it does not help the candidate answer, resists prompt injection, and steers off-topic turns back. The LLM proposes, code decides. |
| O5 | Integrity | Strict integrity checks during the interview, shown to the recruiter as evidence (see R7). |
| O6 | Shows how the system works | A reader of the repo or the docs can follow one interview from link to report. |

## 2. Users

| User | What they do |
|------|--------------|
| Admin (the owner) | Logs in, manages recruiter accounts, sees system health and usage. |
| Recruiter | Creates an account, logs in, creates roles, adds candidates, schedules interviews, reads reports, decides. Sees only their own data. |
| Candidate | Opens a private link, checks mic, consents, takes the interview, rates the experience. No account. |
| Visitor | Reads the home page, tries the demo. |

## 3. Requirements

### R1. Home page
- A public home page that explains what TryOut is and how it works, using only features that exist.
- Entry points: recruiter sign in, create account, and a way to try it.
- Works on mobile.

### R2. Accounts and login
- Recruiter account creation and login. Admin login with an admin role.
- Passwords hashed; session cookie; logout; every recruiter and admin route returns 401 without a session.
- Admin can see and disable recruiter accounts.

### R3. Multi-user data and database redesign
- Every role, candidate, interview and report belongs to one recruiter; a recruiter can never read another's data
  (enforced in the service queries, tested).
- Redesign the schema for multiple users (ownership, indexes for each list query, retention).
- Storage stays managed cloud Postgres (Supabase free tier). Tests run on in-memory SQLite.

### R4. Recruiter workspace
- Manage candidates per role: add, edit, delete, reset, see status at a glance.
- Schedule interviews: a time window when the link works, shown to the candidate.
- Get reports: per-candidate report and ranking per role.

### R5. Concurrency
- Many recruiters and many interviews at the same time on one server, without one slow LLM call blocking others.
- Background work (prep, evaluation) survives a restart and never runs twice.
- Clear behaviour when capacity is reached (the free LLM tier has rate limits): the candidate is told, nothing breaks.

### R6. AI agent context management
- Each agent gets only the context it needs, in a fixed order (instructions first, data last) to use prompt caching.
- Interview context stays bounded on long interviews (summaries of earlier sections, not the full transcript).
- Token use and latency per agent are recorded and visible.

### R7. Integrity checks during the interview
- Strict mode: full screen required, tab switches, window focus loss, copy, paste, second screen, long silences.
- Extension blocking: detect and report known extension footprints and block the interview start when a
  blocked one is found, where the browser allows detecting it.
- Honest limit: a web page cannot block or list browser extensions. Only a locked-down browser or desktop app
  can. TryOut detects what a page can see (injected DOM, known globals) and reports the rest as unverifiable.
- Signals are evidence for the recruiter, never part of the score.

### R8. Structure and traceability
- Backend and frontend folders organised so each file has one job and a reader can trace a request route by route.
- Explicit state management in the frontend; async work and database access in one documented place each.
- HLD and LLD written down and kept in sync with the code.

### R9. Resources
- Light on memory, storage and compute: small DB pool, no stored audio beyond what is needed, bounded in-memory
  state, no work repeated that could be cached.
- Runs on free tiers only (see the free-tier memory): Supabase, Groq, a free host.

### R10. UI and UX
- Planned UI with a consistent design system (tokens, components) across home, recruiter app and interview room.
- Smooth: loading, empty and error states on every data region; no layout jumps.
- Mobile view checked for every screen.
- Name: TryOut. Design a logo and use it everywhere (favicon, header, room, emails).

### R11. Honest content
- No filler text. Every label, number and claim on screen describes something the system really does.
- No features, stats or testimonials that do not exist.

### R12. Testing and deployment
- Every feature has a test on the fake LLM; multi-user isolation and concurrency have their own tests.
- Deployed at a public URL with a demo account; the README explains how to run it and how it works.

## 4. Out of scope (unless the owner adds it)
Billing, organisations and teams, ATS integrations, phone or WhatsApp interviews, video avatars, languages other
than English.

## 5. Owner's tooling request
Design skills installed 2026-11-25: ui-ux-pro-max (plugin), impeccable, huashu-design, Anthropic frontend-design,
plus hallmark (already present).

## 6. Decisions (2026-11-25)
- Sign-up open; admin approves before an account can run interviews; read-only demo account.
- Frontend: vanilla ES modules, no build step.
- Hosting: Hugging Face Spaces (Docker). Database and files: Supabase free tier.
- Invites: one click opens a filled-in Gmail draft, with `mailto:` and copy-text as alternatives, plus a calendar
  file. No mail server.
- Voice out: Deepgram Aura-2 (free credit), browser speech as fallback. Piper removed.
- Cleanup: code and docs that no longer serve the product are removed (TASKS Phase 5).

## 7. Change log
- 2026-11-25: v2 requirements and decisions recorded.
