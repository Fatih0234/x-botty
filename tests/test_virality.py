import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from datetime import datetime, timezone, timedelta
from virality import (
    weighted_engagement, quality, reach, freshness,
    view_momentum, engagement_momentum, percentile_rank,
    filter_candidates, compute_viral_scores, rank_by_viral_score,
)

NOW = datetime(2026, 3, 20, 12, 0, 0, tzinfo=timezone.utc)


def make_tweet(**kwargs):
    defaults = dict(
        url="https://x.com/user/status/1",
        username="user",
        posted_at=NOW.isoformat(),
        views=1000,
        likes=10,
        replies=2,
        retweets=1,
        is_retweet=0,
        is_reply=0,
        is_pinned=0,
    )
    defaults.update(kwargs)
    return defaults


def make_snap(recorded_at, views=1000, likes=10, replies=2, retweets=1):
    return dict(recorded_at=recorded_at.isoformat(), views=views, likes=likes, replies=replies, retweets=retweets)


# --- feature functions ---

def test_quality_missing_views():
    t = make_tweet(views=None)
    # denominator should be 1, not 0
    assert quality(t) == weighted_engagement(t) / 1


def test_quality_zero_views():
    t = make_tweet(views=0)
    assert quality(t) == weighted_engagement(t) / 1


def test_reach_zero_views():
    t = make_tweet(views=0)
    assert reach(t) == 0.0


def test_weighted_engagement():
    t = make_tweet(likes=10, replies=2, retweets=1)
    assert weighted_engagement(t) == 10 + 3 * 2 + 5 * 1  # 21


# --- momentum ---

def test_view_momentum_no_snapshots():
    assert view_momentum([]) == 0.0


def test_view_momentum_one_snapshot():
    snap = make_snap(NOW)
    assert view_momentum([snap]) == 0.0


def test_view_momentum_two_snapshots():
    old = make_snap(NOW - timedelta(hours=3), views=500)
    new = make_snap(NOW, views=800)
    vm = view_momentum([old, new])
    assert abs(vm - 100.0) < 1.0  # 300 views / 3 hours


def test_engagement_momentum_no_snapshots():
    assert engagement_momentum([]) == 0.0


def test_engagement_momentum_one_snapshot():
    assert engagement_momentum([make_snap(NOW)]) == 0.0


# --- filter_candidates ---

def test_filter_excludes_retweet():
    t = make_tweet(is_retweet=1)
    assert filter_candidates([t], NOW) == []


def test_filter_excludes_reply():
    t = make_tweet(is_reply=1)
    assert filter_candidates([t], NOW) == []


def test_filter_excludes_pinned():
    t = make_tweet(is_pinned=1)
    assert filter_candidates([t], NOW) == []


def test_filter_excludes_old():
    t = make_tweet(posted_at=(NOW - timedelta(hours=73)).isoformat())
    assert filter_candidates([t], NOW) == []


def test_filter_keeps_fresh():
    t = make_tweet()
    assert filter_candidates([t], NOW) == [t]


# --- percentile_rank ---

def test_percentile_rank_single():
    assert percentile_rank([5.0]) == [0.0]


def test_percentile_rank_order():
    ranks = percentile_rank([10.0, 0.0, 5.0])
    assert ranks[1] < ranks[2] < ranks[0]


# --- scoring ---

def test_no_snapshots_score_still_computed():
    t = make_tweet()
    results = compute_viral_scores([(t, [])], NOW)
    assert len(results) == 1
    assert 0.0 <= results[0]["viral_score"] <= 1.0


def test_fresh_beats_stale():
    # fresh tweet has identical stats but was posted just now — freshness multiplier is ~1 vs ~0.19
    # give both non-trivial, equal absolute stats so percentile ranks are equal (both 0.5),
    # then only the freshness multiplier differentiates them
    # Use 3 tweets: anchor + fresh + stale, so percentile ranks spread properly
    anchor = make_tweet(url="u0", views=200, likes=2, replies=0, retweets=0,
                        posted_at=(NOW - timedelta(hours=10)).isoformat())
    fresh = make_tweet(url="u1", views=500, likes=10, replies=2, retweets=1,
                       posted_at=NOW.isoformat())
    stale = make_tweet(url="u2", views=500, likes=10, replies=2, retweets=1,
                       posted_at=(NOW - timedelta(hours=60)).isoformat())
    results = compute_viral_scores([(anchor, []), (fresh, []), (stale, [])], NOW)
    by_url = {r["url"]: r for r in results}
    assert by_url["u1"]["viral_score"] > by_url["u2"]["viral_score"]


def test_growing_beats_stale_high_ratio():
    # small high-ratio tweet with no growth
    high_ratio = make_tweet(url="u1", views=100, likes=50, replies=10, retweets=5,
                            posted_at=(NOW - timedelta(hours=48)).isoformat())
    # fast-growing tweet with big reach
    growing = make_tweet(url="u2", views=100_000, likes=200, replies=30, retweets=20,
                         posted_at=(NOW - timedelta(hours=2)).isoformat())
    old_snap = make_snap(NOW - timedelta(hours=2), views=50_000)
    new_snap = make_snap(NOW, views=100_000)
    results = rank_by_viral_score([(high_ratio, []), (growing, [old_snap, new_snap])], NOW)
    by_url = {r["url"]: r for r in results}
    assert by_url["u2"]["viral_score"] > by_url["u1"]["viral_score"]
