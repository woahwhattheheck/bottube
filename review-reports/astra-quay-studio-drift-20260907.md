# ASTRA-QUAY: Studio deployment-drift inventory repair

Operation ID: `astra-quay-bottube-studio-drift-pr-20260907`

Status: **implementation pushed and focused validation passed; upstream publication pending**.

## Published change

- Upstream target: `Scottcjn/bottube:main`.
- Fork branch: `woahwhattheheck/bottube:fix/astra-quay-studio-drift-20260907`.
- Base: `7fe70c398275eedcbe09dc9a07be30a5d84ff14c`.
- Head: `38a4c2725fc5cf681cf107dfd6fa08f0b734d89f`.
- [Exact four-file comparison](https://github.com/woahwhattheheck/bottube/compare/7fe70c398275eedcbe09dc9a07be30a5d84ff14c...38a4c2725fc5cf681cf107dfd6fa08f0b734d89f): both deployment-drift JSON policies, two count assertions in the existing sentinel test, and four new regression cases in `tests/test_deployment_drift_studio.py`.

The source inventory omitted `studio_blueprint.py` although OpenAPI documents its existing `POST /api/studio/generate` declaration. The extractor reads AST declarations without importing application modules. This repair does not establish runtime registration or production availability.

No allowances, production routes, live-probe policy, SDK files, or upstream workflows change. PR2207's SDK contribution and ASTRA-JUNCTION's hosted SDK validation remain credited to their existing contributors. This report and the diagnostic workflow are NOT in the four-file fix branch.

## Verified execution

[Final Python 3.11.16 job and full logs](https://github.com/woahwhattheheck/bottube/actions/runs/34152787252/job/101838344652), completed September 7, 2026:

- Exact candidate checkout: `38a4c2725fc5cf681cf107dfd6fa08f0b734d89f`.
- `git diff --check` and both changed test files' `py_compile`: passed.
- Both offline policies: PASS, exit 0. Each reports 26 OpenAPI operations, 353 declared application operations, 934 effective operations, 19 unchanged known missing-code allowances, zero blocking drift and zero stale allowances. Policy canaries remain 0 and 14 respectively. Live probing is disabled.
- Focused suite: **43 passed in 3.28 seconds**.
- Baseline control: restore the two original configs and original sentinel test byte-for-byte from base `7fe70c39`, retaining only the added regression file. The suite reproduces **exactly 4 expected failures and 39 passes**. The workflow asserts the four failure names and excludes skipped/error cases.
- Candidate restoration: clean `git diff --exit-code`, followed by **43 passed in 3.30 seconds**.

This is 43 distinct focused cases, not 86 distinct tests or a whole-project test run. The second candidate pass verifies restoration after the baseline control. Python 3.13 is additional coverage in the same workflow and was still queued at the latest check; no result is claimed for it here.

Earlier evidence is preserved, not relabeled:
- [Original merge-ref diagnostic](https://github.com/woahwhattheheck/bottube/actions/runs/34152075013/job/101836253064): merge `31ae73f2` had 2 failures / 37 passes and both offline reports identified only the Studio POST as blocking missing code. Diagnostic continue-on-error success was not a passing-suite claim.
- [Initial source-fix candidate](https://github.com/woahwhattheheck/bottube/actions/runs/34152436162/job/101837311474): 1 failure / 42 passes. The new cases and live-only test passed; the remaining failure exposed the stale 24-operation assertion. The final follow-up commit changes exactly the two inventory snapshots.

## Publication state and duplicate prevention

Upstream draft PR creation through this installed integration returned `403 Resource not accessible by integration`; that attempt created no PR. Fork writes succeeded. This isolated runtime has no `gh` executable or GitHub token environment variable. ASTRA-LANTERN accepted a publication-only check through its available route. No duplicate PR creation should race that scope.

Before publishing, search for a matching upstream PR by exact fork branch and reuse it if present. Keep this operation ID, head, existing attribution and observed validation limits. Do not edit PR2207's branch. No live probes, generation/billing calls, bounty claims or payment requests are part of this operation. No renewed owner approval is required.

## Prepared PR

Title: **[ASTRA-QUAY] Include Studio source in deployment drift inventories**

Both deployment-drift policies inventory only `bottube_server.py`, so the existing `POST /api/studio/generate` declaration in `studio_blueprint.py` is reported as missing code. Add the Studio source to both inventories, refresh two stale inventory-count snapshots, and add four regression cases covering source inclusion and the omitted-source failure control.

The change preserves all drift allowances, live-probe settings, existing gates and SDK files. It inventories source declarations; it does not claim the blueprint is mounted or live in production. This is separate from the SDK contribution in #2207.

Base: `7fe70c398275eedcbe09dc9a07be30a5d84ff14c`. Head: `38a4c2725fc5cf681cf107dfd6fa08f0b734d89f`.

Validation on Python 3.11.16: 43 focused cases pass; both offline policies return PASS/0; restoring baseline files reproduces exactly four expected failures and 39 passes; restoring the candidate yields a clean worktree and 43 passes again. [Full hosted evidence](https://github.com/woahwhattheheck/bottube/actions/runs/34152787252/job/101838344652). No full-project CI or live endpoint claim.

```sh
python -m pip install pytest==9.1.1 PyYAML==6.0.3
python -m pytest tests/test_deployment_drift.py tests/test_deployment_drift_studio.py -q
python deployment_drift.py --format text
python deployment_drift.py --config deployment-drift.issue-1410.example.json --format text
```

AI-assisted contribution by ASTRA-QUAY, operated by `woahwhattheheck`.
