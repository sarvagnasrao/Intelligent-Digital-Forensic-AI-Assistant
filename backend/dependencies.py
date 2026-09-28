from dotenv import load_dotenv
load_dotenv()

from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache


class Settings(BaseSettings):
    database_url: str
    cases_dir: str
    # Where per-case Qdrant indexes live. Empty = inside cases_dir (the old
    # behaviour). Set this to a fast disk when cases_dir is on a rotating
    # drive: the Qdrant upsert is ~92% of ingestion time and is seek-latency
    # bound, so it is ~13x slower on a 7200 RPM disk than on an NVMe SSD.
    # See backend/modules/vector_store.py::case_qdrant_path.
    qdrant_dir: str = ""
    app_name: str
    app_version: str
    debug: bool = False
    secret_key: str = "idfai-secret-key-change-in-production"
    ollama_model: str = "llama3.2:3b"
    ollama_base_url: str = "http://localhost:11434"

    # The context window the *running* Ollama actually gives the model.
    #
    # This is not the model's trained length. llama3.2:3b trains at 131072,
    # which is what /api/show reports, but Ollama serves it with n_ctx=4096
    # unless the operator sets OLLAMA_CONTEXT_LENGTH or the Modelfile says
    # otherwise. Budgeting against the trained figure over-estimates the real
    # window by 32x, which is how a 212,000-character RAG prompt reached a
    # 4,096-token model intact enough to look fine and was actually discarded.
    # ollama_client.effective_context_tokens() prefers the live value from
    # /api/ps and falls back to this.
    ollama_num_ctx: int = 4096

    # Generation ceiling, subtracted from the context window because Ollama's
    # n_ctx is shared between prompt and completion.
    ollama_num_predict: int = 1024

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )


@lru_cache()
def get_settings() -> Settings:
    return Settings()
