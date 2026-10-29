# Manual test scripts

These are ad-hoc checks used during development. They are **not** pytest tests and
are excluded from pytest collection.

| File | Purpose |
|------|---------|
| `test_ai.py` | POST a sample question to the worker `/generate` endpoint |
| `test_gen.py` | Minimal `/generate` request |
| `test_generate.py` | `/generate` request with a case question |
| `test_generate.sh` | curl version of the `/generate` request |
| `test_embed.py` | POST artifact IDs to the worker `/embed` endpoint |
| `test_search.py` | POST a hybrid search query to `/search` |
| `test_ollama.py` | Direct Ollama `/api/generate` check |
| `test_worker.py` | Import the worker module (run from the worker directory) |
| `test_import.sh` | Import the deployed worker in WSL |
| `test_examine_direct.py` | Call the worker's `examine()` handler directly |
| `test_examine.json` | Example examination request payload |

## Run

Start the services first with `START_IDFA.bat`, then from the project root:

```powershell
.venv\Scripts\python.exe tests\manual\test_ai.py
```

`test_worker.py`, `test_examine_direct.py`, and `test_import.sh` must run where
the worker module is importable:

```powershell
# Windows (from the worker folder)
cd worker
..\.venv\Scripts\python.exe ..\tests\manual\test_worker.py

# WSL
wsl -d Ubuntu -u root -- bash -lc "cd /root/idfa-worker && source /root/idfa-worker-venv/bin/activate && python /mnt/e/Users/sarva/Documents/Final_Project/tests/manual/test_examine_direct.py"
```

`test_examine_direct.py` starts a real full examination. Use it only when you
intend to process evidence.
