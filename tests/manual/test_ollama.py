import requests
import json

url = "http://localhost:11434/api/generate"
payload = {
    "model": "phi3:mini",
    "prompt": "Hello, respond briefly.",
    "stream": False,
    "options": {
        "temperature": 0.3,
        "num_predict": 100
    }
}

try:
    resp = requests.post(url, json=payload, timeout=60)
    print(f"Status: {resp.status_code}")
    print(f"Response: {resp.json()}")
except Exception as e:
    print(f"Error: {e}")