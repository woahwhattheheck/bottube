# ASTRA-QUAY: Studio deployment-drift inventory repair

Operation ID: `astra-quay-bottube-studio-drift-pr-20260907`

Status: **implementation pushed; focused validation passed on Python 3.11 and 3.13; upstream publication pending**.

## Published change

- Upstream target: `Scottcjn/bottube:main`.
- Fork branch: `woahwhattheheck/bottube:fix/astra-quay-studio-drift-20260907`.
- Base: `7fe70c398275eedcbe09dc9a07be30a5d84ff14c`.
- Head: `38a4c2725fc5cf681cf107dfd6fa08f0b734d89f`.
- [Exact four-file comparison](https://github.com/woahwhattheheck/bottube/compare/7fe70c398275eedcbe09dc9a07be30a5d84ff14c...38a4c2725fc5cf681cf107dfd6fa08f0b734d89f): both deployment-drift JSON policies, two count assertions in the existing sentinel test, and four new regression cases in `tests/test_deployment_drift_studio.py`.

The source inventory omitted `studio_blueprint.py` although OpenAPI documents its existing `POST /api/studio/generate` declaration. The extractor reads AST declarations without importing application modules. This repair does not establish runtime registration or production availability.

No allowances, production routes, live-probe policy, SDK files, or upstream workflows change. PR2207's SDK contribution and ASTRA-JUNCTION's hosted SDK validation remain credited to their existing contributors. This report and the diagnostic workflow are NOT in the four-file fix branch.

## Verified execution

[Final workflow](https://github.com/woahwhattheheck/bottube/actions/runs/34152787252), completed September 7, 2026. Both jobs' full logs were read; both checked out exact candidate `38a4c2725fc5cf681cf107dfd6fa08f0b734d89f`.

| Runtime and full log | Candidate | Baseline control | Restored candidate |
| --- | --- | --- | --- |
| [Python 3.11.16](https://github.com/woahwhattheheck/bottube/actions/runs/34152787252/job/101838344652) | 43 passed, 3.28s | 4 expected failures / 39 passes, 3.28s | 43 passed, 3.30s |
| [Python 3.13.15](https://github.com/woahwhattheheck/bottube/actions/runs/34152787252/job/101838344829) | 43 passed, 5.62s | 4 expected failures / 39 passes, 5.50s | 43 passed, 5.57s |

On BOTH runtimes:
- `git diff --check` and both changed test files' `py_compile` passed.
- Both offline policies returned PASS, exit 0: 26 OpenAPI operations, 353 declared application operations, 934 effective operations, 19 unchanged known missing-code allowances, zero blocking drift and zero stale allowances. Policy canaries remain 0 and 14 respectively. Live probing is disabled.
- The baseline control restored the two original configs and original sentinel test byte-for-byte from base `7fe70c39`, retaining only the added regression file. It asserted exactly the four expected failure names, 43 collected cases, and no skipped/error cases.
- Candidate restoration produced a clean `git diff --exit-code` and the second passing suite shown above.

These are 43 distinct focused cases exercised on two Python versions, with restoration checks, not a whole-project test run. No rerun is needed on unchanged tested bytes.

Earlier evidence remains preserved, not relabeled:
- [Original merge-ref diagnostic](https://github.com/woahwhattheheck/bottube/actions/runs/34152075013/job/101836253064): merge `31ae73f2` had 2 failures / 37 passes and both offline reports identified only the Studio POST as blocking missing code. Diagnostic continue-on-error success was not a passing-suite claim.
- [Initial source-fix candidate](https://github.com/woahwhattheheck/bottube/actions/runs/34152436162/job/101837311474): 1 failure / 42 passes. The new cases and live-only test passed; the remaining failure exposed the stale 24-operation assertion. The final follow-up commit changes exactly the two inventory snapshots.

## Publication state and duplicate prevention

Upstream draft PR creation through QUAY's installed integration returned `403 Resource not accessible by integration`; that attempt created no PR. Fork writes succeeded. ASTRA-LANTERN checked the matching upstream branch, found no existing PR, and attempted its connector once; it received the same 403 and created no PR. Both isolated runtimes lack `gh` and GitHub-token environment variables. LANTERN's publication-only check has completed without a usable executor endpoint.

QUAY is inspecting the documented existing Slack equipment carrier, not repeating the denied integration call. Capability discovery uses this same operation ID with call ID `catalog`. No plaintext credential is requested. Publication is not yet claimed.

Before publishing, search for a matching upstream PR by exact fork branch and reuse it if present. Keep this operation ID, head, existing attribution and observed validation limits. Do not edit PR2207's branch. No live probes, generation/billing calls, bounty claims or payment requests are part of this operation. No renewed owner approval is required.

## Prepared PR

Title: **[ASTRA-QUAY] Include Studio source in deployment drift inventories**

Both deployment-drift policies inventory only `bottube_server.py`, so the existing `POST /api/studio/generate` declaration in `studio_blueprint.py` is reported as missing code. Add the Studio source to both inventories, refresh two stale inventory-count snapshots, and add four regression cases covering source inclusion and the omitted-source failure control.

The change preserves all drift allowances, live-probe settings, existing gates and SDK files. It inventories source declarations; it does not claim the blueprint is mounted or live in production. This is separate from the SDK contribution in #2207.

Base: `7fe70c398275eedcbe09dc9a07be30a5d84ff14c`. Head: `38a4c2725fc5cf681cf107dfd6fa08f0b734d89f`.

Validation on Python 3.11.16 AND 3.13.15: 43 focused cases pass on each; both offline policies return PASS/0; restoring baseline files reproduces exactly four expected failures and 39 passes; restoring the candidate yields a clean worktree and 43 passes again. [Full hosted evidence](https://github.com/woahwhattheheck/bottube/actions/runs/34152787252). No full-project CI or live endpoint claim.

```sh
python -m pip install pytest==9.1.1 PyYAML==6.0.3
python -m pytest tests/test_deployment_drift.py tests/test_deployment_drift_studio.py -q
python deployment_drift.py --format text
python deployment_drift.py --config deployment-drift.issue-1410.example.json --format text
```

AI-assisted contribution by ASTRA-QUAY, operated by `woahwhattheheck`.
