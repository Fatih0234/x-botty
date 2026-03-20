from math import log1p, exp
from datetime import datetime, timezone


def _parse_dt(s: str) -> datetime:
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def weighted_engagement(tweet: dict) -> float:
    return (
        (tweet.get("likes") or 0)
        + 3 * (tweet.get("replies") or 0)
        + 5 * (tweet.get("retweets") or 0)
    )


def quality(tweet: dict) -> float:
    return weighted_engagement(tweet) / max(tweet.get("views") or 0, 1)


def reach(tweet: dict) -> float:
    return log1p(tweet.get("views") or 0)


def freshness(tweet: dict, now: datetime) -> float:
    age_hours = (now - _parse_dt(tweet["posted_at"])).total_seconds() / 3600
    return exp(-age_hours / 36)


def _momentum_window(snapshots: list[dict], max_hours: float) -> tuple[dict, dict] | None:
    """Return (oldest, newest) snapshot pair within max_hours of the newest, or None."""
    if len(snapshots) < 2:
        return None
    newest = snapshots[-1]
    newest_dt = _parse_dt(newest["recorded_at"])
    cutoff_dt_str = None
    oldest_in_window = None
    for snap in snapshots[:-1]:
        snap_dt = _parse_dt(snap["recorded_at"])
        delta_h = (newest_dt - snap_dt).total_seconds() / 3600
        if delta_h <= max_hours:
            oldest_in_window = snap
            break
    if oldest_in_window is None:
        return None
    return oldest_in_window, newest


def view_momentum(snapshots: list[dict]) -> float:
    """Views per hour over the most recent ≤6h window, falling back to ≤24h."""
    for max_hours in (6, 24):
        pair = _momentum_window(snapshots, max_hours)
        if pair:
            old, new = pair
            delta_views = (new.get("views") or 0) - (old.get("views") or 0)
            old_dt = _parse_dt(old["recorded_at"])
            new_dt = _parse_dt(new["recorded_at"])
            delta_hours = (new_dt - old_dt).total_seconds() / 3600
            return max(delta_views, 0) / max(delta_hours, 1e-6)
    return 0.0


def engagement_momentum(snapshots: list[dict]) -> float:
    """Weighted-engagement per hour over recent window."""
    for max_hours in (6, 24):
        pair = _momentum_window(snapshots, max_hours)
        if pair:
            old, new = pair
            old_we = (old.get("likes") or 0) + 3 * (old.get("replies") or 0) + 5 * (old.get("retweets") or 0)
            new_we = (new.get("likes") or 0) + 3 * (new.get("replies") or 0) + 5 * (new.get("retweets") or 0)
            delta_we = new_we - old_we
            old_dt = _parse_dt(old["recorded_at"])
            new_dt = _parse_dt(new["recorded_at"])
            delta_hours = (new_dt - old_dt).total_seconds() / 3600
            return max(delta_we, 0) / max(delta_hours, 1e-6)
    return 0.0


def percentile_rank(values: list[float]) -> list[float]:
    n = len(values)
    if n == 0:
        return []
    sorted_vals = sorted(enumerate(values), key=lambda x: x[1])
    ranks = [0.0] * n
    for rank_i, (orig_i, _) in enumerate(sorted_vals):
        ranks[orig_i] = rank_i / max(n - 1, 1)
    return ranks


def filter_candidates(tweets: list[dict], now: datetime, max_age_hours: int = 72) -> list[dict]:
    result = []
    for t in tweets:
        if t.get("is_retweet"):
            continue
        if t.get("is_reply"):
            continue
        if t.get("is_pinned"):
            continue
        age_hours = (now - _parse_dt(t["posted_at"])).total_seconds() / 3600
        if age_hours > max_age_hours:
            continue
        result.append(t)
    return result


def compute_viral_scores(tweets_with_snapshots: list[tuple[dict, list[dict]]], now: datetime) -> list[dict]:
    """
    tweets_with_snapshots: list of (tweet_dict, snapshots_list)
    Returns list of dicts with all components + viral_score, sorted descending.
    """
    if not tweets_with_snapshots:
        return []

    rows = []
    for tweet, snaps in tweets_with_snapshots:
        rows.append({
            "tweet": tweet,
            "snapshots": snaps,
            "r_vm": view_momentum(snaps),
            "r_reach": reach(tweet),
            "r_qual": quality(tweet),
            "r_em": engagement_momentum(snaps),
            "freshness": freshness(tweet, now),
        })

    vm_ranks = percentile_rank([r["r_vm"] for r in rows])
    reach_ranks = percentile_rank([r["r_reach"] for r in rows])
    qual_ranks = percentile_rank([r["r_qual"] for r in rows])
    em_ranks = percentile_rank([r["r_em"] for r in rows])

    results = []
    for i, row in enumerate(rows):
        t = row["tweet"]
        f = row["freshness"]
        score = f * (0.40 * vm_ranks[i] + 0.25 * reach_ranks[i] + 0.20 * qual_ranks[i] + 0.15 * em_ranks[i])
        results.append({
            "account": t.get("username"),
            "url": t.get("url"),
            "created_at": t.get("posted_at"),
            "views": t.get("views"),
            "likes": t.get("likes"),
            "replies": t.get("replies"),
            "retweets": t.get("retweets"),
            "weighted_engagement": weighted_engagement(t),
            "quality": quality(t),
            "view_momentum": row["r_vm"],
            "engagement_momentum": row["r_em"],
            "freshness": f,
            "viral_score": score,
        })

    results.sort(key=lambda x: x["viral_score"], reverse=True)
    return results


def rank_by_viral_score(tweets_with_snapshots: list[tuple[dict, list[dict]]], now: datetime) -> list[dict]:
    tweets = [t for t, _ in tweets_with_snapshots]
    snap_map = {t["url"]: s for t, s in tweets_with_snapshots}
    candidates = filter_candidates(tweets, now)
    candidate_pairs = [(t, snap_map[t["url"]]) for t in candidates]
    return compute_viral_scores(candidate_pairs, now)
