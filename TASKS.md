# Tryout - Tasks

Overview: [README.md](README.md). Spec: [docs/README.md](docs/README.md). Run: `./run.sh start | stop | restart | status | logs | dev | test | sim [persona]`.

## Done (v1)
- [x] Recruiter: create role from JD + notes, AI-designed brief and rubric, editable
- [x] Candidates: private interview links, resume-personalised openers, claims to verify
- [x] Voice / text interview: ack + one follow-up, time per section, probe limits, code-controlled section switching
- [x] Evaluator: per-criterion bars, verified quotes with timestamps, weighted score, resume flags, candidate feedback
- [x] Recruiter report, ranking, Advance / Hold / Reject, release feedback
- [x] Recruiter uploads one hiring document (PDF / DOCX / text); AI builds plan + rubric; plain-language refine; reset candidate
- [x] Candidate: resume upload, resume fit %, Whisper STT, Piper TTS, video-call room
- [x] Groq client with fallback chain and rate-limit retry; tests on a fake LLM; real-LLM simulator

## Next
- [ ] Proctoring (tab switches, face presence, second voice), shown on the report timeline
- [ ] Email invite sending, reminder
- [ ] Recruiter auth; candidate link expiry
- [ ] Integrity: paste detection, answer-timing signals
