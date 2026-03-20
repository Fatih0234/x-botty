"""
Run this locally while logged into Twitter in your Firefox profile.
It exports your session cookies to cookies.json.

Then store the contents of cookies.json as a GitHub Actions secret
named TWITTER_COOKIES.

Usage:
    uv run python src/export_cookies.py
"""
import sys
import os
import json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import get_firefox_profile, ROOT_DIR
from scraper import TwitterScraper

scraper = TwitterScraper(firefox_profile=get_firefox_profile(), headless=False)
scraper.browser.get("https://x.com")

input("Make sure you are logged into X/Twitter, then press Enter...")

cookies = scraper.browser.get_cookies()
scraper.close()

out_path = os.path.join(ROOT_DIR, "cookies.json")
with open(out_path, "w") as f:
    json.dump(cookies, f, indent=2)

print(f"Saved {len(cookies)} cookies to {out_path}")
print("Store the contents of this file as the TWITTER_COOKIES GitHub Actions secret.")
print("Do NOT commit cookies.json — it is in .gitignore.")
