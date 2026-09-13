"""Regression coverage for Studio's public JSON request contract."""

import pytest
from flask import Flask

import studio_blueprint as studio
from studio_blueprint import VIDEO_TIERS, _valid_studio_price, _video_cost, studio_bp


@pytest.fixture()
def client():
    app = Flask(__name__)
    app.config.update(SECRET_KEY="test", PROPAGATE_EXCEPTIONS=False)
    app.register_blueprint(studio_bp)
    return app.test_client()


@pytest.mark.parametrize(
    "payload",
    [
        ["not", "an", "object"],
        {"type": ["video"], "prompt": "hello"},
        {"type": "video", "prompt": ["hello"]},
        {"type": "video", "prompt": "hello", "tier": ["text_card"]},
        {"type": "i2v", "prompt": "hello", "image": ["not-base64"]},
    ],
)
def test_generate_rejects_malformed_json_types_without_server_error(client, payload):
    response = client.post("/api/studio/generate", json=payload)

    assert response.status_code == 400
    assert response.get_json()["error"]


def test_generate_preserves_empty_object_validation(client):
    response = client.post("/api/studio/generate", json={})

    assert response.status_code == 400
    assert response.get_json() == {"error": "prompt required"}


def test_video_cost_defaults_non_finite_seconds_instead_of_raising():
    tier = VIDEO_TIERS["text_card"]

    cost, seconds = _video_cost("text_card", "1e309")

    assert seconds == tier["default_s"]
    assert cost == round(tier["rtc_per_sec"] * tier["default_s"], 2)


@pytest.mark.parametrize("bad_cost", [-0.01, float("nan"), float("inf"), float("-inf"), True])
def test_studio_price_validator_rejects_negative_nonfinite_and_boolean_values(bad_cost):
    assert not _valid_studio_price(bad_cost)


@pytest.mark.parametrize("valid_cost", [0, 0.0, 0.5, 3])
def test_studio_price_validator_preserves_nonnegative_finite_values(valid_cost):
    assert _valid_studio_price(valid_cost)


@pytest.mark.parametrize("bad_cost", [-0.5, float("nan"), float("inf"), float("-inf")])
def test_generate_rejects_invalid_configured_price_before_database(client, monkeypatch, bad_cost):
    monkeypatch.setattr(studio, "IMAGE_RTC", bad_cost)

    def database_must_not_open():
        pytest.fail("database opened before invalid Studio price was rejected")

    monkeypatch.setattr(studio, "_conn", database_must_not_open)

    response = client.post("/api/studio/generate", json={"type": "image", "prompt": "hello"})

    assert response.status_code == 503
    assert response.get_json() == {"error": "studio pricing is misconfigured"}
