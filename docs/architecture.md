# Tryout - Architecture

## System overview

```mermaid
flowchart LR
    subgraph Browser
        R["Recruiter app<br/>recruiter.html / recruiter.js"]
        C["Candidate interview room<br/>interview.html / interview.js<br/>MediaRecorder + camera"]
    end

    subgraph Server["FastAPI server (backend/app.py)"]
        API["REST API<br/>/api/roles, /api/candidates<br/>/api/i/{token}/..."]
        LOCK["Per-candidate asyncio lock<br/>+ duplicate-answer guard"]
        ENG["Interview Engine<br/>state machine + policy<br/>(time, coverage, probe limits)"]
        subgraph Agents
            RC["Role Compiler"]
            CP["Candidate Prep"]
            TA["Turn Agent"]
            EV["Evaluator<br/>+ quote verification<br/>+ weighted score in code"]
        end
        LLM["LLM client<br/>per-role fallback chains<br/>429 wait-and-retry<br/>JSON repair"]
        VOICE["Voice<br/>FFmpeg -> FLAC<br/>Piper TTS (local)"]
        STORE[("JSON store<br/>data/roles, candidates,<br/>plans, sessions")]
    end

    subgraph Groq["Groq API"]
        STRONG["Strong chain<br/>gpt-oss-120b -> gpt-oss-20b"]
        FAST["Turn chain<br/>gpt-oss-20b -> qwen3"]
        WHISPER["Whisper large-v3"]
    end

    R --> API
    C --> API
    API --> LOCK --> ENG
    API --> RC & CP & EV
    ENG --> TA
    RC & CP & EV --> LLM
    TA --> LLM
    LLM --> STRONG
    LLM --> FAST
    API --> VOICE
    VOICE --> WHISPER
    API --> STORE
    ENG --> STORE
```

## Where the LLM is called

| Agent          | Model chain | How often                                    | Input -> output                                                 |
| -------------- | ----------- | -------------------------------------------- | --------------------------------------------------------------- |
| Role Compiler  | strong      | once per role (+ each plain-language refine) | Hiring document -> sections, slots, criteria                    |
| Candidate Prep | strong      | once per candidate                           | Resume + JD -> highlights, claims, openers, fit, STT vocabulary |
| Turn Agent     | turn        | once per candidate answer                    | Context + answer -> slot updates, ack, probe / bridge question  |
| Evaluator      | strong      | once per interview (background task)         | Transcript + rubric -> ratings, quotes, feedback                |
| Whisper        | STT         | once per spoken answer                       | Audio + vocabulary hint -> text                                 |

Everything else is plain code: section timing, when to move on, which question is spoken, quote verification,
the weighted score, and the resume-fit percentage.

## One interview turn

```mermaid
sequenceDiagram
    participant B as Candidate browser
    participant A as FastAPI
    participant W as Groq Whisper
    participant E as Engine
    participant T as Turn Agent (Groq)
    participant S as JSON store

    B->>A: POST /api/i/{token}/audio (webm / mp4)
    A->>A: FFmpeg -> 16 kHz mono FLAC
    A->>W: transcribe (prompt = role + resume vocabulary + last question)
    W-->>A: segments (silence-hallucinations dropped)
    A->>A: per-candidate lock
    A->>E: handle_user_turn(text)
    E->>E: dedupe, tick clock, PII regex flags
    E->>T: one JSON call (context + answer)
    T-->>E: slot updates, ack, probe / bridge question
    E->>E: policy decides: probe again or switch section
    E->>S: save session
    A-->>B: what to say + progress
    B->>A: GET /tts/{turn_id}
    A-->>B: Piper WAV (browser speech as fallback)
    Note over A: On the last turn the Evaluator runs as a background task
```

## Groq rate-limit handling

```mermaid
flowchart TD
    START["Agent calls llm.json(role=...)"] --> PICK["Take next model in the role's chain"]
    PICK --> CALL["POST /chat/completions<br/>JSON mode, low reasoning effort"]
    CALL --> R429{"HTTP 429?"}
    R429 -- "yes, wait <= 10s<br/>(retry-after header or<br/>'try again in Xs')" --> SLEEP["sleep wait + 0.2s<br/>retry same model (max 2)"] --> CALL
    R429 -- "no, or wait > 10s" --> R400{"HTTP 400 with<br/>reasoning param?"}
    R400 -- yes --> PLAIN["retry once without it"] --> ERR
    R400 -- no --> ERR{"Error?"}
    ERR -- yes --> MORE{"More models<br/>in chain?"}
    MORE -- yes --> PICK
    MORE -- no --> FAIL["LLMError"]
    ERR -- no --> PARSE{"Valid JSON?"}
    PARSE -- no --> REPAIR["one repair call on same model"] --> PARSE2{"Valid?"}
    PARSE2 -- no --> MORE
    PARSE2 -- yes --> OK
    PARSE -- yes --> OK["Return result + usage<br/>(tokens, latency logged)"]

    FAIL --> DEG["Graceful degradation"]
    DEG --> D1["Turn: interviewer says<br/>'could you say that once more?'<br/>interview continues"]
    DEG --> D2["Evaluation: transcript kept,<br/>recruiter can re-evaluate"]
    DEG --> D3["Recruiter actions: 503<br/>'AI service is busy, retry'"]
```

Whisper has its own retry: up to 3 attempts with 2s and 4s back-off on 429.
