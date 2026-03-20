import os
import re
import time
from datetime import datetime, timezone, timedelta

from selenium import webdriver
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import StaleElementReferenceException
from webdriver_manager.firefox import GeckoDriverManager
from selenium.webdriver.firefox.service import Service

# How long to wait after each scroll for new content to load
SCROLL_PAUSE = 3
# How many consecutive scrolls with no new tweets before giving up
MAX_EMPTY_SCROLLS = 4
# Max retries when a stale element is encountered
STALE_RETRIES = 3


class TwitterScraper:
    def __init__(self, firefox_profile: str = "", headless: bool = False, cookies: list[dict] | None = None):
        options = Options()
        if headless:
            options.add_argument("--headless")
        if firefox_profile and os.path.exists(firefox_profile):
            options.profile = firefox_profile

        service = Service(GeckoDriverManager().install())
        self.browser = webdriver.Firefox(service=service, options=options)
        self.wait = WebDriverWait(self.browser, 30)

        if cookies:
            self._inject_cookies(cookies)

    def _inject_cookies(self, cookies: list[dict]):
        """Inject session cookies so the browser is logged in without a profile."""
        self.browser.get("https://x.com")
        time.sleep(2)
        for cookie in cookies:
            try:
                self.browser.add_cookie(cookie)
            except Exception:
                pass
        self.browser.refresh()
        time.sleep(2)

    def scrape(self, username: str, lookback_hours: int = 72) -> list[dict]:
        self.browser.get(f"https://x.com/{username}")

        # Wait for first tweet batch then give it a moment to fully render
        self.wait.until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "article[data-testid='tweet']"))
        )
        time.sleep(2)

        cutoff = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)
        tweets: list[dict] = []
        seen_urls: set[str] = set()
        empty_scroll_count = 0
        reached_cutoff = False

        while not reached_cutoff:
            prev_count = len(seen_urls)

            for attempt in range(STALE_RETRIES):
                try:
                    articles = self.browser.find_elements(
                        By.CSS_SELECTOR, "article[data-testid='tweet']"
                    )
                    for article in articles:
                        tweet = _parse_article(article, username)
                        if tweet is None:
                            continue
                        if tweet["url"] in seen_urls:
                            continue

                        if datetime.fromisoformat(tweet["posted_at"]) < cutoff:
                            reached_cutoff = True
                            continue

                        seen_urls.add(tweet["url"])
                        tweets.append(tweet)
                    break  # parsed successfully
                except StaleElementReferenceException:
                    if attempt == STALE_RETRIES - 1:
                        raise
                    time.sleep(1)

            new_count = len(seen_urls)
            if new_count == prev_count:
                empty_scroll_count += 1
                print(f"    No new tweets found (attempt {empty_scroll_count}/{MAX_EMPTY_SCROLLS})")
                if empty_scroll_count >= MAX_EMPTY_SCROLLS:
                    print("    Reached max empty scrolls — stopping.")
                    break
            else:
                empty_scroll_count = 0

            if reached_cutoff:
                break

            # Scroll and wait for new content
            prev_article_count = len(
                self.browser.find_elements(By.CSS_SELECTOR, "article[data-testid='tweet']")
            )
            self.browser.execute_script("window.scrollTo(0, document.body.scrollHeight);")

            # Wait up to SCROLL_PAUSE seconds for article count to grow
            deadline = time.time() + SCROLL_PAUSE
            while time.time() < deadline:
                time.sleep(0.5)
                current_count = len(
                    self.browser.find_elements(By.CSS_SELECTOR, "article[data-testid='tweet']")
                )
                if current_count > prev_article_count:
                    break

        # Belt-and-suspenders filter
        return [t for t in tweets if datetime.fromisoformat(t["posted_at"]) >= cutoff]

    def scrape_all(self, accounts: list[str], lookback_hours_map: dict[str, int] | None = None) -> dict[str, list[dict]]:
        results = {}
        for account in accounts:
            hours = (lookback_hours_map or {}).get(account, 72)
            print(f"  Scraping @{account} (lookback={hours}h)...")
            try:
                results[account] = self.scrape(account, lookback_hours=hours)
                print(f"  @{account}: found {len(results[account])} tweet(s)")
            except Exception as e:
                print(f"  Error scraping @{account}: {e}")
                results[account] = []
        return results

    def close(self):
        self.browser.quit()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_article(article, username: str) -> dict | None:
    """Parse a tweet article element. Returns None if essential data is missing."""
    try:
        # URL — required
        url_els = article.find_elements(By.CSS_SELECTOR, "a[href*='/status/']")
        if not url_els:
            return None
        raw_href = url_els[0].get_attribute("href") or ""
        # Normalise to https://x.com/... regardless of redirect domain
        match = re.search(r"/([\w]+/status/\d+)", raw_href)
        if not match:
            return None
        url = f"https://x.com/{match.group(1)}"

        # Timestamp — required
        time_els = article.find_elements(By.CSS_SELECTOR, "time")
        if not time_els:
            return None
        dt_str = time_els[0].get_attribute("datetime")
        posted_at = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))

        # Retweet detection — socialContext contains "{someone} reposted"
        social_els = article.find_elements(By.CSS_SELECTOR, "[data-testid='socialContext']")
        is_retweet = bool(social_els and "repost" in social_els[0].text.lower())

        # Reply / quote tweet detection
        is_reply = bool(article.find_elements(By.CSS_SELECTOR, "div[data-testid='reply'] ~ div[data-testid='tweet'] time, [data-testid='tweetText'] ~ [role='link'] time"))
        # Simpler: check if there's a "Replying to" label above the text
        replying_els = article.find_elements(By.XPATH, ".//*[contains(text(), 'Replying to')]")
        is_reply = bool(replying_els)

        # Quote tweet: has an inner quoted-tweet block
        quote_els = article.find_elements(By.CSS_SELECTOR, "div[role='blockquote'], div[data-testid='quoteTweet']")
        is_quote_tweet = bool(quote_els)
        quoted_tweet_url = None
        quoted_tweet_author = None
        quoted_tweet_text = None
        if is_quote_tweet:
            q_block = quote_els[0]
            q_url_els = q_block.find_elements(By.CSS_SELECTOR, "a[href*='/status/']")
            if q_url_els:
                q_href = q_url_els[0].get_attribute("href") or ""
                q_match = re.search(r"/([\w]+/status/\d+)", q_href)
                quoted_tweet_url = f"https://x.com/{q_match.group(1)}" if q_match else None
            q_text_els = q_block.find_elements(By.CSS_SELECTOR, "div[data-testid='tweetText']")
            quoted_tweet_text = q_text_els[0].text if q_text_els else None
            # Author: look for a span with the @username pattern inside the quoted block
            q_author_els = q_block.find_elements(By.CSS_SELECTOR, "span")
            for span in q_author_els:
                t = span.text.strip()
                if t.startswith("@"):
                    quoted_tweet_author = t.lstrip("@")
                    break

        # Pinned tweet
        is_pinned = bool(article.find_elements(By.XPATH, ".//*[contains(text(), 'Pinned')]"))

        # Tweet text
        text_els = article.find_elements(By.CSS_SELECTOR, "div[data-testid='tweetText']")
        text = text_els[0].text if text_els else ""

        # Hashtags and mentions from links inside the tweet text
        hashtags = []
        mentions = []
        if text_els:
            for a in text_els[0].find_elements(By.CSS_SELECTOR, "a"):
                href = a.get_attribute("href") or ""
                if "/hashtag/" in href:
                    tag = a.text.lstrip("#")
                    if tag:
                        hashtags.append(tag)
                elif href.startswith("https://x.com/") and "/status/" not in href:
                    mention = a.text.lstrip("@")
                    if mention:
                        mentions.append(mention)

        # External links (t.co hrefs that aren't media or twitter-internal)
        external_links = []
        for a in article.find_elements(By.CSS_SELECTOR, "a[href]"):
            href = a.get_attribute("href") or ""
            if href.startswith("https://t.co/") or (
                href.startswith("http") and "x.com" not in href and "twitter.com" not in href
            ):
                if href not in external_links:
                    external_links.append(href)

        # Media URLs (images and videos — URLs only, no binary)
        media_urls = []
        for img in article.find_elements(By.CSS_SELECTOR, "img[src*='pbs.twimg.com/media']"):
            src = img.get_attribute("src")
            if src and src not in media_urls:
                media_urls.append(src)
        for video in article.find_elements(By.CSS_SELECTOR, "video[poster]"):
            poster = video.get_attribute("poster")
            if poster and poster not in media_urls:
                media_urls.append(poster)

        # Stats — parsed from the action group's aria-label (most reliable)
        stats = _parse_stats_from_group(article)

        return {
            "username": username,
            "text": text,
            "posted_at": posted_at.isoformat(),
            "url": url,
            "is_retweet": is_retweet,
            "is_reply": is_reply,
            "is_quote_tweet": is_quote_tweet,
            "is_pinned": is_pinned,
            "quoted_tweet_url": quoted_tweet_url,
            "quoted_tweet_author": quoted_tweet_author,
            "quoted_tweet_text": quoted_tweet_text,
            "hashtags": hashtags,
            "mentions": mentions,
            "external_links": external_links,
            "media_urls": media_urls,
            "replies": stats.get("replies"),
            "retweets": stats.get("retweets"),
            "likes": stats.get("likes"),
            "views": stats.get("views"),
        }
    except Exception:
        return None


