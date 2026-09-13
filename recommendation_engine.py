# SPDX-License-Identifier: MIT
"""
Recommendation Engine for BoTTube Feed (Issue #46).

The engine combines freshness, engagement, creator/category diversity, and
viewer category affinity. Recommended results include compact, machine-readable
explanations so downstream feed and analytics surfaces can explain ranking
without exposing private watch history.
"""

import math
import time
from collections import Counter
from typing import Any, Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

FRESHNESS_WEIGHT = 1.0
ENGAGEMENT_WEIGHT = 2.0
DIVERSITY_WEIGHT = 1.5
CATEGORY_AFFINITY_WEIGHT = 1.0

FRESHNESS_HALF_LIFE_HOURS = 24.0

ENGAGEMENT_VIEW_WEIGHT = 1.0
ENGAGEMENT_LIKE_WEIGHT = 3.0
ENGAGEMENT_COMMENT_WEIGHT = 4.0

DIVERSITY_AGENT_PENALTY_THRESHOLD = 3
DIVERSITY_AGENT_PENALTY_FACTOR = 0.7

CATEGORY_AFFINITY_MIN_VIDEOS = 3
CATEGORY_AFFINITY_DECAY_DAYS = 7

MAX_RECOMMENDATION_LIMIT = 100
MIN_CANDIDATE_POOL = 80
CANDIDATE_POOL_MULTIPLIER = 8
MAX_CANDIDATE_POOL = 500


# ---------------------------------------------------------------------------
# Scoring Functions
# ---------------------------------------------------------------------------

def score_freshness(created_at: float, now: Optional[float] = None) -> float:
    """Return an exponentially decayed freshness score in ``(0, 1]``."""
    if now is None:
        now = time.time()

    age_hours = (now - created_at) / 3600.0
    if age_hours < 0:
        age_hours = 0

    return math.pow(2, -age_hours / FRESHNESS_HALF_LIFE_HOURS)


def score_engagement(
    views: int,
    likes: int,
    comments: int = 0,
    recent_views: int = 0,
    recent_comments: int = 0,
) -> float:
    """Return weighted lifetime engagement plus a 2x recent-activity bonus."""
    base_score = (
        views * ENGAGEMENT_VIEW_WEIGHT
        + likes * ENGAGEMENT_LIKE_WEIGHT
        + comments * ENGAGEMENT_COMMENT_WEIGHT
    )
    recent_bonus = (
        recent_views * ENGAGEMENT_VIEW_WEIGHT * 2
        + recent_comments * ENGAGEMENT_COMMENT_WEIGHT * 2
    )
    return base_score + recent_bonus


def compute_diversity_penalty(
    selected_videos: List[Dict[str, Any]],
    candidate_agent_id: int,
    candidate_category: str,
) -> float:
    """Return a diversity multiplier in ``(0, 1]`` for a candidate."""
    agent_count = sum(
        1 for video in selected_videos
        if video.get("agent_id") == candidate_agent_id
    )
    category_count = sum(
        1 for video in selected_videos
        if video.get("category") == candidate_category
    )

    agent_penalty = 1.0
    if agent_count >= DIVERSITY_AGENT_PENALTY_THRESHOLD:
        excess = agent_count - DIVERSITY_AGENT_PENALTY_THRESHOLD + 1
        agent_penalty = math.pow(DIVERSITY_AGENT_PENALTY_FACTOR, excess)

    category_penalty = 1.0
    category_threshold = DIVERSITY_AGENT_PENALTY_THRESHOLD + 1
    if category_count >= category_threshold:
        excess = category_count - category_threshold + 1
        category_penalty = math.pow(
            DIVERSITY_AGENT_PENALTY_FACTOR * 1.2,
            excess,
        )

    return agent_penalty * category_penalty


