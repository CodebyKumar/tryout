"""JSON file persistence. One file per object; written after every change so a refresh can resume."""

import json
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel

from . import config
from .models import Candidate, InterviewPlan, Role, Session

T = TypeVar("T", bound=BaseModel)

_KINDS = {Role: ("roles", "role_id"), Candidate: ("candidates", "candidate_id"),
          InterviewPlan: ("plans", "plan_id"), Session: ("sessions", "session_id")}


def _path(kind: str, obj_id: str) -> Path:
    if not obj_id.replace("_", "").isalnum():
        raise ValueError("bad id")
    d = config.DATA_DIR / kind
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{obj_id}.json"


def save(obj: BaseModel) -> None:
    kind, key = _KINDS[type(obj)]
    path = _path(kind, getattr(obj, key))
    tmp = path.with_suffix(".tmp")
    tmp.write_text(obj.model_dump_json(indent=1))
    tmp.replace(path)


def load(cls: type[T], obj_id: str) -> T | None:
    kind, _ = _KINDS[cls]
    path = _path(kind, obj_id)
    if not path.exists():
        return None
    return cls.model_validate_json(path.read_text())


def delete(cls: type[T], obj_id: str) -> None:
    kind, _ = _KINDS[cls]
    _path(kind, obj_id).unlink(missing_ok=True)


def load_all(cls: type[T]) -> list[T]:
    kind, _ = _KINDS[cls]
    d = config.DATA_DIR / kind
    return [cls.model_validate_json(p.read_text()) for p in sorted(d.glob("*.json"))] if d.exists() else []


def read_json(name: str, default):
    path = config.DATA_DIR / name
    if not path.exists():
        return default
    return json.loads(path.read_text())


def write_json(name: str, data) -> None:
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    path = config.DATA_DIR / name
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1, default=str))
    tmp.replace(path)
