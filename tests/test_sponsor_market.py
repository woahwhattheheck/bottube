import copy
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from sponsor_market import (
    AUTHORITY_CEILING,
    SponsorMarketError,
    build_proposal,
    compile_inventory,
    compile_media_kit,
    compile_reservation_book,
    loads_strict,
    media_kit_markdown,
    proposal_markdown,
    transition_proposal,
    verify_inventory,
    verify_lifecycle_event,
    verify_media_kit,
    verify_proposal,
    verify_reservation_book,
)


def inventory_spec(generation=3, slots=2):
    return {
        "creator_id": "creator_alpha",
        "generation": generation,
        "issued_at": "2026-09-13T14:00:00Z",
        "currency": "USD",
        "packages": [
            {
                "package_id": "pre-roll-30",
                "title": "30 second pre-roll",
                "placement": "PRE_ROLL",
                "rate_minor": 25000,
                "slots": slots,
                "window_start": "2026-09-14T00:00:00Z",
                "window_end": "2026-10-14T00:00:00Z",
                "allowed_sponsor_categories": ["developer_tools", "hardware"],
                "blocked_sponsor_categories": ["gambling"],
            },
            {
                "package_id": "description-link",
                "title": "Description placement",
                "placement": "DESCRIPTION",
                "rate_minor": 10000,
                "slots": 4,
                "window_start": "2026-09-14T00:00:00Z",
                "window_end": "2026-10-14T00:00:00Z",
                "allowed_sponsor_categories": [],
                "blocked_sponsor_categories": ["gambling"],
            },
        ],
    }


def media_spec():
    return {
        "creator_id": "creator_alpha",
        "generated_at": "2026-09-13T14:00:00Z",
        "window_start": "2026-08-14T00:00:00Z",
        "window_end": "2026-09-13T00:00:00Z",
        "channel_name": "Agent Systems Lab",
        "categories": ["ai", "software"],
        "aggregates": {
            "subscriber_count": 12000,
            "published_video_count": 24,
            "window_views": 543210,
            "window_watch_seconds": 9876543,
        },
        "source_scope_digest": hashlib.sha256(b"creator_alpha:all-public-videos:g3").hexdigest(),
    }


def request(proposal_id="offer-a", quantity=1):
    return {
        "proposal_id": proposal_id,
        "sponsor_ref": "spn_AcmeDev1",
        "sponsor_category": "developer_tools",
        "created_at": "2026-09-13T15:00:00Z",
        "valid_until": "2026-09-20T15:00:00Z",
        "selections": [
            {"package_id": "pre-roll-30", "quantity": quantity},
            {"package_id": "description-link", "quantity": 1},
        ],
    }


def compiled():
    inv = compile_inventory(inventory_spec())
    kit = compile_media_kit(media_spec())
    proposal = build_proposal(inv, kit, request())
    return inv, kit, proposal


def test_inventory_is_deterministic_and_canonical():
    a = compile_inventory(inventory_spec())
    b_spec = inventory_spec()
    b_spec["packages"] = list(reversed(b_spec["packages"]))
    b = compile_inventory(b_spec)
    assert a == b
    assert verify_inventory(a)
    assert a["authority"] == AUTHORITY_CEILING


def test_inventory_rejects_currency_mix_aliases_and_bool_int():
    spec = inventory_spec()
    spec["currency"] = "usd"
    with pytest.raises(SponsorMarketError, match="currency_invalid"):
        compile_inventory(spec)
    spec = inventory_spec()
    spec["packages"][0]["rate_minor"] = True
    with pytest.raises(SponsorMarketError, match="rate_minor_int_required"):
        compile_inventory(spec)


def test_inventory_rejects_conflicting_category_policy_and_bad_window():
    spec = inventory_spec()
    spec["packages"][0]["blocked_sponsor_categories"] = ["developer_tools"]
    with pytest.raises(SponsorMarketError, match="policy_conflict"):
        compile_inventory(spec)
    spec = inventory_spec()
    spec["packages"][0]["window_end"] = spec["packages"][0]["window_start"]
    with pytest.raises(SponsorMarketError, match="package_window_invalid"):
        compile_inventory(spec)


