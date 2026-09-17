# Bug report: syndication run start accepts non-string `run_type`

Bounty context: `Scottcjn/rustchain-bounties#1102` (functional bug report).

Pinned upstream source: `Scottcjn/bottube@6af6b63f7a5a87353a30cd4552dc5c0e183a96af`.

## URL

`POST https://bottube.ai/api/syndication/run/start`

## Steps to reproduce

1. Authenticate with any valid BoTTube `X-API-Key`.
2. Send an otherwise valid JSON object whose required `run_type` field is a truthy non-string value:

```http
POST /api/syndication/run/start
Content-Type: application/json
X-API-Key: <valid key>

{"run_type":["x_crosspost"]}
```

A JSON object value such as `{"run_type":{"kind":"x_crosspost"}}` reaches the same failure class.

## Expected

The route documents `run_type` as a string. Non-string values should be rejected deterministically with HTTP 400 before tracker/database work.

## Actual

`syndication_routes.start_run()` validates only the top-level JSON-object shape and then uses a truthiness check:

```python
run_type = data.get("run_type")
if not run_type:
    return jsonify({"error": "run_type is required"}), 400
```

A truthy list/dict passes that check and is sent to `SyndicationTracker.start_run()`, which binds it directly into SQLite as the `run_type` parameter. CPython `sqlite3` rejects list/dict bind values with `sqlite3.ProgrammingError` (for example: `Error binding parameter 1: type 'list' is not supported`). The route's broad `except Exception` then returns that client-input failure as HTTP 500.

There is a second contract inconsistency in the same field: numeric/boolean JSON scalars are accepted by SQLite and coerced/persisted into the TEXT column rather than being rejected as invalid `run_type` values.

## Source-level reproduction of the failing boundary

```python
import sqlite3

conn = sqlite3.connect(":memory:")
conn.execute("create table t(run_type text not null)")
conn.execute("insert into t values (?)", (["x_crosspost"],))
# sqlite3.ProgrammingError: Error binding parameter 1: type 'list' is not supported
```

## Suggested fix

Validate `isinstance(run_type, str)` before `tracker.start_run()` and add a focused regression for truthy list/dict plus scalar non-string values. Existing missing/empty-string behavior can remain unchanged.

## Duplicate boundary

Fresh searches before publication found no open/closed BoTTube issue or PR for `run_type` field-type validation or this SQLite bind failure. Existing syndication work covers (a) top-level non-object JSON bodies and (b) malformed numeric/date query parameters; this report is specifically about the type of the `run_type` field inside an otherwise valid JSON object.

## Environment

- Upstream current `main` pinned above
- Source inspected through the GitHub API
- SQLite boundary reproduced with CPython `sqlite3`
- Desktop automation environment
