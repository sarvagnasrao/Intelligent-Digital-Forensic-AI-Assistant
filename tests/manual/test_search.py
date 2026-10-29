import requests
import json

# Test search endpoint
url = "http://localhost:8000/search"
payload = {
    "case_id": 1,
    "query": "test",
    "mode": "hybrid",
    "limit": 10
}

try:
    resp = requests.post(url, json=payload, timeout=30)
    print(f"Status: {resp.status_code}")
    print(f"Response: {resp.json()}")
except Exception as e:
    print(f"Error: {e}")