def test_media_kit_is_aggregate_only_and_no_pii_or_secrets():
    kit = compile_media_kit(media_spec())
    assert verify_media_kit(kit)
    assert kit["viewer_level_data_present"] is False
    assert kit["source_authenticity_proven"] is False
    bad = media_spec()
    bad["channel_name"] = "reach me creator@example.com"
    with pytest.raises(SponsorMarketError, match="pii_shaped"):
        compile_media_kit(bad)
    bad = media_spec()
    bad["categories"] = ["api_key=supersecret123"]
    with pytest.raises(SponsorMarketError, match="secret_shaped"):
        compile_media_kit(bad)


def test_media_kit_rejects_future_window_and_bool_metric():
    bad = media_spec()
    bad["generated_at"] = "2026-09-12T00:00:00Z"
    with pytest.raises(SponsorMarketError, match="media_window_invalid"):
        compile_media_kit(bad)
    bad = media_spec()
    bad["aggregates"]["window_views"] = False
    with pytest.raises(SponsorMarketError, match="window_views_int_required"):
        compile_media_kit(bad)


def test_proposal_binds_exact_inventory_and_media_kit_and_math():
    inv, kit, proposal = compiled()
    assert verify_proposal(proposal, inv, kit)
    assert proposal["total_minor"] == 35000
    assert proposal["currency"] == "USD"
    assert proposal["state"] == "DRAFT"
    assert proposal["sponsor_acceptance_proven"] is False
    assert proposal["payment_proven"] is False


def test_proposal_rejects_category_and_capacity_violation():
    inv = compile_inventory(inventory_spec(slots=1))
    kit = compile_media_kit(media_spec())
    with pytest.raises(SponsorMarketError, match="exceeds_package_slots"):
        build_proposal(inv, kit, request(quantity=2))
    bad = request()
    bad["sponsor_category"] = "gambling"
    with pytest.raises(SponsorMarketError, match="not_allowed"):
        build_proposal(inv, kit, bad)


def test_proposal_rejects_same_id_inventory_mutation_even_if_resealed():
    inv, kit, proposal = compiled()
    changed = inventory_spec(generation=3)
    changed["packages"][0]["rate_minor"] = 26000
    mutated_inv = compile_inventory(changed)
    with pytest.raises(SponsorMarketError, match="noncanonical_or_stale"):
        verify_proposal(proposal, mutated_inv, kit)
    assert inv["generation"] == mutated_inv["generation"]
    assert inv["receipt_sha256"] != mutated_inv["receipt_sha256"]


def test_proposal_rejects_cross_creator_media_kit():
    inv = compile_inventory(inventory_spec())
    ms = media_spec()
    ms["creator_id"] = "creator_beta"
    kit = compile_media_kit(ms)
    with pytest.raises(SponsorMarketError, match="creator_mismatch"):
        build_proposal(inv, kit, request())


