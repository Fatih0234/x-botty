import sys
import os
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import get_accounts, get_firefox_profile, get_headless, get_cookies
from scraper import TwitterScraper
from report import engagement_score
import db


def main():
    accounts = get_accounts()
    if not accounts:
        print("No accounts configured. Add them to config.json under 'accounts'.")
        sys.exit(1)

    db.init_db()

    lookback_hours_map = {
        account: 24 * 7 if not db.account_has_tweets(account) else 72
        for account in accounts
    }

    print(f"Scraping {len(accounts)} account(s): {', '.join('@' + a for a in accounts)}")

    scraper = TwitterScraper(
        firefox_profile=get_firefox_profile(),
        headless=get_headless(),
        cookies=get_cookies(),
    )

    try:
        results = scraper.scrape_all(accounts, lookback_hours_map)
    finally:
        scraper.close()

    # Fetch known URLs once to avoid per-tweet DB queries
    known_urls = set(db.get_active_tweet_urls(max_age_days=30))

    cutoff_3d = datetime.now(timezone.utc) - timedelta(days=3)
    new_total = 0
    for account, tweets in results.items():
        new_for_account = 0
        for tweet in tweets:
            tweet["engagement_score"] = engagement_score(tweet)
            is_new = tweet["url"] not in known_urls
            db.upsert_tweet(tweet)
            if datetime.fromisoformat(tweet["posted_at"]) >= cutoff_3d:
                db.add_snapshot(tweet)
            if is_new:
                new_for_account += 1
                known_urls.add(tweet["url"])
        new_total += new_for_account
        print(f"  @{account}: {len(tweets)} tweet(s) scraped, {new_for_account} new")

    active_urls = db.get_active_tweet_urls(max_age_days=7)
    scraped_urls = {t["url"] for tweets in results.values() for t in tweets}
    stale_count = len(set(active_urls) - scraped_urls)
    if stale_count:
        print(f"  {stale_count} older tracked tweet(s) not re-scraped this run")

    print(f"\n{new_total} new tweet(s) added to DB.")

    breakouts = db.get_breakouts(hours=6, min_score_delta=50.0)
    if breakouts:
        print(f"\nBreakout tweets (last 6h):")
        for b in breakouts[:5]:
            print(f"  +{b['delta']:.0f}  @{b['username']}: {b['url']}")


if __name__ == "__main__":
    main()
