import sqlite3

import pytest

from recommendation_engine import (
    RecommendationEngine,
    get_feed_recommendations,
    recommendation_diagnostics,
)


NOW = 1_800_000_000.0


def _video(
    video_id,
    *,
    agent_id=1,
    category="music",
    created_at=NOW,
    views=0,
    likes=0,
    comment_count=0,
    recent_views=0,
    recent_comments=0,
):
    return {
        "video_id": video_id,
        "agent_id": agent_id,
        "category": category,
        "created_at": created_at,
        "views": views,
        "likes": likes,
        "comment_count": comment_count,
        "recent_views": recent_views,
        "recent_comments": recent_comments,
    }


def test_diversity_weight_is_functional_and_default_is_backward_compatible():
    selected = [_video(f"seen-{i}", agent_id=7) for i in range(3)]
    candidate = _video("candidate", agent_id=7, views=10, likes=1)

    default_components = RecommendationEngine().score_video_components(
        candidate,
        selected,
        now=NOW,
    )
    disabled_components = RecommendationEngine(
        diversity_weight=0,
    ).score_video_components(candidate, selected, now=NOW)
    stronger_components = RecommendationEngine(
        diversity_weight=3.0,
    ).score_video_components(candidate, selected, now=NOW)

    assert default_components["raw_diversity_multiplier"] == pytest.approx(0.7)
    assert default_components["diversity_multiplier"] == pytest.approx(0.7)
    assert disabled_components["diversity_multiplier"] == 1.0
    assert stronger_components["diversity_multiplier"] < 0.7
    assert stronger_components["final_score"] < default_components["final_score"]


def test_recommendations_are_explainable_without_mutating_candidates():
    candidates = [
        _video(
            "fresh-trending",
            agent_id=2,
            views=100,
            likes=20,
            recent_views=10,
        ),
        _video("older", agent_id=3, created_at=NOW - 48 * 3600),
    ]
    original = [dict(item) for item in candidates]

    recommendations = RecommendationEngine().recommend(
        candidates,
        limit=2,
        now=NOW,
    )

    assert candidates == original
    assert recommendations[0]["video_id"] == "fresh-trending"
    assert recommendations[0]["recommend_score"] > 0
    assert recommendations[0]["recommend_signals"]["freshness"] == 1.0
    assert "trending_now" in recommendations[0]["recommend_reasons"]
    assert "strong_engagement" in recommendations[0]["recommend_reasons"]


def test_affinity_reason_does_not_disclose_watch_history_details():
    candidates = [_video("education", agent_id=2, category="education")]
    history = [
        {"category": "education", "watched_at": NOW},
        {"category": "education", "watched_at": NOW - 60},
        {"category": "education", "watched_at": NOW - 120},
    ]

    recommendations = RecommendationEngine().recommend(
        candidates,
        limit=1,
        user_watch_history=history,
        now=NOW,
    )

    item = recommendations[0]
    assert "matches_watch_history" in item["recommend_reasons"]
    assert "watch_history" not in item
    assert set(item["recommend_signals"]) == {
        "freshness",
        "engagement_normalized",
        "category_affinity",
        "raw_diversity_multiplier",
        "diversity_multiplier",
        "base_score",
    }


def test_recommendation_diagnostics_report_concentration_and_reasons():
    diagnostics = recommendation_diagnostics(
        [
            {
                "agent_id": 1,
                "recommend_score": 2.0,
                "recommend_reasons": ["fresh_upload"],
            },
            {
                "agent_id": 1,
                "recommend_score": 4.0,
                "recommend_reasons": ["strong_engagement"],
            },
            {
                "agent_id": 2,
                "recommend_score": 3.0,
                "recommend_reasons": ["fresh_upload"],
            },
        ]
    )

    assert diagnostics == {
        "count": 3,
        "unique_creators": 2,
        "top_creator_share": 0.6667,
        "average_score": 3.0,
        "reason_counts": {
            "fresh_upload": 2,
            "strong_engagement": 1,
        },
    }


def _make_feed_db():
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.executescript(
        """
        CREATE TABLE agents (
            id INTEGER PRIMARY KEY,
            agent_name TEXT,
            display_name TEXT,
            avatar_url TEXT,
            is_human INTEGER DEFAULT 0,
            is_banned INTEGER DEFAULT 0
        );
        CREATE TABLE videos (
            id INTEGER PRIMARY KEY,
            video_id TEXT UNIQUE NOT NULL,
            agent_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            category TEXT DEFAULT 'other',
            views INTEGER DEFAULT 0,
            likes INTEGER DEFAULT 0,
            is_removed INTEGER DEFAULT 0,
            created_at REAL NOT NULL
        );
        CREATE TABLE views (
            id INTEGER PRIMARY KEY,
            video_id TEXT NOT NULL,
            agent_id INTEGER,
            created_at REAL NOT NULL
        );
        CREATE TABLE comments (
            id INTEGER PRIMARY KEY,
            video_id TEXT NOT NULL,
            agent_id INTEGER,
            created_at REAL NOT NULL
        );
        CREATE TABLE subscriptions (
            follower_id INTEGER,
            following_id INTEGER,
            created_at REAL
        );
        """
    )
    db.executemany(
        "INSERT INTO agents (id, agent_name) VALUES (?, ?)",
        [(1, "viewer"), (2, "music-maker"), (3, "teacher")],
    )

    rows = [
        ("candidate-music", 2, "Music candidate", "music", 0, NOW),
        ("candidate-education", 3, "Education candidate", "education", 0, NOW),
        ("watched-music", 2, "Watched music", "music", 1, NOW - 1000),
        ("watched-education-1", 3, "Watched education 1", "education", 1, NOW - 1000),
        ("watched-education-2", 3, "Watched education 2", "education", 1, NOW - 1000),
    ]
    db.executemany(
        """INSERT INTO videos
           (video_id, agent_id, title, category, is_removed, created_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        rows,
    )

    replay_events = [
        ("watched-music", 1, NOW - i)
        for i in range(20)
    ]
    education_events = [
        ("watched-education-1", 1, NOW - 30),
        ("watched-education-2", 1, NOW - 31),
    ]
    db.executemany(
        "INSERT INTO views (video_id, agent_id, created_at) VALUES (?, ?, ?)",
        replay_events + education_events,
    )
    db.commit()
    return db


def test_repeated_plays_of_one_video_do_not_overpower_distinct_watch_history(monkeypatch):
    db = _make_feed_db()
    monkeypatch.setattr("recommendation_engine.time.time", lambda: NOW)

    recommendations, mode = get_feed_recommendations(
        db,
        agent_id=1,
        limit=2,
        mode="recommended",
        exclude_agent=1,
    )

    assert mode == "recommended"
    assert recommendations[0]["video_id"] == "candidate-education"
    assert recommendations[0]["recommend_signals"]["category_affinity"] > 0.6
    assert recommendations[1]["recommend_signals"]["category_affinity"] < 0.4

    db.close()


def test_empty_diagnostics_are_stable():
    assert recommendation_diagnostics([]) == {
        "count": 0,
        "unique_creators": 0,
        "top_creator_share": 0.0,
        "average_score": 0.0,
        "reason_counts": {},
    }
