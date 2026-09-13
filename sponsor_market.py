"""BoTTube creator sponsorship inventory, media-kit, and proposal tooling.

The module is deliberately offline and authority-limited.  It can prepare and
verify deterministic commercial artifacts, but it cannot contact sponsors,
serve ads, accept money, form contracts, or assert recognized revenue.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import stat
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


INVENTORY_SCHEMA = "bottube-sponsor-inventory/v1"
MEDIA_KIT_SCHEMA = "bottube-sponsor-media-kit/v1"
PROPOSAL_SCHEMA = "bottube-sponsor-proposal/v1"
RESERVATION_SCHEMA = "bottube-sponsor-reservation-book/v1"
LIFECYCLE_SCHEMA = "bottube-sponsor-proposal-lifecycle/v1"

PLACEMENTS = {
    "PRE_ROLL",
    "MID_ROLL",
    "POST_ROLL",
    "DESCRIPTION",
    "PINNED_COMMENT",
}
PROPOSAL_STATES = {"DRAFT", "OWNER_APPROVED", "WITHDRAWN"}
SPONSOR_REF_RE = re.compile(r"^spn_[A-Za-z0-9_-]{6,64}$")
ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{1,63}$")
CURRENCY_RE = re.compile(r"^[A-Z]{3}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
SECRET_RE = re.compile(
    r"(?i)(api[_-]?key|secret|token|password|bearer\s+[a-z0-9._~+/=-]{8,}|sk-[a-z0-9_-]{10,})"
)
EMAIL_RE = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.I)
PHONE_RE = re.compile(r"(?<!\w)(?:\+?1[-. ]?)?\(?\d{3}\)?[-. ]?\d{3}[-. ]?\d{4}(?!\w)")
URL_CREDENTIAL_RE = re.compile(r"(?i)https?://[^/\s:@]+:[^/\s@]+@")
CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
MAX_JSON_BYTES = 2 * 1024 * 1024
MAX_TEXT = 240
MAX_ITEMS = 256
MAX_SAFE_INT = 9_000_000_000_000_000

AUTHORITY_CEILING = {
    "sponsor_contact": False,
    "ad_delivery": False,
    "provider_mutation": False,
    "contract_signature": False,
    "payment_mutation": False,
    "creator_payout": False,
    "cash_assertion": False,
    "revenue_recognition": False,
    "viewer_profiling": False,
}


class SponsorMarketError(ValueError):
    """Fail-closed validation error for sponsorship artifacts."""


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _strict_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in pairs:
        if key in out:
            raise SponsorMarketError(f"duplicate_json_key:{key}")
        out[key] = value
    return out


def _reject_constant(value: str) -> None:
    raise SponsorMarketError(f"non_finite_json:{value}")


def loads_strict(raw: str) -> Any:
    if not isinstance(raw, str):
        raise SponsorMarketError("json_text_required")
    if len(raw.encode("utf-8")) > MAX_JSON_BYTES:
        raise SponsorMarketError("json_too_large")
    try:
        return json.loads(raw, object_pairs_hook=_strict_pairs, parse_constant=_reject_constant)
    except SponsorMarketError:
        raise
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise SponsorMarketError("invalid_json") from exc


def _ordinary_file_bytes(path: os.PathLike[str] | str) -> bytes:
    p = Path(path)
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    if hasattr(os, "O_NONBLOCK"):
        flags |= os.O_NONBLOCK
    try:
        fd = os.open(p, flags)
    except OSError as exc:
        raise SponsorMarketError("input_open_failed") from exc
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise SponsorMarketError("input_not_regular")
        if info.st_size > MAX_JSON_BYTES:
            raise SponsorMarketError("json_too_large")
        chunks: list[bytes] = []
        remaining = MAX_JSON_BYTES + 1
        while remaining:
            chunk = os.read(fd, min(65536, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b"".join(chunks)
        if len(raw) > MAX_JSON_BYTES:
            raise SponsorMarketError("json_too_large")
        return raw
    finally:
        os.close(fd)


def load_json_file(path: os.PathLike[str] | str) -> Any:
    try:
        text = _ordinary_file_bytes(path).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SponsorMarketError("json_not_utf8") from exc
    return loads_strict(text)


def _write_exclusive(path: os.PathLike[str] | str, data: str) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(p, flags, 0o600)
    except FileExistsError as exc:
        raise SponsorMarketError("output_exists") from exc
    except OSError as exc:
        raise SponsorMarketError("output_open_failed") from exc
    try:
        raw = data.encode("utf-8")
        sent = 0
        while sent < len(raw):
            sent += os.write(fd, raw[sent:])
        os.fsync(fd)
    finally:
        os.close(fd)


def _write_json_exclusive(path: os.PathLike[str] | str, value: Any) -> None:
    _write_exclusive(path, json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False) + "\n")


def _require_keys(obj: Mapping[str, Any], *, required: set[str], optional: set[str] = set()) -> None:
    if not isinstance(obj, Mapping):
        raise SponsorMarketError("object_required")
    keys = set(obj)
    missing = required - keys
    extra = keys - required - optional
    if missing:
        raise SponsorMarketError("missing_fields:" + ",".join(sorted(missing)))
    if extra:
        raise SponsorMarketError("unknown_fields:" + ",".join(sorted(extra)))


def _safe_int(value: Any, name: str, *, minimum: int = 0, maximum: int = MAX_SAFE_INT) -> int:
    if type(value) is not int:
        raise SponsorMarketError(f"{name}_int_required")
    if value < minimum or value > maximum:
        raise SponsorMarketError(f"{name}_out_of_range")
    return value


def _safe_text(value: Any, name: str, *, max_len: int = MAX_TEXT, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise SponsorMarketError(f"{name}_text_required")
    if value != value.strip():
        raise SponsorMarketError(f"{name}_outer_whitespace")
    if (not allow_empty and not value) or len(value) > max_len:
        raise SponsorMarketError(f"{name}_length")
    if CONTROL_RE.search(value) or "\r" in value or "\n" in value:
        raise SponsorMarketError(f"{name}_control")
    if SECRET_RE.search(value) or URL_CREDENTIAL_RE.search(value):
        raise SponsorMarketError(f"{name}_secret_shaped")
    return value


def _public_text(value: Any, name: str, *, max_len: int = MAX_TEXT) -> str:
    text = _safe_text(value, name, max_len=max_len)
    if EMAIL_RE.search(text) or PHONE_RE.search(text):
        raise SponsorMarketError(f"{name}_pii_shaped")
    return text


def _identifier(value: Any, name: str) -> str:
    text = _safe_text(value, name, max_len=64)
    if not ID_RE.fullmatch(text):
        raise SponsorMarketError(f"{name}_invalid")
    return text


def _sponsor_ref(value: Any) -> str:
    text = _safe_text(value, "sponsor_ref", max_len=68)
    if not SPONSOR_REF_RE.fullmatch(text):
        raise SponsorMarketError("sponsor_ref_invalid")
    return text


def _currency(value: Any) -> str:
    if not isinstance(value, str) or not CURRENCY_RE.fullmatch(value):
        raise SponsorMarketError("currency_invalid")
    return value


def _timestamp(value: Any, name: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise SponsorMarketError(f"{name}_utc_required")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise SponsorMarketError(f"{name}_invalid") from exc
    if parsed.tzinfo != timezone.utc or parsed.microsecond:
        raise SponsorMarketError(f"{name}_canonical_utc_required")
    if value != parsed.strftime("%Y-%m-%dT%H:%M:%SZ"):
        raise SponsorMarketError(f"{name}_canonical_utc_required")
    return parsed


def _digest(value: Any, name: str) -> str:
    if not isinstance(value, str) or not SHA256_RE.fullmatch(value):
        raise SponsorMarketError(f"{name}_sha256_required")
    return value


def _string_list(value: Any, name: str, *, max_items: int = 32) -> list[str]:
    if not isinstance(value, list) or len(value) > max_items:
        raise SponsorMarketError(f"{name}_list_required")
    out: list[str] = []
    for item in value:
        out.append(_public_text(item, name, max_len=80))
    if len(set(out)) != len(out):
        raise SponsorMarketError(f"{name}_duplicate")
    return sorted(out)


def _authority() -> dict[str, bool]:
    return dict(AUTHORITY_CEILING)


def _seal(packet: dict[str, Any]) -> dict[str, Any]:
    if "receipt_sha256" in packet:
        raise SponsorMarketError("receipt_already_present")
    sealed = dict(packet)
    sealed["receipt_sha256"] = _sha256(packet)
    return sealed


def _verify_seal(packet: Mapping[str, Any]) -> None:
    if not isinstance(packet, Mapping):
        raise SponsorMarketError("packet_object_required")
    receipt = packet.get("receipt_sha256")
    _digest(receipt, "receipt")
    unsigned = dict(packet)
    unsigned.pop("receipt_sha256", None)
    if _sha256(unsigned) != receipt:
        raise SponsorMarketError("receipt_mismatch")


def compile_inventory(spec: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and seal one creator's sponsorship inventory generation."""
    _require_keys(
        spec,
        required={"creator_id", "generation", "issued_at", "currency", "packages"},
    )
    creator_id = _identifier(spec["creator_id"], "creator_id")
    generation = _safe_int(spec["generation"], "generation", minimum=1, maximum=2_000_000_000)
    issued_at = spec["issued_at"]
    _timestamp(issued_at, "issued_at")
    currency = _currency(spec["currency"])
    packages_raw = spec["packages"]
    if not isinstance(packages_raw, list) or not packages_raw or len(packages_raw) > MAX_ITEMS:
        raise SponsorMarketError("packages_invalid")

    packages: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in packages_raw:
        _require_keys(
            raw,
            required={
                "package_id",
                "title",
                "placement",
                "rate_minor",
                "slots",
                "window_start",
                "window_end",
                "allowed_sponsor_categories",
                "blocked_sponsor_categories",
            },
        )
        package_id = _identifier(raw["package_id"], "package_id")
        if package_id in seen:
            raise SponsorMarketError("package_id_duplicate")
        seen.add(package_id)
        title = _public_text(raw["title"], "title", max_len=100)
        placement = raw["placement"]
        if placement not in PLACEMENTS:
            raise SponsorMarketError("placement_invalid")
        rate_minor = _safe_int(raw["rate_minor"], "rate_minor", minimum=1)
        slots = _safe_int(raw["slots"], "slots", minimum=1, maximum=100_000)
        start = raw["window_start"]
        end = raw["window_end"]
        start_dt = _timestamp(start, "window_start")
        end_dt = _timestamp(end, "window_end")
        if end_dt <= start_dt:
            raise SponsorMarketError("package_window_invalid")
        allowed = _string_list(raw["allowed_sponsor_categories"], "allowed_sponsor_categories")
        blocked = _string_list(raw["blocked_sponsor_categories"], "blocked_sponsor_categories")
        if set(allowed) & set(blocked):
            raise SponsorMarketError("sponsor_category_policy_conflict")
        packages.append(
            {
                "package_id": package_id,
                "title": title,
                "placement": placement,
                "rate_minor": rate_minor,
                "slots": slots,
                "window_start": start,
                "window_end": end,
                "allowed_sponsor_categories": allowed,
                "blocked_sponsor_categories": blocked,
            }
        )
    packages.sort(key=lambda item: item["package_id"])
    packet = {
        "schema": INVENTORY_SCHEMA,
        "creator_id": creator_id,
        "generation": generation,
        "issued_at": issued_at,
        "currency": currency,
        "packages": packages,
        "authority": _authority(),
    }
    return _seal(packet)


