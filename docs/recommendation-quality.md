# Recommendation quality and explainability

BoTTube's `recommended` feed ranks a bounded pool of eligible videos using four signals: freshness, engagement, viewer category affinity, and creator/category diversity.

## Ranking signals

`RecommendationEngine.score_video_components()` exposes the exact components used by the ranker:

- `freshness`: exponential age decay with a 24-hour half-life.
- `engagement_normalized`: log-scaled lifetime engagement plus a recent-activity bonus.
- `category_affinity`: time-decayed affinity derived from the viewer's recent distinct-video watch history.
- `raw_diversity_multiplier`: the legacy creator/category concentration penalty.
- `diversity_multiplier`: the effective penalty after `diversity_weight` is applied.
- `base_score`: weighted score before diversity.

The default `diversity_weight` preserves the previous diversity multiplier exactly. Setting it to `0` disables diversity penalties; larger values make concentration penalties stronger.

## Explanations

Recommended records carry two additive fields:

- `recommend_signals`: rounded component values suitable for diagnostics or creator/operator analytics.
- `recommend_reasons`: stable reason identifiers intended for UI copy or aggregation.

Current reason identifiers are `trending_now`, `fresh_upload`, `strong_engagement`, `matches_watch_history`, and `balanced_recommendation`.

These explanations do **not** include raw watch-history events, watched video IDs, or another user's private history. `matches_watch_history` only states that the aggregate category-affinity signal was strong enough to matter.

## Replay resistance

Category affinity counts each distinct watched video once, using the most recent watch timestamp for that video. Replaying one clip repeatedly therefore cannot crowd the 50-item preference window and manufacture a category preference.

## Diagnostics

`recommendation_diagnostics(recommendations)` returns aggregate output quality metrics:

- recommendation count;
- unique creator count;
- top-creator share;
- average recommendation score;
- reason-frequency counts.

This is deliberately aggregate so it can be used in operator and creator-facing analytics without exposing viewer-level history.

## Candidate pool and limits

The recommended feed evaluates a wider bounded pool than the final page (`8x` the requested size, at least 80 and at most 500 candidates). Public recommendation requests are capped at 100 returned items. This gives engagement and affinity signals room to surface strong content while keeping the greedy diversity pass bounded.

## Regression coverage

`tests/test_recommendation_quality.py` verifies:

- `diversity_weight` is functional and the default remains backward-compatible;
- recommendation annotations do not mutate caller-owned candidate dictionaries;
- explanation fields contain aggregate signals rather than raw watch history;
- diagnostics report creator concentration and reason frequencies;
- replaying one video cannot overpower multiple distinct watches in affinity ranking.