def _parse_stats_from_group(article) -> dict:
    """
    X's action bar has a div[role='group'] with aria-label like:
      "47 replies, 23 reposts, 156 likes, 12 bookmarks, 89.3K views"
    Parsing this is far more reliable than hunting individual spans.
    Falls back to per-button span scraping if not found.
    """
    groups = article.find_elements(By.CSS_SELECTOR, "div[role='group'][aria-label]")
    for group in groups:
        label = group.get_attribute("aria-label") or ""
        if any(k in label for k in ("repl", "repost", "like", "view")):
            return _parse_aria_label(label)

    # Fallback: individual testid spans
    return {
        "replies": _get_stat_span(article, "reply"),
        "retweets": _get_stat_span(article, "retweet"),
        "likes": _get_stat_span(article, "like"),
        "views": None,
    }


_STAT_PATTERNS = {
    "replies": re.compile(r"(\d[\d,.KMkm]*)\s+repl", re.I),
    "retweets": re.compile(r"(\d[\d,.KMkm]*)\s+repost", re.I),
    "likes": re.compile(r"(\d[\d,.KMkm]*)\s+like", re.I),
    "views": re.compile(r"(\d[\d,.KMkm]*)\s+view", re.I),
}


def _parse_aria_label(label: str) -> dict:
    result = {}
    for key, pattern in _STAT_PATTERNS.items():
        m = pattern.search(label)
        result[key] = _parse_count(m.group(1)) if m else None
    return result


def _parse_count(text: str) -> int | None:
    """Convert '1.2K', '3M', '456' etc. to int."""
    if not text:
        return None
    text = text.strip().replace(",", "")
    try:
        if text[-1].upper() == "K":
            return int(float(text[:-1]) * 1_000)
        if text[-1].upper() == "M":
            return int(float(text[:-1]) * 1_000_000)
        return int(text)
    except (ValueError, IndexError):
        return None


def _get_stat_span(article, testid: str) -> int | None:
    try:
        els = article.find_elements(By.CSS_SELECTOR, f"div[data-testid='{testid}'] span")
        for el in els:
            text = el.text.strip()
            if text:
                return _parse_count(text)
    except Exception:
        pass
    return None
