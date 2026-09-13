# BoTTube Sponsor Market

`Sponsor Market` is an offline creator-commercialization plane for BoTTube. It turns explicit creator sponsorship inventory plus privacy-minimized aggregate channel facts into deterministic media kits and draft sponsor proposals, then gives the creator an internal capacity ledger so two approved proposals cannot silently reserve the same finite slot inventory.

It is intentionally **not** an ad network, checkout, sponsor CRM, payment processor, tracking pixel, or revenue-recognition system.

## Product flow

1. **Inventory** — the creator publishes one exact generation of sponsorship packages. Each package binds placement, integer minor-unit rate, finite slots, availability window, and allowed/blocked sponsor categories. One inventory has exactly one ISO-style three-letter currency; there is no FX or cross-currency arithmetic.
2. **Media kit** — the host/creator supplies aggregate channel facts only: subscriber count, published-video count, window views, and window watch seconds. The packet excludes viewer identities and raw watch histories and labels itself `AGGREGATE_SNAPSHOT_INTEGRITY_ONLY`. The SHA-256 receipt proves only integrity of the supplied snapshot, not source authenticity or completeness.
3. **Proposal** — a draft binds one exact inventory receipt, one exact media-kit receipt, an opaque sponsor reference, sponsor category, exact package quantities, exact unit rates, and computed integer-minor-unit total. Same-ID inventory mutation changes the receipt and invalidates the old proposal.
4. **Lifecycle** — append-only internal `APPROVE` / `WITHDRAW` events use a proposal-generation fence and prior-event receipt chain. `OWNER_APPROVED` means only that the creator reserved internal capacity for that proposal. It does not mean the sponsor accepted anything.
5. **Reservation book** — the compiler replays lifecycle chains against one exact current inventory generation and counts capacity only for current, non-expired `OWNER_APPROVED` proposals. Any overbooking, chain break, stale inventory, future event, replay, or duplicate proposal fails closed.

## Authority ceiling

Every artifact carries the same all-false external authority ceiling. Sponsor Market does **not** authorize or prove:

- sponsor contact or message delivery;
- ad placement or delivery;
- provider/account mutation;
- contract signature or sponsor acceptance;
- payment, refund, or creator payout;
- cash received or recognized revenue;
- viewer profiling.

A proposal is a prepared commercial artifact, not a contract or invoice. A media-kit receipt is a deterministic integrity receipt, not a platform/provider attestation.

## CLI

All JSON ingress is strict UTF-8, duplicate-key rejecting, non-finite-number rejecting, bounded to 2 MiB, and ordinary-file only. Outputs are create-exclusive mode `0600` files and are never overwritten.

```bash
# Compile one inventory generation.
python sponsor_market.py inventory inventory-spec.json inventory.json

# Compile aggregate media-kit JSON + Markdown.
python sponsor_market.py media-kit media-kit-spec.json media-kit.json media-kit.md

# Build deterministic proposal JSON + Markdown.
python sponsor_market.py proposal inventory.json media-kit.json request.json proposal.json proposal.md

# Compile a current internal capacity book from proposal/event bundles.
python sponsor_market.py reserve inventory.json portfolio.json 2026-09-13T18:00:00Z reservations.json

# Integrity/schema verification for standalone artifacts.
python sponsor_market.py verify inventory.json
```

`portfolio.json` is a list of objects shaped as:

```json
[
  {
    "proposal": {"schema": "bottube-sponsor-proposal/v1", "...": "..."},
    "events": [{"schema": "bottube-sponsor-proposal-lifecycle/v1", "...": "..."}]
  }
]
```

## Security and privacy invariants

- strict exact-key schemas reject accidental or attacker-added authority fields;
- Python `bool` cannot alias integer money/count inputs;
- text is bounded and rejects control characters, secret-shaped data, email/phone-shaped public fields, and credential-bearing URLs;
- integer money only, with an explicit safe-integer ceiling and overflow fence;
- proposal price comes only from the exact sealed inventory generation;
- raw sponsor contact data is replaced by an opaque `spn_...` reference;
- aggregate media kits have no viewer-level rows or watch history;
- lifecycle events are proposal-generation-bound and chain-bound;
- reservation compilation rejects stale inventory, duplicate proposals, replayed events, sequence gaps, future events, and overbooking;
- CLI file reads are bounded regular-file reads with `O_NOFOLLOW` where available; outputs are create-exclusive.

## Verification note

`verify` on a standalone proposal/lifecycle packet checks structural receipt integrity and its fixed authority ceiling. Full proposal currency validation requires the exact inventory and media-kit generations and is performed by `verify_proposal()` in the Python API. Full reservation truth requires recompilation from the exact inventory + proposal/event portfolio.
