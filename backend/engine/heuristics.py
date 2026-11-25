"""Text heuristics for the interviewer's lines: no repeated questions, no repeated filler openers, no verdicts."""

import re

from ..models import Session

_STOP = {
    "what",
    "did",
    "you",
    "your",
    "the",
    "and",
    "for",
    "how",
    "can",
    "could",
    "tell",
    "about",
    "that",
    "this",
    "with",
    "was",
    "were",
    "are",
    "have",
    "has",
    "there",
    "any",
    "one",
    "use",
    "used",
    "using",
    "would",
    "some",
}


def _words(text: str) -> set[str]:
    return {
        w for w in "".join(c.lower() if c.isalnum() else " " for c in text).split() if len(w) > 2 and w not in _STOP
    }


def similar(a: str, b: str) -> bool:
    wa, wb = _words(a), _words(b)
    return bool(wa and wb) and len(wa & wb) / len(wa | wb) >= 0.5


def recent_agent(session: Session, n: int = 3) -> list[str]:
    return [t.text for t in session.turns if t.role == "agent"][-n:]


_FILLERS = {"got it", "okay", "ok", "right", "nice", "sure", "alright", "great", "cool", "i see", "makes sense"}


def fresh_ack(ack: str, session: Session) -> str:
    """Keep the acknowledgment, but trim an opener word ("Got it,") that the last turns already used, so it doesn't
    sound repetitive. Only a bare repeated filler is dropped entirely."""
    recent = [t.lower() for t in recent_agent(session, 2)]
    words = ack.split()
    for n in (2, 1):
        opener = " ".join(words[:n]).lower().strip(" .!,")
        if opener in _FILLERS and any(t.startswith(opener) for t in recent):
            rest = " ".join(words[n:]).lstrip(" ,.!-")
            return rest[:1].upper() + rest[1:] if len(rest.split()) >= 3 else ""
    return ack


# The interviewer never tells the candidate whether an answer was right (docs/requirements.md O4). These are the
# ways a model slips into a verdict; an acknowledgment that contains one is replaced with a neutral one.
_VERDICT = re.compile(
    r"\b(that'?s|that is|you'?re|you are|exactly|absolutely|totally) (correct|right|wrong|incorrect)\b"
    r"|\b(correct|right|wrong|great|perfect|excellent) answer\b|\bthe (right|correct) answer is\b"
    r"|\byou (should|could) (say|answer|mention)\b",
    re.I,
)
NEUTRAL_ACK = "Thanks for explaining."


def judges_answer(text: str) -> bool:
    return bool(_VERDICT.search(text))
