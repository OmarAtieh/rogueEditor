# Repository Guidelines

## Project Structure & Modules
- `Source/`: App sources
  - `RogueEditor.py`: Legacy monolith (kept for compatibility)
  - `cli.py`: New modular CLI (auth + dump commands)
  - `rogueeditor/`: Package
    - `api.py`: HTTP client (auth, trainer, slots)
    - `config.py`: Endpoints, default headers
    - `token.py`: URL‑safe Base64 helpers
- `Compiled/`: Prebuilt Windows binary (`rogueEditor.zip` / `rogueEditor.exe`).
- `debug/`: Dev utilities (`tests/`, `logs/`, `docs/`).
- `README.md`: Usage and requirements.

## Key Design Patterns
- **Separation of concerns**: CLI and GUI share the same core API and editor modules
- **Per-user isolation**: All saves, sessions, and backups are username-scoped
- **Save-then-upload flow**: Local JSON files serve as the source of truth, with explicit upload steps
- **Catalog-driven UI**: Autocomplete and pickers backed by JSON catalogs built from game data
- **Non-blocking GUI**: Background tasks with progress indicators and error dialogs
- **Don't repeat yourself**: Every piece of knowledge must have a single, unambiguous, authoritative representation within a system

## Build, Test, and Development
- Run legacy: `python Source/RogueEditor.py`
- Run modular: `python Source/cli.py`
  - Non-interactive smoke: `python Source/cli.py --noninteractive` (requires `.env/env_data.txt`)
- Install deps: `pip install requests`
- Quick tests: `python debug/tests/test_auth.py`, `python debug/tests/test_with_credentials_fixed.py`
- Debug endpoints: `python debug/tests/test_all_endpoints.py`
- Use test creds: place credentials in `.env/env_data.txt` and choose option 2 when prompted (see `debug/docs/TEST_CREDENTIALS_FEATURE.md`).
 - Smoke validation: `python debug/tests/integration_smoke.py` or use CLI option `10` (safe no-op updates).

## Coding Style & Naming
- Python 3.10+, 4‑space indentation, UTF‑8.
- Follow PEP 8: `snake_case` for functions/variables, `CapWords` for classes.
- Module layout: prefer adding small modules under `Source/` (e.g., `api.py`, `models.py`) rather than growing `RogueEditor.py`.
- Keep side‑effects behind `if __name__ == "__main__":`.

## Testing Guidelines
- Framework: ad‑hoc scripts in `debug/tests/` (no pytest configured).
- Naming: `test_*.py` for scripts; keep each script runnable standalone via `python file.py`.
- Credentials: never hardcode; read from `.env/env_data.txt` when needed.
- Manual verification: run key flows after changes (login, dump/update trainer, dump/update slot).
- Integration: prefer `integration_smoke.py` or CLI option `10` to validate end-to-end.
 - CI-friendly: use `python Source/cli.py --noninteractive` to validate login and no-op updates.

## Commit & Pull Request
- Commits: short imperative subject (≤72 chars), scoped changes per commit: e.g., "api: add url‑safe token header".
- PRs: include summary, rationale, affected commands, and before/after output or logs from `debug/tests/`.
- Link related docs (e.g., `debug/docs/TOKEN_FIX_IMPLEMENTATION.md`). Attach screenshots only if UI behavior changes.

## Security & Configuration
- Secrets: never commit tokens or real credentials. Use `.env/` only for local data; ensure it stays untracked.
- Endpoints: current live endpoints under `api.pokerogue.net` (see README). For local servers, update constants in `Source/` and document changes in the PR.
