import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

DATA_DIR = Path(os.getenv("DATA_DIR", ROOT / "data"))
PROMPTS_DIR = ROOT / "backend" / "prompts"
FRONTEND_DIR = ROOT / "frontend"

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_BASE_URL = os.getenv("GROQ_BASE_URL", "https://api.groq.com/openai/v1")
TIME_BUDGET_SEC = int(os.getenv("TIME_BUDGET_SEC", "480"))


def _chain(name: str, default: str) -> list[str]:
    return [m.strip() for m in os.getenv(name, default).split(",") if m.strip()]


# Role -> fallback chain of models. Agents pick a role, never a model.
MODELS = {
    "turn": _chain("MODEL_TURN", "openai/gpt-oss-20b,qwen/qwen3.8-27b"),
    "strong": _chain("MODEL_STRONG", "openai/gpt-oss-120b,openai/gpt-oss-20b"),
    "aux": _chain("MODEL_AUX", "qwen/qwen3.8-27b,openai/gpt-oss-20b"),
}

PIPER_MODEL = os.getenv("PIPER_MODEL", "")
STT_MODEL = os.getenv("STT_MODEL", "whisper-large-v3")
