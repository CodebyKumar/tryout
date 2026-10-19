# Tryout

An AI voice screening interviewer. A recruiter uploads a job description, Tryout designs the interview and the
scoring rubric, each candidate does a short resume-personalised voice interview from a private link, and the
recruiter gets an evidence-backed report to decide Advance / Hold / Reject.

Every rating in a report cites what the candidate actually said, with a timestamp, and the quote is verified in code
against the transcript. The AI suggests; a human always decides.

## How it works

1. **Recruiter creates a role** from a JD, interview guidelines, a rubric or rough notes (PDF, DOCX or text).
   Tryout drafts the interview brief (sections, time per section, what to probe) and weighted scoring criteria with
   bars. The recruiter can refine it in plain language.
2. **Recruiter adds candidates** with their resume. Each candidate gets a private interview link, a resume-fit score
   and a list of resume claims worth verifying.
3. **Candidate interviews** any time: consent and AI disclosure, then a 10-20 minute voice interview in a video-call
   style room. Openers are personalised from the resume; vague answers get a specific follow-up.
4. **Recruiter reviews the report**: per-criterion above / meets / below bar with quotes, weighted score, strengths,
   concerns, resume-consistency flags and a suggested next step. Candidates are ranked per role.
5. **Recruiter decides** and releases specific, kind feedback to the candidate.

## Architecture

| Component | Model | Runs | Job |
|---|---|---|---|
| Role Compiler | strong | once per role | Hiring document -> interview sections + rubric |
| Candidate Prep | strong | once per candidate | Resume -> highlights, claims to verify, personalised openers, fit score |
| Turn Agent | fast | every turn | Records evidence per probe slot, acknowledgment + one follow-up |
| Interview Engine | code | every turn | State machine: time budgets, coverage, probe limits, section switching |
| Evaluator | strong | once per interview | Per-criterion rating with quotes; code verifies quotes and computes the score |

The LLM proposes, the engine decides. Section changes, timing and scoring are deterministic, so every candidate for a
role gets the same brief and rubric.

**Voice:** Groq Whisper speech-to-text (prompted with role and resume vocabulary), local Piper text-to-speech, FFmpeg
normalisation so Chrome and Safari recordings both work.

**Stack:** Python 3.12, FastAPI, Pydantic, Groq (per-role model fallback chain with rate-limit retry), vanilla
JavaScript, JSON file storage, Pytest.

```
backend/
  app.py            API + static frontend
  engine/           interview state machine and deterministic policy
  agents/           role compiler, candidate prep, evaluator
  llm/client.py     Groq client with fallback and retry
  prompts/          prompt templates
  voice.py          Whisper STT, Piper TTS
frontend/           recruiter app and candidate interview room
scripts/simulate.py real-LLM candidate simulator
tests/              flow tests on a fake LLM
```

## Run it

Needs [uv](https://docs.astral.sh/uv/), ffmpeg and a [Groq API key](https://console.groq.com/keys).

```bash
./run.sh            # first run creates .env; add GROQ_API_KEY, then run again
```

Open http://localhost:8000.

| Command | What it does |
|---|---|
| `./run.sh start / stop / restart / status / logs` | Manage the server |
| `./run.sh dev` | Run with auto-reload |
| `./run.sh share` | Public HTTPS link through a Cloudflare quick tunnel |
| `./run.sh test` | Run the tests |
| `./run.sh sim [persona]` | Simulate a full interview with a real LLM |

Configuration lives in `.env` (see `.env.example`): model chains per role, default interview length, Piper voice
and Whisper model.

## Principles

- Every rating is backed by a verified quote from the candidate.
- Same brief and rubric for every candidate of a role.
- Never scores accent, fluency (unless the role needs it) or protected attributes.
- The interviewer never says whether an answer is right and never helps the candidate answer.
- Consent and clear AI disclosure before the interview.

## Roadmap

See [TASKS.md](TASKS.md). Product spec: [docs/README.md](docs/README.md).