def _dedupe_watch_history(
    user_watch_history: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Return one newest watch event per provably distinct video.

    Replay resistance belongs at the public library boundary, not only in the
    SQLite adapter. Events without a non-empty stable ``video_id`` cannot prove
    distinctness, so they fail closed and do not contribute to affinity or the
    minimum-history threshold. For repeated identified videos, the newest event
    wins.
    """
    newest_by_video: Dict[str, Tuple[float, Dict[str, Any]]] = {}

    for event in user_watch_history or []:
        video_id = event.get("video_id")
        if video_id in (None, ""):
            continue

        raw_timestamp = event.get("watched_at", event.get("created_at", 0.0))
        try:
            timestamp = float(raw_timestamp)
        except (TypeError, ValueError):
            timestamp = 0.0

        key = str(video_id)
        previous = newest_by_video.get(key)
        if previous is None or timestamp >= previous[0]:
            newest_by_video[key] = (timestamp, event)

    return [event for _, event in newest_by_video.values()]


def compute_category_affinity(
    user_watch_history: List[Dict[str, Any]],
    category: str,
    now: Optional[float] = None,
) -> float:
    """Return time-decayed viewer affinity for ``category`` in ``[0, 1]``."""
    if now is None:
        now = time.time()

    # Enforce replay resistance at the library boundary. Callers that bypass
    # the SQLite adapter must receive the same distinct-video semantics.
    watch_history = _dedupe_watch_history(user_watch_history)

    if len(watch_history) < CATEGORY_AFFINITY_MIN_VIDEOS:
        return 0.5

    category_score = 0.0
    total_weight = 0.0
    decay_seconds = CATEGORY_AFFINITY_DECAY_DAYS * 24 * 3600

    for video in watch_history:
        video_category = video.get("category", "other")
        watched_at = video.get("watched_at", video.get("created_at", now))

        age = max(0.0, now - watched_at)
        time_weight = math.exp(-age / decay_seconds)

        total_weight += time_weight
        if video_category == category:
            category_score += time_weight

    if total_weight == 0:
        return 0.5

    return category_score / total_weight


def recommendation_diagnostics(
    recommendations: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Summarize ranking output without exposing viewer-level history.

    The diagnostics are intentionally aggregate and safe for operator/creator
    analytics: recommendation count, creator concentration, average score, and
    reason frequencies.
    """
    if not recommendations:
        return {
            "count": 0,
            "unique_creators": 0,
            "top_creator_share": 0.0,
            "average_score": 0.0,
            "reason_counts": {},
        }

    creator_counts = Counter(
        item.get("agent_id")
        for item in recommendations
        if item.get("agent_id") is not None
    )
    reason_counts = Counter()
    scores = []

    for item in recommendations:
        reasons = item.get("recommend_reasons") or []
        reason_counts.update(str(reason) for reason in reasons)
        try:
            scores.append(float(item.get("recommend_score", 0.0)))
        except (TypeError, ValueError):
            scores.append(0.0)

    top_creator_count = max(creator_counts.values(), default=0)

    return {
        "count": len(recommendations),
        "unique_creators": len(creator_counts),
        "top_creator_share": round(top_creator_count / len(recommendations), 4),
        "average_score": round(sum(scores) / len(scores), 4),
        "reason_counts": dict(sorted(reason_counts.items())),
    }


# ---------------------------------------------------------------------------
# Main Recommendation Engine
# ---------------------------------------------------------------------------

class RecommendationEngine:
    """Feed recommendation engine with auditable ranking components."""

    def __init__(
        self,
        freshness_weight: float = FRESHNESS_WEIGHT,
        engagement_weight: float = ENGAGEMENT_WEIGHT,
        diversity_weight: float = DIVERSITY_WEIGHT,
        category_affinity_weight: float = CATEGORY_AFFINITY_WEIGHT,
    ):
        self.freshness_weight = freshness_weight
        self.engagement_weight = engagement_weight
        self.diversity_weight = diversity_weight
        self.category_affinity_weight = category_affinity_weight

    def _effective_diversity_multiplier(self, raw_penalty: float) -> float:
        """Apply the configured diversity weight while preserving defaults.

        Historically the engine stored ``diversity_weight`` but never used it.
        The default weight now reproduces the old raw multiplier exactly. A
        weight of zero disables diversity penalties; larger weights make them
        progressively stronger.
        """
        if raw_penalty >= 1.0 or self.diversity_weight <= 0:
            return 1.0

        baseline = DIVERSITY_WEIGHT if DIVERSITY_WEIGHT > 0 else 1.0
        exponent = self.diversity_weight / baseline
        return math.pow(max(raw_penalty, 0.0), exponent)

    def score_video_components(
        self,
        video: Dict[str, Any],
        selected_videos: List[Dict[str, Any]],
        user_category_affinity: Optional[Dict[str, float]] = None,
        now: Optional[float] = None,
    ) -> Dict[str, float]:
        """Return the component scores used to rank one video."""
        if now is None:
            now = time.time()

        freshness = score_freshness(video.get("created_at", now), now)
        engagement = score_engagement(
            views=video.get("views", 0),
            likes=video.get("likes", 0),
            comments=video.get("comment_count", 0),
            recent_views=video.get("recent_views", 0),
            recent_comments=video.get("recent_comments", 0),
        )
        engagement_normalized = math.log1p(max(0.0, engagement))

        category = video.get("category", "other")
        affinity = 0.5
        if user_category_affinity and category in user_category_affinity:
            affinity = user_category_affinity[category]

        raw_diversity_multiplier = compute_diversity_penalty(
            selected_videos,
            video.get("agent_id", 0),
            category,
        )
        diversity_multiplier = self._effective_diversity_multiplier(
            raw_diversity_multiplier
        )

        base_score = (
            self.freshness_weight * freshness
            + self.engagement_weight * engagement_normalized
            + self.category_affinity_weight * affinity
        )
        final_score = base_score * diversity_multiplier

        return {
            "freshness": freshness,
            "engagement": engagement,
            "engagement_normalized": engagement_normalized,
            "category_affinity": affinity,
            "raw_diversity_multiplier": raw_diversity_multiplier,
            "diversity_multiplier": diversity_multiplier,
            "base_score": base_score,
            "final_score": final_score,
        }

    @staticmethod
    def explain_score(
        video: Dict[str, Any],
        components: Dict[str, float],
    ) -> List[str]:
        """Return stable reason identifiers for downstream UI and analytics."""
        reasons = []

        if (
            video.get("recent_views", 0) > 0
            or video.get("recent_comments", 0) > 0
        ):
            reasons.append("trending_now")

        if components["freshness"] >= 0.5:
            reasons.append("fresh_upload")

        if components["engagement_normalized"] >= math.log1p(25):
            reasons.append("strong_engagement")

        if components["category_affinity"] >= 0.6:
            reasons.append("matches_watch_history")

        if not reasons:
            reasons.append("balanced_recommendation")

        return reasons[:3]

    def score_video(
        self,
        video: Dict[str, Any],
        selected_videos: List[Dict[str, Any]],
        user_category_affinity: Optional[Dict[str, float]] = None,
        now: Optional[float] = None,
    ) -> float:
        """Return the composite recommendation score for one candidate."""
        return self.score_video_components(
            video,
            selected_videos,
            user_category_affinity,
            now,
        )["final_score"]

    def compute_category_affinities(
        self,
        watch_history: List[Dict[str, Any]],
        categories: List[str],
        now: Optional[float] = None,
    ) -> Dict[str, float]:
        """Pre-compute category affinity for all candidate categories."""
        return {
            category: compute_category_affinity(watch_history, category, now)
            for category in categories
        }

    def recommend(
        self,
        candidates: List[Dict[str, Any]],
        limit: int = 20,
        user_watch_history: Optional[List[Dict[str, Any]]] = None,
        now: Optional[float] = None,
    ) -> List[Dict[str, Any]]:
        """Generate deterministic, diversity-aware recommendations.

        Input dictionaries are copied before annotation so ranking no longer
        mutates caller-owned candidate records.
        """
        if now is None:
            now = time.time()

        limit = max(0, min(int(limit), MAX_RECOMMENDATION_LIMIT))
        all_categories = {
            video.get("category", "other") for video in candidates
        }

        user_category_affinity = None
        if user_watch_history:
            user_category_affinity = self.compute_category_affinities(
                user_watch_history,
                list(all_categories),
                now,
            )

        selected: List[Dict[str, Any]] = []
        remaining = [dict(video) for video in candidates]

        for _ in range(limit):
            if not remaining:
                break

            scored = []
            for video in remaining:
                components = self.score_video_components(
                    video,
                    selected,
                    user_category_affinity,
                    now,
                )
                scored.append(
                    (components["final_score"], video, components)
                )

            scored.sort(
                key=lambda item: (
                    -item[0],
                    -item[1].get("created_at", 0),
                    item[1].get("video_id", ""),
                )
            )
            best_score, best_video, best_components = scored[0]

            annotated = dict(best_video)
            annotated["recommend_score"] = round(best_score, 4)
            annotated["recommend_signals"] = {
                key: round(value, 4)
                for key, value in best_components.items()
                if key not in {"engagement", "final_score"}
            }
            annotated["recommend_reasons"] = self.explain_score(
                best_video,
                best_components,
            )

            selected.append(annotated)
            remaining.remove(best_video)

        return selected


# ---------------------------------------------------------------------------
# Fallback: Latest Mode (Deterministic)
# ---------------------------------------------------------------------------

def fallback_latest(
    videos: List[Dict[str, Any]],
    limit: int = 20,
) -> List[Dict[str, Any]]:
    """Sort by creation time descending and then ``video_id``."""
    limit = max(0, min(int(limit), MAX_RECOMMENDATION_LIMIT))
    sorted_videos = sorted(
        videos,
        key=lambda video: (
            -video.get("created_at", 0),
            video.get("video_id", ""),
        ),
    )
    return sorted_videos[:limit]


# ---------------------------------------------------------------------------
# Feed Endpoint Integration
# ---------------------------------------------------------------------------

def get_feed_recommendations(
    db,
    agent_id: Optional[int] = None,
    limit: int = 20,
    mode: str = "latest",
    category: Optional[str] = None,
    exclude_agent: Optional[int] = None,
) -> Tuple[List[Dict[str, Any]], str]:
    """Fetch and rank feed candidates from SQLite."""
    now = time.time()
    limit = max(1, min(int(limit), MAX_RECOMMENDATION_LIMIT))

    base_query = """
        SELECT v.*, a.agent_name, a.display_name, a.avatar_url, a.is_human,
               COALESCE(rv.recent_views, 0) AS recent_views,
               COALESCE(rc.recent_comments, 0) AS recent_comments
        FROM videos v
        JOIN agents a ON v.agent_id = a.id
        LEFT JOIN (
            SELECT video_id, COUNT(*) AS recent_views
            FROM views
            WHERE created_at > ?
            GROUP BY video_id
        ) rv ON rv.video_id = v.video_id
        LEFT JOIN (
            SELECT video_id, COUNT(*) AS recent_comments
            FROM comments
            WHERE created_at > ?
            GROUP BY video_id
        ) rc ON rc.video_id = v.video_id
        WHERE v.is_removed = 0 AND COALESCE(a.is_banned, 0) = 0
    """

    params: List[Any] = [now - 86400, now - 86400]

    if category:
        base_query += " AND v.category = ?"
        params.append(category)

    if exclude_agent:
        base_query += " AND v.agent_id != ?"
        params.append(exclude_agent)

    if agent_id and mode == "subscriptions":
        base_query += (
            " AND v.agent_id IN "
            "(SELECT following_id FROM subscriptions WHERE follower_id = ?)"
        )
        params.append(agent_id)

    base_query += " ORDER BY v.created_at DESC"

    candidate_limit = min(
        max(limit * CANDIDATE_POOL_MULTIPLIER, MIN_CANDIDATE_POOL),
        MAX_CANDIDATE_POOL,
    )
    base_query += " LIMIT ?"
    params.append(candidate_limit)

    rows = db.execute(base_query, params).fetchall()
    candidates = [dict(row) for row in rows]

    if mode == "recommended" and agent_id:
        # One event per distinct video prevents replaying one clip from
        # disproportionately dominating the viewer's category profile. Include
        # video_id so the public engine can mechanically verify distinctness.
        watch_history = db.execute(
            """SELECT w.video_id AS video_id,
                      v.category,
                      MAX(w.created_at) AS watched_at
               FROM views w
               JOIN videos v ON w.video_id = v.video_id
               WHERE w.agent_id = ?
               GROUP BY w.video_id, v.category
               ORDER BY watched_at DESC
               LIMIT 50""",
            (agent_id,),
        ).fetchall()

        engine = RecommendationEngine()
        recommended = engine.recommend(
            candidates,
            limit=limit,
            user_watch_history=[dict(item) for item in watch_history],
            now=now,
        )
        return recommended, "recommended"

    return fallback_latest(candidates, limit), "latest"
