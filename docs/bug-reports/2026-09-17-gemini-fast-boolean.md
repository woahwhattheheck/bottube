# BoTTube bug report: Gemini `fast` flag accepts non-booleans and can invert caller intent

Bounty: `Scottcjn/rustchain-bounties#1102`

Upstream source measured: `Scottcjn/bottube@6af6b63f7a5a87353a30cd4552dc5c0e183a96af`

Affected path: `gemini_blueprint.py`, authenticated `POST /api/gemini/generate-video`

## Summary

The documented request contract presents `fast` as a JSON boolean:

```json
{"prompt": "...", "fast": false}
```

The handler does not validate that type. It currently computes:

```python
fast = bool(data.get("fast", False))
```

Python truthiness means any non-empty string, non-empty list, non-empty object, or non-zero number becomes `True`. In particular, the plausible client mistake `"fast": "false"` is interpreted as **true**, so the route selects `VIDEO_MODEL_FAST` even though the supplied value says `false`.

## Source path to the wrong model

On the pinned upstream commit, `generate_video()` parses the JSON object and validates `prompt` and `negative_prompt`, then performs:

```python
resolution = data.get("resolution", "720p")
if resolution not in ("720p", "1080p"):
    resolution = "720p"
fast = bool(data.get("fast", False))
```

Later in the same handler:

```python
model = VIDEO_MODEL_FAST if fast else VIDEO_MODEL
```

The chosen `fast` value is also passed into `_generate_video_async(...)`, where it independently selects the fast model again:

```python
model = VIDEO_MODEL_FAST if fast else VIDEO_MODEL
```

So this is not display-only metadata; the coerced value controls which generation model is requested.

## Deterministic reproduction

The relevant logic can be reproduced without credentials or a paid Gemini request:

```python
VIDEO_MODEL = "veo-3.1-generate-preview"
VIDEO_MODEL_FAST = "veo-3.1-fast-generate-preview"

for supplied in [False, True, "false", "true", 0, 1, [], [1], {}, {"x": 1}]:
    fast = bool(supplied)
    model = VIDEO_MODEL_FAST if fast else VIDEO_MODEL
    print(repr(supplied), type(supplied).__name__, fast, model)
```

Observed output for representative values:

```text
False      bool  False veo-3.1-generate-preview
True       bool  True  veo-3.1-fast-generate-preview
'false'    str   True  veo-3.1-fast-generate-preview
'true'     str   True  veo-3.1-fast-generate-preview
0          int   False veo-3.1-generate-preview
1          int   True  veo-3.1-fast-generate-preview
[]         list  False veo-3.1-generate-preview
[1]        list  True  veo-3.1-fast-generate-preview
{}         dict  False veo-3.1-generate-preview
{'x': 1}   dict  True  veo-3.1-fast-generate-preview
```

The load-bearing case is JSON string `"false"`: Flask decodes it as Python `str`, and `bool("false")` is `True`.

## Expected behavior

Because the API documents `fast` as a boolean, only JSON `true` and `false` should be accepted. Non-boolean values should return HTTP 400 before rate-limit quota is consumed, a job row is inserted, or a generation thread starts.

For example:

```python
fast = data.get("fast", False)
if not isinstance(fast, bool):
    return jsonify({"error": "fast must be a boolean"}), 400
```

Then use `fast` directly for model selection.

## Why this matters

This can silently change the requested model rather than merely rejecting malformed input. A client serializing form values as strings can ask for `false` and receive the fast-model path. That makes request semantics depend on Python container truthiness instead of the API contract and can affect generation quality, latency, and provider-side behavior without a clear client error.

## Regression coverage to add

`tests/test_gemini_request_validation.py` already proves malformed JSON shape and string fields are rejected before a job or generation starts. A focused regression should extend that contract:

- `{ "prompt": "draw this", "fast": "false" }` -> 400, `fast must be a boolean`, zero jobs
- `{ "prompt": "draw this", "fast": 1 }` -> 400, zero jobs
- `{ "prompt": "draw this", "fast": [] }` -> 400, zero jobs
- JSON boolean `false` remains valid and selects `VIDEO_MODEL`
- JSON boolean `true` remains valid and selects `VIDEO_MODEL_FAST`

## Scope

No production endpoint was invoked and no paid Gemini generation was started. The finding is source-level and deterministic against the exact upstream commit above.