import hashlib
import json

import pytest

from sponsor_market import (
    SponsorMarketError,
    build_proposal,
    compile_inventory,
    compile_media_kit,
    transition_proposal,
    verify_any,
)
from test_sponsor_market import inventory_spec, media_spec, request


def _rehash(packet):
    unsigned = dict(packet)
    unsigned.pop("receipt_sha256")
    packet["receipt_sha256"] = hashlib.sha256(
        json.dumps(unsigned, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


def test_standalone_verify_rejects_rehashed_external_authority_escalation():
    inventory = compile_inventory(inventory_spec())
    kit = compile_media_kit(media_spec())
    proposal = build_proposal(inventory, kit, request())

    forged = dict(proposal)
    forged["payment_proven"] = True
    _rehash(forged)
    with pytest.raises(SponsorMarketError, match="external_authority_escalation"):
        verify_any(forged)

    approve = transition_proposal(
        proposal,
        previous_event=None,
        action="APPROVE",
        event_id="approve-standalone",
        occurred_at="2026-09-13T16:00:00Z",
        expected_proposal_receipt_sha256=proposal["receipt_sha256"],
    )
    forged_event = dict(approve)
    forged_event["sponsor_acceptance_proven"] = True
    _rehash(forged_event)
    with pytest.raises(SponsorMarketError, match="lifecycle_authority_escalation"):
        verify_any(forged_event)
