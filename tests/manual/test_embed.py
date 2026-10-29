"""Ad-hoc check for the worker's embedding endpoint.

Start the worker first:

    .venv\\Scripts\\python.exe worker\\main.py

Then run:

    .venv\\Scripts\\python.exe tests\\manual\\test_embed.py

Verifies that Ollama serves the configured embedding model at the expected
dimension, and that a batch returns one vector per input.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request

WORKER = "http://127.0.0.1:8000"
EXPECTED_DIMENSIONS = 384

payload = {
    "texts": [
        "invoice 4471 for office supplies",
        "USB device serial 0781-5567",
        "email confirming termination",
    ]
}

request = urllib.request.Request(
    f"{WORKER}/embed",
    data=json.dumps(payload).encode("utf-8"),
    headers={"Content-Type": "application/json"},
)

try:
    with urllib.request.urlopen(request, timeout=300) as response:
        body = json.loads(response.read())
except urllib.error.URLError as exc:
    raise SystemExit(f"Worker not reachable at {WORKER}: {exc}")

if not body.get("success"):
    raise SystemExit(f"Embedding failed: {body.get('error')}")

embeddings = body.get("embeddings") or []
print(f"vectors : {len(embeddings)} (expected {len(payload['texts'])})")
print(f"dimensions: {body.get('dimensions')} (expected {EXPECTED_DIMENSIONS})")
print(f"first values: {embeddings[0][:5]}")

assert len(embeddings) == len(payload["texts"]), "one vector per text"
assert body["dimensions"] == EXPECTED_DIMENSIONS, "vector size must match Qdrant"
assert all(len(vector) == EXPECTED_DIMENSIONS for vector in embeddings), "uniform size"
print("embedding endpoint OK")