def verify_inventory(packet: Mapping[str, Any]) -> bool:
    _verify_seal(packet)
    _require_keys(
        packet,
        required={
            "schema",
            "creator_id",
            "generation",
            "issued_at",
            "currency",
            "packages",
            "authority",
            "receipt_sha256",
        },
    )
    if packet["schema"] != INVENTORY_SCHEMA or packet["authority"] != AUTHORITY_CEILING:
        raise SponsorMarketError("inventory_schema_or_authority_invalid")
    rebuilt = compile_inventory(
        {
            "creator_id": packet["creator_id"],
            "generation": packet["generation"],
            "issued_at": packet["issued_at"],
            "currency": packet["currency"],
            "packages": packet["packages"],
        }
    )
    if rebuilt != dict(packet):
        raise SponsorMarketError("inventory_noncanonical")
    return True


def compile_media_kit(spec: Mapping[str, Any]) -> dict[str, Any]:
    """Seal privacy-minimized aggregate creator facts for sponsor review.

    Inputs are aggregate facts supplied by the host/creator.  The receipt proves
    integrity of this snapshot, not platform/provider authenticity or completeness.
    """
    _require_keys(
        spec,
        required={
            "creator_id",
            "generated_at",
            "window_start",
            "window_end",
            "channel_name",
            "categories",
            "aggregates",
            "source_scope_digest",
        },
    )
    creator_id = _identifier(spec["creator_id"], "creator_id")
    generated_at = spec["generated_at"]
    gen_dt = _timestamp(generated_at, "generated_at")
    start = spec["window_start"]
    end = spec["window_end"]
    start_dt = _timestamp(start, "window_start")
    end_dt = _timestamp(end, "window_end")
    if end_dt <= start_dt or gen_dt < end_dt:
        raise SponsorMarketError("media_window_invalid")
    channel_name = _public_text(spec["channel_name"], "channel_name", max_len=100)
    categories = _string_list(spec["categories"], "categories", max_items=32)
    if not categories:
        raise SponsorMarketError("categories_empty")
    aggregates = spec["aggregates"]
    _require_keys(
        aggregates,
        required={"subscriber_count", "published_video_count", "window_views", "window_watch_seconds"},
    )
    safe_aggregates = {
        "subscriber_count": _safe_int(aggregates["subscriber_count"], "subscriber_count"),
        "published_video_count": _safe_int(
            aggregates["published_video_count"], "published_video_count"
        ),
        "window_views": _safe_int(aggregates["window_views"], "window_views"),
        "window_watch_seconds": _safe_int(
            aggregates["window_watch_seconds"], "window_watch_seconds"
        ),
    }
    source_scope_digest = _digest(spec["source_scope_digest"], "source_scope_digest")
    packet = {
        "schema": MEDIA_KIT_SCHEMA,
        "creator_id": creator_id,
        "generated_at": generated_at,
        "window_start": start,
        "window_end": end,
        "channel_name": channel_name,
        "categories": categories,
        "aggregates": safe_aggregates,
        "source_scope_digest": source_scope_digest,
        "evidence_scope": "AGGREGATE_SNAPSHOT_INTEGRITY_ONLY",
        "viewer_level_data_present": False,
        "source_authenticity_proven": False,
        "source_completeness_proven": False,
        "authority": _authority(),
    }
    return _seal(packet)


