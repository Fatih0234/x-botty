# twitter-bot2

Scrapes Twitter/X and stores results in a SQLite database, running on a GitHub Actions schedule.

## Persistence

`data/twitter.db` is persisted as a GitHub Release asset under the tag `latest-db` — it is **not** committed to git.

How it works:
- **First run**: no release exists, scraper starts with a fresh DB, then creates the `latest-db` release and uploads `twitter.db` as an asset.
- **Subsequent runs**: workflow downloads the existing `twitter.db` from the release, runs the scraper (appending new data), then re-uploads the updated file with `--clobber`.

This keeps the git history clean and avoids ever storing the database in the repository.

## Viral Score Metrics

Each scrape run computes and stores six metrics on the latest snapshot for every tweet within the 72-hour tracking window (`snapshots` table).

### `view_momentum`
Views gained per hour over the most recent snapshot window (prefers ≤6h, falls back to ≤24h).
```
(views_latest - views_oldest) / hours_elapsed
```

### `engagement_momentum`
Weighted engagement gained per hour over the same window.
```
weighted_engagement = likes + 3×replies + 5×retweets
engagement_momentum = (we_latest - we_oldest) / hours_elapsed
```

### `quality`
Engagement density — how much engagement a tweet earned relative to its views.
```
(likes + 3×replies + 5×retweets) / max(views, 1)
```

### `reach`
Logarithmic scale of absolute view count (dampens outlier spikes).
```
log1p(views)
```

### `freshness`
Exponential decay by tweet age. A brand-new tweet scores 1.0; a 72h-old tweet scores ~0.14.
```
exp(-age_hours / 36)
```

### `viral_score`
Each of the four raw metrics is converted to a **percentile rank** (0–1) within the current scrape batch, then combined with freshness as a multiplier:
```
viral_score = freshness × (0.40×view_momentum_pct + 0.25×reach_pct + 0.20×quality_pct + 0.15×engagement_momentum_pct)
```

> `viral_score` is batch-relative — values are only comparable within the same scrape run, not across different runs.
