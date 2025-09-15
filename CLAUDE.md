# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is rogueEditor, a Pokérogue save editor for trainers and run data with both CLI and GUI modes. It's a Python application that interfaces with the Pokérogue API to edit trainer data, Pokémon teams, starters, and run modifiers.

## Development Commands

### Running the Application
- **CLI mode (default)**: `python Source/cli.py`
- **GUI mode**: `python Source/cli.py --gui`
- **Non-interactive smoke test**: `python Source/cli.py --noninteractive` (requires `.env/env_data.txt`)
- **Legacy entrypoint**: `python Source/RogueEditor.py` (delegates to CLI)

### Dependencies
- **Install**: `pip install requests` (only external dependency)
- **Requirements**: Python 3.10+

### Testing and Development
- **Quick auth test**: `python debug/tests/test_auth.py`
- **Credentials test**: `python debug/tests/test_with_credentials_fixed.py`
- **All endpoints test**: `python debug/tests/test_all_endpoints.py`
- **Integration smoke test**: `python debug/tests/integration_smoke.py`
- **Build catalogs**: Use CLI menu option 20 or run catalog builder from CLI Tools menu

### Common Development Tasks
- **Build data catalogs**: CLI → Tools → Build catalogs from tmpServerFiles (option 20)
- **Clean dev artifacts**: CLI → Tools → Clean dev artifacts (removes debug/, tmpServerFiles/, env data)
- **Test credentials setup**: Place credentials in `.env/env_data.txt`, use CLI option 2

## Architecture Overview

### Core Modules (`Source/rogueeditor/`)
- **`api.py`**: HTTP client for Pokérogue API with authentication, retry logic, and endpoint management
- **`config.py`**: Base URLs, endpoint paths, default headers, and environment overrides
- **`editor.py`**: High-level operations for data manipulation (dumps, updates, team editing, modifiers)
- **`catalog.py`**: JSON catalog loaders and TS enum parser for game data
- **`utils.py`**: Path helpers, environment management, user session storage, JSON I/O utilities
- **`token.py`**: Base64 token conversion helpers for API authentication

### GUI Architecture (`Source/gui/`)
- **`gui.py`**: Main Tkinter application with non-blocking UI and background task handling
- **`gui/sections/`**: Modular UI sections (login, data_io, slots, team)
- **`gui/dialogs/`**: Dialog windows (team_editor, item_manager)
- **`gui/common/`**: Shared widgets and catalog selection components

### Data Management
- **User saves**: `Source/saves/<username>/` (trainer.json, slot N.json)
- **Catalogs**: `Source/data/` (moves.json, abilities.json, pokemon_catalog.json, etc.)
- **Environment**: `.env/env_data.txt` for test credentials, `.env/users.json` for session tracking
- **Backups**: Timestamped backups with restore dialog support

### API Integration
- **Authentication**: Form-encoded login with fallback to JSON, standard Base64 authorization headers
- **Session management**: clientSessionId per user with automatic generation and persistence
- **Endpoints**: System endpoints (`/savedata/system/`) for trainer data, session endpoints (`/savedata/session/`) for slot data
- **Error handling**: Retry logic with backoff for 429/5xx, clear error messages for auth failures

### Key Design Patterns
- **Separation of concerns**: CLI and GUI share the same core API and editor modules
- **Per-user isolation**: All saves, sessions, and backups are username-scoped
- **Save-then-upload flow**: Local JSON files serve as the source of truth, with explicit upload steps
- **Catalog-driven UI**: Autocomplete and pickers backed by JSON catalogs built from game data
- **Non-blocking GUI**: Background tasks with progress indicators and error dialogs
- **Don't repeat yourself**: Every piece of knowledge must have a single, unambiguous, authoritative representation within a system

## Development Guidelines

### Code Style
- Python 3.10+, 4-space indentation, UTF-8
- Follow PEP 8: `snake_case` for functions/variables, `CapWords` for classes
- Keep side effects behind `if __name__ == "__main__":`

### Testing Approach
- Ad-hoc scripts in `debug/tests/` (no pytest configured), coverage is spotty
- Each test script runnable standalone via `python file.py`
- Never hardcode credentials; read from `.env/env_data.txt`
- Use `integration_smoke.py` or CLI option 10 for end-to-end validation
- To be standarized later into formal pytests

### Security Notes
- Never commit tokens or credentials
- Use `.env/` only for local data (stays untracked)
- API endpoints default to `api.pokerogue.net` (see config.py for overrides)

## Important File Locations

### Configuration Files
- `.env/env_data.txt`: Test credentials and default clientSessionId
- `.env/users.json`: Per-username session tracking
- `Source/data/`: Game data catalogs (moves, abilities, Pokémon, etc.)

### Entry Points
- `Source/cli.py`: Main modular CLI
- `Source/gui.py`: Tkinter GUI application
- `Source/RogueEditor.py`: Legacy compatibility wrapper

### Development Utilities
- `debug/tests/`: Test scripts and endpoint validation
- `debug/docs/`: Development documentation and guides
- `tools/`: PowerShell and shell scripts for git operations

### Development Tracking and Feature Docs
- `Source/TrackingAndDocs/`: Teflects project structure and isolates docs from code, maintain docs and mirror project directory structure where relevant under this directory