def verify_media_kit(packet: Mapping[str, Any]) -> bool:
    _verify_seal(packet)
    _require_keys(
        packet,
        required={
            "schema",
            "creator_id",
            "generated_at",
            "window_start",
            "window_end",
            "channel_name",
            "categories",
            "aggregates",
            "source_scope_digest",
            "evidence_scope",
            "viewer_level_data_present",
            "source_authenticity_proven",
            "source_completeness_proven",
            "authority",
            "receipt_sha256",
        },
    )
    if packet["schema"] != MEDIA_KIT_SCHEMA:
        raise SponsorMarketError("media_kit_schema_invalid")
    if packet["evidence_scope"] != "AGGREGATE_SNAPSHOT_INTEGRITY_ONLY":
        raise SponsorMarketError("media_kit_scope_invalid")
    if packet["viewer_level_data_present"] is not False:
        raise SponsorMarketError("viewer_data_not_allowed")
    if packet["source_authenticity_proven"] is not False or packet["source_completeness_proven"] is not False:
        raise SponsorMarketError("media_kit_authority_escalation")
    if packet["authority"] != AUTHORITY_CEILING:
        raise SponsorMarketError("media_kit_authority_invalid")
    rebuilt = compile_media_kit(
        {
            "creator_id": packet["creator_id"],
            "generated_at": packet["generated_at"],
            "window_start": packet["window_start"],
            "window_end": packet["window_end"],
            "channel_name": packet["channel_name"],
            "categories": packet["categories"],
            "aggregates": packet["aggregates"],
            "source_scope_digest": packet["source_scope_digest"],
        }
    )
    if rebuilt != dict(packet):
        raise SponsorMarketError("media_kit_noncanonical")
    return True


