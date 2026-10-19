# Tryout - Product Spec (v1)

## Problem
A company hiring for one role gets hundreds of applicants. Recruiters run 30-minute screening calls:
scheduling overhead, inconsistent questions, thin notes, and most applicants never hear back.

## Product
Two sides, one loop:

1. **Recruiter** creates a role: pastes the JD and notes (must-haves, red flags, what not to ask). The agent
   drafts the interview brief (sections, minutes, what to probe) and the scoring criteria (weight, bars). The
   recruiter edits and saves.
2. **Recruiter** adds candidates (name, email, resume). Each gets a private interview link.
3. **Candidate** opens the link any time, gives consent, and does a 10-20 minute voice interview. Questions are
   personalised from the resume; vague answers get specific follow-ups.
4. **Recruiter** gets a report within a minute: each criterion rated above / meets / below bar with quotes and
   timestamps, weighted score, strengths, concerns, resume-consistency flags, suggested next step. Candidates
   ranked per role.
5. **Recruiter** decides: Advance / Hold / Reject. The human always decides.
6. **Candidate** gets specific, kind feedback once the recruiter releases it.

## Principles
- Every rating is backed by a quote the candidate actually said (verified in code).
- Same brief and rubric for every candidate of a role.
- Never scores accent, fluency (unless the role needs it) or protected attributes.
- The interviewer never tells the candidate whether an answer is right, and never helps them answer.
- Consent and clear AI disclosure before the interview.

## Architecture
- **Role Compiler** (strong model, once per role): JD + notes -> sections + criteria.
- **Candidate Prep** (strong, once per candidate): resume -> highlights, claims to verify, personalised openers.
- **Turn Agent** (fast, every turn): records evidence per probe slot, acknowledgment + one follow-up question.
- **Engine** (code): time budget per section, coverage, probe limits, section switching. Code supplies the next
  section's question so the spoken question always matches the section.
- **Evaluator** (strong, once per interview): per-criterion rating + evidence quotes; code verifies quotes and
  computes the weighted score.

LLM: Groq free tier, one key, model per role with fallback (`.env`). Storage: JSON files in `data/`.

## Next
Proctoring (tab switches, face presence, second voice), paste and answer-timing integrity signals, email invites and
reminders, recruiter auth and candidate link expiry, ATS webhooks, LLM sensitivity check, calibration across
candidates. Interviews are English only.
