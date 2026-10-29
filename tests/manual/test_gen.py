import requests

url = "http://localhost:8000/generate"
payload = {
    "case_id": 1,
    "question": "Hello",
    "context_artifacts": [],
    "mode": "analysis",
    "max_tokens": 100,
    "temperature": 0.3
}

try:
    resp = requests.post(url, json=payload, timeout=60)
    print(f"Status: {resp.status_code}")
    print(f"Response: {resp.json()}")
except Exception as e:
    print(f"Error: {e}")