def test_tamper_and_reseal_external_authority_cannot_verify():
    inv, kit, proposal = compiled()
    forged = dict(proposal)
    forged["payment_proven"] = True
    unsigned = dict(forged)
    unsigned.pop("receipt_sha256")
    forged["receipt_sha256"] = hashlib.sha256(
        json.dumps(unsigned, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()
    with pytest.raises(SponsorMarketError, match="external_authority_escalation"):
        verify_proposal(forged, inv, kit)


def test_owner_approval_and_withdrawal_chain():
    _, _, proposal = compiled()
    approve = transition_proposal(
        proposal,
        previous_event=None,
        action="APPROVE",
        event_id="approve-1",
        occurred_at="2026-09-13T16:00:00Z",
        expected_proposal_receipt_sha256=proposal["receipt_sha256"],
    )
    assert verify_lifecycle_event(approve, proposal)
    assert approve["resulting_state"] == "OWNER_APPROVED"
    withdraw = transition_proposal(
        proposal,
        previous_event=approve,
        action="WITHDRAW",
        event_id="withdraw-2",
        occurred_at="2026-09-13T17:00:00Z",
        expected_proposal_receipt_sha256=proposal["receipt_sha256"],
    )
    assert withdraw["previous_event_receipt_sha256"] == approve["receipt_sha256"]
    assert withdraw["resulting_state"] == "WITHDRAWN"


def test_lifecycle_generation_fence_and_terminal_withdrawal():
    _, _, proposal = compiled()
    with pytest.raises(SponsorMarketError, match="generation_mismatch"):
        transition_proposal(
            proposal,
            previous_event=None,
            action="APPROVE",
            event_id="approve-1",
            occurred_at="2026-09-13T16:00:00Z",
            expected_proposal_receipt_sha256="0" * 64,
        )
    first = transition_proposal(
        proposal,
        previous_event=None,
        action="WITHDRAW",
        event_id="withdraw-1",
        occurred_at="2026-09-13T16:00:00Z",
        expected_proposal_receipt_sha256=proposal["receipt_sha256"],
    )
    with pytest.raises(SponsorMarketError, match="withdrawn_terminal"):
        transition_proposal(
            proposal,
            previous_event=first,
            action="APPROVE",
            event_id="approve-2",
            occurred_at="2026-09-13T17:00:00Z",
            expected_proposal_receipt_sha256=proposal["receipt_sha256"],
        )


def test_reservation_book_counts_only_current_owner_approved_proposals():
    inv = compile_inventory(inventory_spec(slots=2))
    kit = compile_media_kit(media_spec())
    p1 = build_proposal(inv, kit, request("offer-a", 1))
    p2 = build_proposal(inv, kit, request("offer-b", 1))
    a1 = transition_proposal(
        p1,
        previous_event=None,
        action="APPROVE",
        event_id="approve-a",
        occurred_at="2026-09-13T16:00:00Z",
        expected_proposal_receipt_sha256=p1["receipt_sha256"],
    )
    a2 = transition_proposal(
        p2,
        previous_event=None,
        action="APPROVE",
        event_id="approve-b",
        occurred_at="2026-09-13T16:05:00Z",
        expected_proposal_receipt_sha256=p2["receipt_sha256"],
    )
    book = compile_reservation_book(
        inv,
        [{"proposal": p1, "events": [a1]}, {"proposal": p2, "events": [a2]}],
        evaluated_at="2026-09-13T17:00:00Z",
    )
    assert verify_reservation_book(book)
    cap = {row["package_id"]: row for row in book["capacity"]}
    assert cap["pre-roll-30"]["reserved"] == 2
    assert cap["pre-roll-30"]["remaining"] == 0


def test_reservation_book_fails_closed_on_overbooking():
    inv = compile_inventory(inventory_spec(slots=1))
    kit = compile_media_kit(media_spec())
    rows = []
    for proposal_id in ("offer-a", "offer-b"):
        p = build_proposal(inv, kit, request(proposal_id, 1))
        e = transition_proposal(
            p,
            previous_event=None,
            action="APPROVE",
            event_id=f"approve-{proposal_id}",
            occurred_at="2026-09-13T16:00:00Z",
            expected_proposal_receipt_sha256=p["receipt_sha256"],
        )
        rows.append({"proposal": p, "events": [e]})
    with pytest.raises(SponsorMarketError, match="reservation_overbooked"):
        compile_reservation_book(inv, rows, evaluated_at="2026-09-13T17:00:00Z")


def test_withdrawn_and_expired_proposals_release_capacity():
    inv = compile_inventory(inventory_spec(slots=1))
    kit = compile_media_kit(media_spec())
    p = build_proposal(inv, kit, request("offer-a", 1))
    a = transition_proposal(
        p,
        previous_event=None,
        action="APPROVE",
        event_id="approve-a",
        occurred_at="2026-09-13T16:00:00Z",
        expected_proposal_receipt_sha256=p["receipt_sha256"],
    )
    w = transition_proposal(
        p,
        previous_event=a,
        action="WITHDRAW",
        event_id="withdraw-a",
        occurred_at="2026-09-13T17:00:00Z",
        expected_proposal_receipt_sha256=p["receipt_sha256"],
    )
    book = compile_reservation_book(inv, [{"proposal": p, "events": [a, w]}], evaluated_at="2026-09-13T18:00:00Z")
    assert book["capacity"][1]["reserved"] == 0 or book["capacity"][0]["reserved"] == 0
    expired = compile_reservation_book(inv, [{"proposal": p, "events": [a]}], evaluated_at="2026-09-21T16:00:00Z")
    assert all(row["reserved"] == 0 for row in expired["capacity"])


def test_reservation_rejects_stale_inventory_generation():
    inv1 = compile_inventory(inventory_spec(generation=3))
    kit = compile_media_kit(media_spec())
    p = build_proposal(inv1, kit, request())
    a = transition_proposal(
        p,
        previous_event=None,
        action="APPROVE",
        event_id="approve-a",
        occurred_at="2026-09-13T16:00:00Z",
        expected_proposal_receipt_sha256=p["receipt_sha256"],
    )
    inv2 = compile_inventory(inventory_spec(generation=4))
    with pytest.raises(SponsorMarketError, match="stale_inventory"):
        compile_reservation_book(inv2, [{"proposal": p, "events": [a]}], evaluated_at="2026-09-13T17:00:00Z")


def test_reservation_rejects_event_chain_gap_and_future_event():
    inv, kit, p = compiled()
    a = transition_proposal(
        p,
        previous_event=None,
        action="APPROVE",
        event_id="approve-a",
        occurred_at="2026-09-13T18:00:00Z",
        expected_proposal_receipt_sha256=p["receipt_sha256"],
    )
    with pytest.raises(SponsorMarketError, match="future_lifecycle_event"):
        compile_reservation_book(inv, [{"proposal": p, "events": [a]}], evaluated_at="2026-09-13T17:00:00Z")
    broken = dict(a)
    broken["sequence"] = 2
    unsigned = dict(broken)
    unsigned.pop("receipt_sha256")
    broken["receipt_sha256"] = hashlib.sha256(
        json.dumps(unsigned, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()
    with pytest.raises(SponsorMarketError, match="chain_root_invalid"):
        compile_reservation_book(inv, [{"proposal": p, "events": [broken]}], evaluated_at="2026-09-13T19:00:00Z")


def test_strict_json_duplicate_and_nonfinite_rejection():
    with pytest.raises(SponsorMarketError, match="duplicate_json_key"):
        loads_strict('{"a":1,"a":2}')
    with pytest.raises(SponsorMarketError, match="non_finite_json"):
        loads_strict('{"a":NaN}')


def test_markdown_has_receipts_and_explicit_authority_ceiling():
    _, kit, proposal = compiled()
    kit_md = media_kit_markdown(kit)
    proposal_md = proposal_markdown(proposal)
    assert kit["receipt_sha256"] in kit_md
    assert "No viewer-level data" in kit_md
    assert proposal["receipt_sha256"] in proposal_md
    assert "does not prove sponsor acceptance" in proposal_md


def test_cli_create_exclusive_and_verify(tmp_path):
    root = Path(__file__).resolve().parents[1]
    spec = tmp_path / "inv.json"
    out = tmp_path / "out.json"
    spec.write_text(json.dumps(inventory_spec()), encoding="utf-8")
    cmd = [sys.executable, str(root / "sponsor_market.py"), "inventory", str(spec), str(out)]
    first = subprocess.run(cmd, cwd=root, capture_output=True, text=True, check=False)
    assert first.returncode == 0, first.stdout + first.stderr
    second = subprocess.run(cmd, cwd=root, capture_output=True, text=True, check=False)
    assert second.returncode == 2
    assert "output_exists" in second.stdout
    verify = subprocess.run(
        [sys.executable, str(root / "sponsor_market.py"), "verify", str(out)],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert verify.returncode == 0
    assert verify.stdout.strip() == "PASS"


def test_cli_rejects_symlink_input_when_supported(tmp_path):
    if not hasattr(os, "O_NOFOLLOW"):
        pytest.skip("platform lacks O_NOFOLLOW")
    root = Path(__file__).resolve().parents[1]
    real = tmp_path / "real.json"
    link = tmp_path / "link.json"
    out = tmp_path / "out.json"
    real.write_text(json.dumps(inventory_spec()), encoding="utf-8")
    link.symlink_to(real)
    run = subprocess.run(
        [sys.executable, str(root / "sponsor_market.py"), "inventory", str(link), str(out)],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert run.returncode == 2
    assert "input_open_failed" in run.stdout


def test_input_mutation_and_unknown_fields_fail_closed():
    spec = inventory_spec()
    spec["surprise"] = "nope"
    with pytest.raises(SponsorMarketError, match="unknown_fields"):
        compile_inventory(spec)
    inv, kit, proposal = compiled()
    forged = copy.deepcopy(proposal)
    forged["selections"][0]["quantity"] = 2
    with pytest.raises(SponsorMarketError, match="receipt_mismatch"):
        verify_proposal(forged, inv, kit)
