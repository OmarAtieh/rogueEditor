import os

BASE_URL = os.getenv("ROGUEEDITOR_BASE_URL", "https://api.pokerogue.net")

# Endpoints
LOGIN_URL = os.getenv("ROGUEEDITOR_LOGIN_URL", f"{BASE_URL}/account/login")
TRAINER_DATA_URL = os.getenv("ROGUEEDITOR_TRAINER_URL", f"{BASE_URL}/account/info")
GAMESAVE_SLOT_URL = os.getenv("ROGUEEDITOR_SLOT_URL", f"{BASE_URL}/account/info/slot")

# Candidate paths for slot fetch/update (helps during live API drift)
SLOT_FETCH_PATHS = [
    os.getenv("ROGUEEDITOR_SLOT_PATH", "/account/info/slot/{i}"),
    "/savedata/session/get?slot={i}&clientSessionId={csid}",
    "/gamesave/data/{i}",
    "/save/data/{i}",
    "/account/slot/{i}",
]

SLOT_UPDATE_PATHS = [
    os.getenv("ROGUEEDITOR_SLOT_UPDATE_PATH", "/account/info/slot/{i}"),
    "/savedata/session/update?slot={i}&clientSessionId={csid}",
    "/savedata/session/set?slot={i}&clientSessionId={csid}",
    "/gamesave/update/{i}",
    "/save/update/{i}",
]

# Optional client session id (from browser network, or login response if present)
CLIENT_SESSION_ID = os.getenv("ROGUEEDITOR_CLIENT_SESSION_ID")

# Default headers that mimic browser requests
DEFAULT_HEADERS = {
    "accept": "application/json, text/plain, */*",
    "content-type": "application/x-www-form-urlencoded",
    "sec-ch-ua": '"Google Chrome";v="139", "Chromium";v="139", "Not;A=Brand";v="99"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "origin": "https://pokerogue.net",
    "referer": "https://pokerogue.net/",
    "user-agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/139.0.0.0 Safari/537.36"
    ),
}
