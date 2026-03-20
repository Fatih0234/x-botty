import os
import json
from datetime import datetime, timezone

from config import ROOT_DIR
import db
from virality import rank_by_viral_score

# Weights reflect amplification value: retweet > reply > like
RETWEET_WEIGHT = 5
REPLY_WEIGHT = 3
LIKE_WEIGHT = 1


def engagement_score(tweet: dict) -> float:
    """
    Weighted engagement score.
    If views are available, returns a rate (score / views).
    Otherwise returns the raw weighted sum.
    """
    replies = tweet.get("replies") or 0
    retweets = tweet.get("retweets") or 0
    likes = tweet.get("likes") or 0
    views = tweet.get("views")

    score = (replies * REPLY_WEIGHT) + (retweets * RETWEET_WEIGHT) + (likes * LIKE_WEIGHT)

    if views and views > 0:
        return round(score / views, 6)
    return float(score)


def save_report(data: dict) -> str:
    reports_dir = os.path.join(ROOT_DIR, "reports")
    os.makedirs(reports_dir, exist_ok=True)

    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    path = os.path.join(reports_dir, f"{date_str}.json")

    # Attach engagement score to every tweet, find top tweet per account
    enriched = {}
    for account, tweets in data.items():
        scored = []
        for tweet in tweets:
            t = dict(tweet)
            t["engagement_score"] = engagement_score(t)
            scored.append(t)

        scored.sort(key=lambda t: t["engagement_score"], reverse=True)

        enriched[account] = {
            "tweet_count": len(scored),
            "top_tweet": scored[0]["url"] if scored else None,
            "tweets": scored,
        }

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "accounts": enriched,
    }

    with open(path, "w") as f:
        json.dump(payload, f, indent=2)

    return path, payload


def generate_viral_ranking(now: datetime | None = None) -> str:
    if now is None:
        now = datetime.now(timezone.utc)

    tweets = db.get_candidate_tweets(max_age_hours=72)
    tweets_with_snapshots = [(t, db.get_snapshots(t["url"])) for t in tweets]
    ranked = rank_by_viral_score(tweets_with_snapshots, now)

    reports_dir = os.path.join(ROOT_DIR, "reports")
    os.makedirs(reports_dir, exist_ok=True)
    date_str = now.strftime("%Y-%m-%d")
    path = os.path.join(reports_dir, f"{date_str}_viral.json")

    payload = {
        "generated_at": now.isoformat(),
        "count": len(ranked),
        "tweets": ranked,
    }
    with open(path, "w") as f:
        json.dump(payload, f, indent=2)

    return path
