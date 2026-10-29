"""Print the resolved configuration as JSON for the launcher scripts.

Keeping this in a file avoids passing a multi-line Python program through
PowerShell, where embedded quotes are rewritten before Python sees them.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import load_config

config = load_config()
print(json.dumps({
    "data_dir": config.app.data_dir,
    "logs_dir": config.app.logs_dir,
    "worker_url": config.worker.url,
    "ollama_host": config.ollama.host.rstrip("/"),
    "qdrant_url": config.qdrant.url.rstrip("/"),
    "qdrant_storage": config.qdrant.storage_path,
    "ollama_model": config.ollama.model,
    "embedding_model": config.embeddings.model_id,
    "chat_provider": config.ollama.provider,
    "embedding_provider": config.embeddings.provider,
}))