def _package_map(inventory: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    return {item["package_id"]: item for item in inventory["packages"]}


def build_proposal(
    inventory: Mapping[str, Any],
    media_kit: Mapping[str, Any],
    request: Mapping[str, Any],
) -> dict[str, Any]:
    """Create a deterministic draft sponsorship proposal from exact sealed inputs."""
    verify_inventory(inventory)
    verify_media_kit(media_kit)
    if inventory["creator_id"] != media_kit["creator_id"]:
        raise SponsorMarketError("creator_mismatch")
    _require_keys(
        request,
        required={
            "proposal_id",
            "sponsor_ref",
            "sponsor_category",
            "created_at",
            "valid_until",
            "selections",
        },
    )
    proposal_id = _identifier(request["proposal_id"], "proposal_id")
    sponsor_ref = _sponsor_ref(request["sponsor_ref"])
    sponsor_category = _identifier(request["sponsor_category"], "sponsor_category")
    created_at = request["created_at"]
    valid_until = request["valid_until"]
    created_dt = _timestamp(created_at, "created_at")
    valid_dt = _timestamp(valid_until, "valid_until")
    inventory_dt = _timestamp(inventory["issued_at"], "issued_at")
    if created_dt < inventory_dt or valid_dt <= created_dt:
        raise SponsorMarketError("proposal_time_invalid")

    selections_raw = request["selections"]
    if not isinstance(selections_raw, list) or not selections_raw or len(selections_raw) > MAX_ITEMS:
        raise SponsorMarketError("selections_invalid")
    packages = _package_map(inventory)
    selections: list[dict[str, Any]] = []
    seen: set[str] = set()
    total_minor = 0
    for raw in selections_raw:
        _require_keys(raw, required={"package_id", "quantity"})
        package_id = _identifier(raw["package_id"], "package_id")
        if package_id in seen:
            raise SponsorMarketError("selection_duplicate")
        seen.add(package_id)
        package = packages.get(package_id)
        if package is None:
            raise SponsorMarketError("selection_unknown_package")
        quantity = _safe_int(raw["quantity"], "quantity", minimum=1, maximum=100_000)
        if quantity > package["slots"]:
            raise SponsorMarketError("selection_exceeds_package_slots")
        if created_dt >= _timestamp(package["window_end"], "window_end"):
            raise SponsorMarketError("selection_package_expired")
        allowed = package["allowed_sponsor_categories"]
        blocked = package["blocked_sponsor_categories"]
        if sponsor_category in blocked or (allowed and sponsor_category not in allowed):
            raise SponsorMarketError("sponsor_category_not_allowed")
        line_total = package["rate_minor"] * quantity
        if line_total > MAX_SAFE_INT or total_minor + line_total > MAX_SAFE_INT:
            raise SponsorMarketError("proposal_total_overflow")
        total_minor += line_total
        selections.append(
            {
                "package_id": package_id,
                "placement": package["placement"],
                "quantity": quantity,
                "unit_rate_minor": package["rate_minor"],
                "line_total_minor": line_total,
                "window_start": package["window_start"],
                "window_end": package["window_end"],
            }
        )
    selections.sort(key=lambda item: item["package_id"])
    packet = {
        "schema": PROPOSAL_SCHEMA,
        "proposal_id": proposal_id,
        "creator_id": inventory["creator_id"],
        "sponsor_ref": sponsor_ref,
        "sponsor_category": sponsor_category,
        "created_at": created_at,
        "valid_until": valid_until,
        "currency": inventory["currency"],
        "inventory_generation": inventory["generation"],
        "inventory_receipt_sha256": inventory["receipt_sha256"],
        "media_kit_receipt_sha256": media_kit["receipt_sha256"],
        "selections": selections,
        "total_minor": total_minor,
        "state": "DRAFT",
        "owner_approval_is_internal_only": True,
        "sponsor_acceptance_proven": False,
        "payment_proven": False,
        "authority": _authority(),
    }
    return _seal(packet)


def verify_proposal(
    proposal: Mapping[str, Any],
    inventory: Mapping[str, Any],
    media_kit: Mapping[str, Any],
) -> bool:
    _verify_seal(proposal)
    _require_keys(
        proposal,
        required={
            "schema",
            "proposal_id",
            "creator_id",
            "sponsor_ref",
            "sponsor_category",
            "created_at",
            "valid_until",
            "currency",
            "inventory_generation",
            "inventory_receipt_sha256",
            "media_kit_receipt_sha256",
            "selections",
            "total_minor",
            "state",
            "owner_approval_is_internal_only",
            "sponsor_acceptance_proven",
            "payment_proven",
            "authority",
            "receipt_sha256",
        },
    )
    if proposal["schema"] != PROPOSAL_SCHEMA or proposal["state"] != "DRAFT":
        raise SponsorMarketError("proposal_schema_or_state_invalid")
    if proposal["owner_approval_is_internal_only"] is not True:
        raise SponsorMarketError("proposal_owner_boundary_invalid")
    if proposal["sponsor_acceptance_proven"] is not False or proposal["payment_proven"] is not False:
        raise SponsorMarketError("proposal_external_authority_escalation")
    if proposal["authority"] != AUTHORITY_CEILING:
        raise SponsorMarketError("proposal_authority_invalid")
    rebuilt = build_proposal(
        inventory,
        media_kit,
        {
            "proposal_id": proposal["proposal_id"],
            "sponsor_ref": proposal["sponsor_ref"],
            "sponsor_category": proposal["sponsor_category"],
            "created_at": proposal["created_at"],
            "valid_until": proposal["valid_until"],
            "selections": [
                {"package_id": item["package_id"], "quantity": item["quantity"]}
                for item in proposal["selections"]
            ],
        },
    )
    if rebuilt != dict(proposal):
        raise SponsorMarketError("proposal_noncanonical_or_stale")
    return True


def transition_proposal(
    proposal: Mapping[str, Any],
    *,
    previous_event: Mapping[str, Any] | None,
    action: str,
    event_id: str,
    occurred_at: str,
    expected_proposal_receipt_sha256: str,
) -> dict[str, Any]:
    """Create an append-only internal lifecycle event.

    This proves only local workflow intent.  OWNER_APPROVED is not sponsor
    acceptance, contract formation, payment, or ad-delivery authority.
    """
    _verify_seal(proposal)
    _digest(expected_proposal_receipt_sha256, "expected_proposal_receipt")
    if proposal["receipt_sha256"] != expected_proposal_receipt_sha256:
        raise SponsorMarketError("proposal_generation_mismatch")
    event_id = _identifier(event_id, "event_id")
    occurred_dt = _timestamp(occurred_at, "occurred_at")
    if occurred_dt < _timestamp(proposal["created_at"], "created_at"):
        raise SponsorMarketError("event_predates_proposal")
    if action not in {"APPROVE", "WITHDRAW"}:
        raise SponsorMarketError("lifecycle_action_invalid")

    prior_state = "DRAFT"
    sequence = 1
    previous_digest: str | None = None
    if previous_event is not None:
        verify_lifecycle_event(previous_event, proposal)
        previous_digest = previous_event["receipt_sha256"]
        prior_state = previous_event["resulting_state"]
        sequence = previous_event["sequence"] + 1
        if occurred_dt < _timestamp(previous_event["occurred_at"], "occurred_at"):
            raise SponsorMarketError("event_time_regression")
    if prior_state == "WITHDRAWN":
        raise SponsorMarketError("withdrawn_terminal")
    if action == "APPROVE":
        if prior_state != "DRAFT":
            raise SponsorMarketError("approval_state_invalid")
        resulting_state = "OWNER_APPROVED"
    else:
        if prior_state not in {"DRAFT", "OWNER_APPROVED"}:
            raise SponsorMarketError("withdraw_state_invalid")
        resulting_state = "WITHDRAWN"

    event = {
        "schema": LIFECYCLE_SCHEMA,
        "event_id": event_id,
        "proposal_id": proposal["proposal_id"],
        "proposal_receipt_sha256": proposal["receipt_sha256"],
        "sequence": sequence,
        "previous_event_receipt_sha256": previous_digest,
        "action": action,
        "occurred_at": occurred_at,
        "prior_state": prior_state,
        "resulting_state": resulting_state,
        "owner_approval_is_internal_only": True,
        "sponsor_acceptance_proven": False,
        "payment_proven": False,
        "authority": _authority(),
    }
    return _seal(event)


def verify_lifecycle_event(event: Mapping[str, Any], proposal: Mapping[str, Any]) -> bool:
    _verify_seal(proposal)
    _verify_seal(event)
    _require_keys(
        event,
        required={
            "schema",
            "event_id",
            "proposal_id",
            "proposal_receipt_sha256",
            "sequence",
            "previous_event_receipt_sha256",
            "action",
            "occurred_at",
            "prior_state",
            "resulting_state",
            "owner_approval_is_internal_only",
            "sponsor_acceptance_proven",
            "payment_proven",
            "authority",
            "receipt_sha256",
        },
    )
    if event["schema"] != LIFECYCLE_SCHEMA:
        raise SponsorMarketError("lifecycle_schema_invalid")
    if event["proposal_id"] != proposal["proposal_id"] or event["proposal_receipt_sha256"] != proposal["receipt_sha256"]:
        raise SponsorMarketError("lifecycle_proposal_mismatch")
    _identifier(event["event_id"], "event_id")
    _safe_int(event["sequence"], "sequence", minimum=1)
    _timestamp(event["occurred_at"], "occurred_at")
    if event["prior_state"] not in PROPOSAL_STATES or event["resulting_state"] not in PROPOSAL_STATES:
        raise SponsorMarketError("lifecycle_state_invalid")
    previous = event["previous_event_receipt_sha256"]
    if previous is not None:
        _digest(previous, "previous_event_receipt")
    if event["owner_approval_is_internal_only"] is not True:
        raise SponsorMarketError("lifecycle_owner_boundary_invalid")
    if event["sponsor_acceptance_proven"] is not False or event["payment_proven"] is not False:
        raise SponsorMarketError("lifecycle_authority_escalation")
    if event["authority"] != AUTHORITY_CEILING:
        raise SponsorMarketError("lifecycle_authority_invalid")
    expected_pairs = {
        ("DRAFT", "APPROVE", "OWNER_APPROVED"),
        ("DRAFT", "WITHDRAW", "WITHDRAWN"),
        ("OWNER_APPROVED", "WITHDRAW", "WITHDRAWN"),
    }
    if (event["prior_state"], event["action"], event["resulting_state"]) not in expected_pairs:
        raise SponsorMarketError("lifecycle_transition_invalid")
    return True


def compile_reservation_book(
    inventory: Mapping[str, Any],
    proposals_and_events: Sequence[Mapping[str, Any]],
    *,
    evaluated_at: str,
) -> dict[str, Any]:
    """Compile capacity used by current owner-approved, non-withdrawn proposals."""
    verify_inventory(inventory)
    eval_dt = _timestamp(evaluated_at, "evaluated_at")
    package_map = _package_map(inventory)
    used = {package_id: 0 for package_id in package_map}
    rows: list[dict[str, Any]] = []
    proposal_ids: set[str] = set()

    if len(proposals_and_events) > MAX_ITEMS:
        raise SponsorMarketError("reservation_input_too_large")
    for raw in proposals_and_events:
        _require_keys(raw, required={"proposal", "events"})
        proposal = raw["proposal"]
        _verify_seal(proposal)
        if proposal["inventory_receipt_sha256"] != inventory["receipt_sha256"]:
            raise SponsorMarketError("reservation_stale_inventory")
        if proposal["creator_id"] != inventory["creator_id"] or proposal["currency"] != inventory["currency"]:
            raise SponsorMarketError("reservation_inventory_mismatch")
        proposal_id = proposal["proposal_id"]
        if proposal_id in proposal_ids:
            raise SponsorMarketError("reservation_duplicate_proposal")
        proposal_ids.add(proposal_id)
        if eval_dt > _timestamp(proposal["valid_until"], "valid_until"):
            state = "EXPIRED"
        else:
            state = "DRAFT"
        events = raw["events"]
        if not isinstance(events, list) or len(events) > MAX_ITEMS:
            raise SponsorMarketError("events_invalid")
        prior_event: Mapping[str, Any] | None = None
        seen_event_ids: set[str] = set()
        seen_receipts: set[str] = set()
        for event in events:
            verify_lifecycle_event(event, proposal)
            if event["event_id"] in seen_event_ids or event["receipt_sha256"] in seen_receipts:
                raise SponsorMarketError("lifecycle_replay")
            seen_event_ids.add(event["event_id"])
            seen_receipts.add(event["receipt_sha256"])
            if prior_event is None:
                if event["sequence"] != 1 or event["previous_event_receipt_sha256"] is not None:
                    raise SponsorMarketError("lifecycle_chain_root_invalid")
            else:
                if event["sequence"] != prior_event["sequence"] + 1:
                    raise SponsorMarketError("lifecycle_sequence_gap")
                if event["previous_event_receipt_sha256"] != prior_event["receipt_sha256"]:
                    raise SponsorMarketError("lifecycle_chain_broken")
                if event["prior_state"] != prior_event["resulting_state"]:
                    raise SponsorMarketError("lifecycle_state_chain_broken")
            if _timestamp(event["occurred_at"], "occurred_at") > eval_dt:
                raise SponsorMarketError("future_lifecycle_event")
            prior_event = event
        if prior_event is not None:
            state = prior_event["resulting_state"] if state != "EXPIRED" else state
        if state == "OWNER_APPROVED":
            for selection in proposal["selections"]:
                package = package_map.get(selection["package_id"])
                if package is None:
                    raise SponsorMarketError("reservation_unknown_package")
                used[selection["package_id"]] += selection["quantity"]
                if used[selection["package_id"]] > package["slots"]:
                    raise SponsorMarketError("reservation_overbooked")
        rows.append(
            {
                "proposal_id": proposal_id,
                "proposal_receipt_sha256": proposal["receipt_sha256"],
                "state": state,
            }
        )

    capacity = []
    for package_id in sorted(package_map):
        package = package_map[package_id]
        capacity.append(
            {
                "package_id": package_id,
                "slots": package["slots"],
                "reserved": used[package_id],
                "remaining": package["slots"] - used[package_id],
            }
        )
    rows.sort(key=lambda item: item["proposal_id"])
    packet = {
        "schema": RESERVATION_SCHEMA,
        "creator_id": inventory["creator_id"],
        "inventory_generation": inventory["generation"],
        "inventory_receipt_sha256": inventory["receipt_sha256"],
        "currency": inventory["currency"],
        "evaluated_at": evaluated_at,
        "proposals": rows,
        "capacity": capacity,
        "authority": _authority(),
    }
    return _seal(packet)


def verify_reservation_book(packet: Mapping[str, Any]) -> bool:
    _verify_seal(packet)
    _require_keys(
        packet,
        required={
            "schema",
            "creator_id",
            "inventory_generation",
            "inventory_receipt_sha256",
            "currency",
            "evaluated_at",
            "proposals",
            "capacity",
            "authority",
            "receipt_sha256",
        },
    )
    if packet["schema"] != RESERVATION_SCHEMA or packet["authority"] != AUTHORITY_CEILING:
        raise SponsorMarketError("reservation_schema_or_authority_invalid")
    _identifier(packet["creator_id"], "creator_id")
    _safe_int(packet["inventory_generation"], "inventory_generation", minimum=1)
    _digest(packet["inventory_receipt_sha256"], "inventory_receipt")
    _currency(packet["currency"])
    _timestamp(packet["evaluated_at"], "evaluated_at")
    if not isinstance(packet["proposals"], list) or not isinstance(packet["capacity"], list):
        raise SponsorMarketError("reservation_lists_invalid")
    return True


def media_kit_markdown(packet: Mapping[str, Any]) -> str:
    verify_media_kit(packet)
    a = packet["aggregates"]
    return (
        f"# {packet['channel_name']} — Sponsor Media Kit\n\n"
        f"Snapshot: `{packet['generated_at']}`  \n"
        f"Window: `{packet['window_start']}` → `{packet['window_end']}`\n\n"
        f"- Subscribers: {a['subscriber_count']}\n"
        f"- Published videos: {a['published_video_count']}\n"
        f"- Window views: {a['window_views']}\n"
        f"- Window watch seconds: {a['window_watch_seconds']}\n"
        f"- Categories: {', '.join(packet['categories'])}\n\n"
        "Evidence scope: aggregate snapshot integrity only. No viewer-level data, "
        "source-authenticity claim, sponsor-contact authority, payment proof, or revenue claim.\n\n"
        f"Receipt SHA-256: `{packet['receipt_sha256']}`\n"
    )


def proposal_markdown(packet: Mapping[str, Any]) -> str:
    _verify_seal(packet)
    lines = [
        f"# Sponsorship Proposal {packet['proposal_id']}",
        "",
        f"Sponsor ref: `{packet['sponsor_ref']}`",
        f"Valid until: `{packet['valid_until']}`",
        f"Currency: `{packet['currency']}`",
        "",
        "| Package | Placement | Qty | Unit minor | Line minor |",
        "|---|---|---:|---:|---:|",
    ]
    for item in packet["selections"]:
        lines.append(
            f"| {item['package_id']} | {item['placement']} | {item['quantity']} | "
            f"{item['unit_rate_minor']} | {item['line_total_minor']} |"
        )
    lines.extend(
        [
            "",
            f"Total minor units: **{packet['total_minor']} {packet['currency']}**",
            "",
            "Status: DRAFT. Internal owner approval does not prove sponsor acceptance, contract, payment, ad delivery, cash, or revenue.",
            "",
            f"Receipt SHA-256: `{packet['receipt_sha256']}`",
            "",
        ]
    )
    return "\n".join(lines)


def verify_any(packet: Mapping[str, Any]) -> bool:
    schema = packet.get("schema") if isinstance(packet, Mapping) else None
    if schema == INVENTORY_SCHEMA:
        return verify_inventory(packet)
    if schema == MEDIA_KIT_SCHEMA:
        return verify_media_kit(packet)
    if schema == RESERVATION_SCHEMA:
        return verify_reservation_book(packet)
    if schema in {PROPOSAL_SCHEMA, LIFECYCLE_SCHEMA}:
        _verify_seal(packet)
        if packet.get("authority") != AUTHORITY_CEILING:
            raise SponsorMarketError("authority_invalid")
        return True
    raise SponsorMarketError("unknown_schema")


def _main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Offline BoTTube sponsorship artifact compiler")
    sub = parser.add_subparsers(dest="command", required=True)

    p_inv = sub.add_parser("inventory")
    p_inv.add_argument("spec")
    p_inv.add_argument("output")

    p_kit = sub.add_parser("media-kit")
    p_kit.add_argument("spec")
    p_kit.add_argument("output_json")
    p_kit.add_argument("output_markdown")

    p_prop = sub.add_parser("proposal")
    p_prop.add_argument("inventory")
    p_prop.add_argument("media_kit")
    p_prop.add_argument("request")
    p_prop.add_argument("output_json")
    p_prop.add_argument("output_markdown")

    p_res = sub.add_parser("reserve")
    p_res.add_argument("inventory")
    p_res.add_argument("portfolio")
    p_res.add_argument("evaluated_at")
    p_res.add_argument("output")

    p_verify = sub.add_parser("verify")
    p_verify.add_argument("artifact")

    args = parser.parse_args(argv)
    try:
        if args.command == "inventory":
            result = compile_inventory(load_json_file(args.spec))
            _write_json_exclusive(args.output, result)
        elif args.command == "media-kit":
            result = compile_media_kit(load_json_file(args.spec))
            _write_json_exclusive(args.output_json, result)
            _write_exclusive(args.output_markdown, media_kit_markdown(result))
        elif args.command == "proposal":
            inventory = load_json_file(args.inventory)
            media_kit = load_json_file(args.media_kit)
            request = load_json_file(args.request)
            result = build_proposal(inventory, media_kit, request)
            _write_json_exclusive(args.output_json, result)
            _write_exclusive(args.output_markdown, proposal_markdown(result))
        elif args.command == "reserve":
            inventory = load_json_file(args.inventory)
            portfolio = load_json_file(args.portfolio)
            if not isinstance(portfolio, list):
                raise SponsorMarketError("portfolio_list_required")
            result = compile_reservation_book(inventory, portfolio, evaluated_at=args.evaluated_at)
            _write_json_exclusive(args.output, result)
        else:
            verify_any(load_json_file(args.artifact))
            print("PASS")
    except SponsorMarketError as exc:
        print(f"HOLD:{exc}")
        return 2
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main())
