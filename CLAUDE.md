# Tryout

AI voice screening interviewer, being rebuilt from a prototype into a product.

## Start here

- Plan and current phase: [TASKS.md](TASKS.md). Work through it in phase order and tick items off as they land.
- Why each task exists (finding IDs like `B1`, `D3`): [docs/backend-audit.md](docs/backend-audit.md).
- Code map (layers, routes, flows, where to find things): [docs/system-design.md](docs/system-design.md).
  Keep it in sync when files move.

## Decisions

- Backend first. Frontend changes only where needed to test a backend change by hand (`[UI]` tasks) until
  Phase 7 sign-off.
- Storage moves to managed cloud Postgres only. SQLAlchemy 2.0 async + Alembic. No repository layer; services
  query directly. Tests use in-memory SQLite through the same models.
- FastAPI stays the backend. Python is required for the agent, voice and document code.
- Agents: one folder each with spec, prompt, code tools and tests. The LLM proposes, code decides.
- Simple over clever: shortest code a new reader can follow; no structure added "for later".

## Commands

`./run.sh dev` (auto-reload), `./run.sh test`, `./run.sh sim [strong|vague|bluffer|injector]` (real LLM).

## Conventions

- Every fix or feature comes with a test on the fake LLM (`tests/`).
- Prompts live in `.md` files next to their agent; bump `prompt_version` when one changes.
- No em-dashes anywhere (code, docs, commits); use `-`.
- Naming follows each language's standard (decided 2026-10-22): Python snake_case for functions, variables, files
  and folders, PascalCase for classes; camelCase in frontend JS. JSON, API and database fields stay snake_case.
