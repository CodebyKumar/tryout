import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

DATABASE_URL = os.getenv("DATABASE_URL", "")

# Original uploaded files (Supabase Storage). Optional: without a key only the extracted text is kept.
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_SECRET_KEY = os.getenv("SUPABASE_SECRET_KEY", "")
STORAGE_BUCKET = os.getenv("STORAGE_BUCKET", "documents")
FRONTEND_DIR = ROOT / "frontend"

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_BASE_URL = os.getenv("GROQ_BASE_URL", "https://api.groq.com/openai/v1")
TIME_BUDGET_SEC = int(os.getenv("TIME_BUDGET_SEC", "480"))

# Interview rules. Code enforces them whatever the Turn Agent proposes.
MAX_PROBES_PER_SLOT = int(os.getenv("MAX_PROBES_PER_SLOT", "2"))  # follow-ups on one piece of evidence
MAX_PROBES_PER_SECTION = int(os.getenv("MAX_PROBES_PER_SECTION", "3"))  # then move on, answered or not
WRAPUP_RESERVE_SEC = int(os.getenv("WRAPUP_RESERVE_SEC", "45"))  # kept free for "anything else?" and goodbye

# Upload caps
MAX_DOC_MB = int(os.getenv("MAX_DOC_MB", "5"))
MAX_AUDIO_MB = int(os.getenv("MAX_AUDIO_MB", "10"))  # about 3 minutes of browser audio; longer is cut to 3 min


def _chain(name: str, default: str) -> list[str]:
    return [m.strip() for m in os.getenv(name, default).split(",") if m.strip()]


# Role -> fallback chain of models. Agents pick a role, never a model.
MODELS = {
    "turn": _chain("MODEL_TURN", "openai/gpt-oss-20b,qwen/qwen3.8-27b"),
    "strong": _chain("MODEL_STRONG", "openai/gpt-oss-120b,openai/gpt-oss-20b"),
    "aux": _chain("MODEL_AUX", "qwen/qwen3.8-27b,openai/gpt-oss-20b"),
}

STT_MODEL = os.getenv("STT_MODEL", "whisper-large-v3")
# Interviewer voice (Deepgram Aura, free credit). Without a key the room uses the browser's own speech.
DEEPGRAM_API_KEY = os.getenv("DEEPGRAM_API_KEY", "")
DEEPGRAM_VOICE = os.getenv("DEEPGRAM_VOICE", "aura-2-thalia-en")

# Accounts. The account that signs up with ADMIN_EMAIL is the admin and is active at once; others wait for approval.
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "").strip().lower()
SESSION_DAYS = int(os.getenv("SESSION_DAYS", "14"))  # how long a login lasts
LINK_DAYS = int(os.getenv("LINK_DAYS", "14"))  # how long a candidate link works when no window is set

# Capacity. The free LLM tier, not the server, limits how many interviews can run well at once.
MAX_LIVE_INTERVIEWS = int(os.getenv("MAX_LIVE_INTERVIEWS", "4"))
IDLE_MINUTES = int(os.getenv("IDLE_MINUTES", "10"))  # an interview with no answer for this long is ended
