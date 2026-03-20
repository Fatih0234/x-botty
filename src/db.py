import json
import sqlite3
from datetime import datetime, timezone
from contextlib import contextmanager

from config import ROOT_DIR
import os

DB_PATH = os.path.join(ROOT_DIR, "data", "twitter.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS tweets (
    url         TEXT PRIMARY KEY,
    username    TEXT NOT NULL,
    text        TEXT,
    posted_at   TEXT NOT NULL,
    first_seen_at TEXT NOT NULL,
    is_retweet  INTEGER DEFAULT 0,
    is_reply    INTEGER DEFAULT 0,
    is_quote_tweet INTEGER DEFAULT 0,
    is_pinned   INTEGER DEFAULT 0,
    quoted_tweet_url TEXT,
    hashtags    TEXT,
    mentions    TEXT,
    external_links TEXT,
    media_urls  TEXT
);

CREATE TABLE IF NOT EXISTS snapshots (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    tweet_url       TEXT NOT NULL,
    recorded_at     TEXT NOT NULL,
    views           INTEGER,
    likes           INTEGER,
    retweets        INTEGER,
    replies         INTEGER,
    engagement_score REAL,
    FOREIGN KEY (tweet_url) REFERENCES tweets(url)
);

CREATE INDEX IF NOT EXISTS idx_snapshots_tweet_url ON snapshots(tweet_url);
CREATE INDEX IF NOT EXISTS idx_tweets_username ON tweets(username);
CREATE INDEX IF NOT EXISTS idx_tweets_posted_at ON tweets(posted_at);
"""


@contextmanager
def get_conn():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with get_conn() as conn:
        conn.executescript(SCHEMA)


def upsert_tweet(tweet: dict):
    """Insert tweet if not seen before. Does not update existing rows."""
    with get_conn() as conn:
        conn.execute("""
            INSERT OR IGNORE INTO tweets
                (url, username, text, posted_at, first_seen_at,
                 is_retweet, is_reply, is_quote_tweet, is_pinned,
                 quoted_tweet_url, hashtags, mentions, external_links, media_urls)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            tweet["url"],
            tweet["username"],
            tweet.get("text", ""),
            tweet["posted_at"],
            datetime.now(timezone.utc).isoformat(),
            int(tweet.get("is_retweet", False)),
            int(tweet.get("is_reply", False)),
            int(tweet.get("is_quote_tweet", False)),
            int(tweet.get("is_pinned", False)),
            tweet.get("quoted_tweet_url"),
            json.dumps(tweet.get("hashtags") or []),
            json.dumps(tweet.get("mentions") or []),
            json.dumps(tweet.get("external_links") or []),
            json.dumps(tweet.get("media_urls") or []),
        ))


def add_snapshot(tweet: dict):
    """Record an engagement snapshot for a tweet."""
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO snapshots (tweet_url, recorded_at, views, likes, retweets, replies, engagement_score)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            tweet["url"],
            datetime.now(timezone.utc).isoformat(),
            tweet.get("views"),
            tweet.get("likes"),
            tweet.get("retweets"),
            tweet.get("replies"),
            tweet.get("engagement_score"),
        ))


def get_active_tweet_urls(max_age_days: int = 7) -> list[str]:
    """Return URLs of tweets still within the tracking window."""
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT url FROM tweets
            WHERE posted_at >= datetime('now', ?)
        """, (f"-{max_age_days} days",)).fetchall()
    return [row["url"] for row in rows]


def get_snapshots(tweet_url: str) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT * FROM snapshots WHERE tweet_url = ? ORDER BY recorded_at
        """, (tweet_url,)).fetchall()
    return [dict(row) for row in rows]


def get_recent_tweets(username: str, hours: int = 24) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT t.*, s.views, s.likes, s.retweets, s.replies, s.engagement_score, s.recorded_at AS snapshot_at
            FROM tweets t
            JOIN snapshots s ON s.tweet_url = t.url
            WHERE t.username = ?
              AND t.posted_at >= datetime('now', ?)
              AND s.id = (SELECT id FROM snapshots WHERE tweet_url = t.url ORDER BY recorded_at DESC LIMIT 1)
            ORDER BY s.engagement_score DESC
        """, (username, f"-{hours} hours")).fetchall()
    return [dict(row) for row in rows]


def get_breakouts(hours: int = 6, min_score_delta: float = 50.0) -> list[dict]:
    """
    Tweets where engagement_score grew significantly in the last N hours.
    Compares the latest snapshot to the one from ~N hours ago.
    """
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT
                t.url, t.username, t.text, t.posted_at,
                latest.engagement_score AS score_now,
                early.engagement_score  AS score_before,
                (latest.engagement_score - COALESCE(early.engagement_score, 0)) AS delta
            FROM tweets t
            JOIN snapshots latest ON latest.tweet_url = t.url
                AND latest.id = (SELECT id FROM snapshots WHERE tweet_url = t.url ORDER BY recorded_at DESC LIMIT 1)
            LEFT JOIN snapshots early ON early.tweet_url = t.url
                AND early.recorded_at <= datetime('now', ?)
                AND early.id = (SELECT id FROM snapshots WHERE tweet_url = t.url AND recorded_at <= datetime('now', ?) ORDER BY recorded_at DESC LIMIT 1)
            WHERE delta >= ?
            ORDER BY delta DESC
        """, (f"-{hours} hours", f"-{hours} hours", min_score_delta)).fetchall()
    return [dict(row) for row in rows]
