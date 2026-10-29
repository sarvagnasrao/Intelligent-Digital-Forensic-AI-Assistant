#!/bin/bash
curl -s -X POST http://localhost:8000/generate \
  -H "Content-Type: application/json" \
  -d '{"case_id": 1, "question": "What files were found?", "context_artifacts": []}'