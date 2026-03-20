import os
import json
from dotenv import load_dotenv

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

load_dotenv(os.path.join(ROOT_DIR, ".env"))


def get_firefox_profile() -> str:
    with open(os.path.join(ROOT_DIR, "config.json"), "r") as f:
        return json.load(f).get("firefox_profile", "")


def get_headless() -> bool:
    if os.environ.get("HEADLESS", "").lower() in ("1", "true"):
        return True
    with open(os.path.join(ROOT_DIR, "config.json"), "r") as f:
        return json.load(f).get("headless", False)


def get_accounts() -> list[str]:
    with open(os.path.join(ROOT_DIR, "config.json"), "r") as f:
        return json.load(f).get("accounts", [])


def get_cookies() -> list[dict] | None:
    """
    Load Twitter session cookies for GitHub Actions (no Firefox profile available).
    Reads from TWITTER_COOKIES env var (JSON array) or cookies.json file.
    Returns None if neither is present — falls back to Firefox profile auth.
    """
    raw = os.environ.get("TWITTER_COOKIES")
    if raw:
        return json.loads(raw)
    cookies_path = os.path.join(ROOT_DIR, "cookies.json")
    if os.path.exists(cookies_path):
        with open(cookies_path) as f:
            return json.load(f)
    return None


def get_gemini_api_key() -> str:
    return os.environ.get("GEMINI_API_KEY", "")
