"""Configuration management for IDFA.

Paths are resolved in exactly one place so the application can live in a
read-only install directory and still keep per-user state:

* ``config.yaml`` lives in the per-user config folder (``%APPDATA%\\IDFA`` on
  Windows),
* the database, logs, evidence store and Qdrant storage are all derived from a
  single ``app.data_dir`` root that the user picks on first run and can change
  later from Settings.

Leaving a path blank in the YAML means "derive it from ``app.data_dir``", which
keeps the file portable between machines and drives.
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.util.dpapi import decrypt_secret, encrypt_secret

PROJECT_ROOT = Path(__file__).resolve().parent.parent

SQLITE_PREFIX = "sqlite:///"

LEGACY_EMBEDDING_MODELS = {
    "sentence-transformers/all-minilm-l6-v2",
    "all-minilm-l6-v2",
    "models/all-minilm-l6-v2",
}


def loopback_url(value: str) -> str:
    """Rewrite ``localhost`` to ``127.0.0.1`` in a service URL.

    ``localhost`` can resolve to ``::1`` first on Windows, while the bundled
    services bind IPv4 only. Older config files still contain it, so normalise
    rather than requiring users to edit YAML.
    """
    text = (value or "").strip()
    for scheme in ("http://", "https://"):
        if text.lower().startswith(scheme + "localhost"):
            rest = text[len(scheme) + len("localhost"):]
            if rest == "" or rest[0] in ":/?":
                return f"{scheme}127.0.0.1{rest}"
    return text


def embedding_model_name(value: str) -> str:
    """Map the retired Hugging Face id onto Ollama's model name.

    The weights are identical, so an existing installation keeps working
    without re-indexing or editing its configuration file.
    """
    name = (value or "").strip()
    if not name or name.lower() in LEGACY_EMBEDDING_MODELS:
        return "all-minilm"
    return name


def app_config_dir() -> Path:
    """Return the per-user folder that holds ``config.yaml``."""
    override = os.environ.get("IDFA_CONFIG_DIR")
    if override:
        return Path(override).expanduser()
    appdata = os.environ.get("APPDATA")
    if appdata:
        return Path(appdata) / "IDFA"
    return Path.home() / ".config" / "IDFA"


def default_config_path() -> Path:
    """Return the active configuration file path for this user."""
    return app_config_dir() / "config.yaml"


def project_config_path() -> Path:
    """Legacy location where older builds kept settings inside the project."""
    return PROJECT_ROOT / "config.yaml"


def default_data_dir() -> Path:
    """Recommended data root for a fresh install."""
    return Path.home() / "Documents" / "IDFA_Data"


class AppConfig(BaseModel):
    name: str = "IDFA"
    version: str = "0.1.0"
    debug: bool = True
    # Blank means "use the recommended location and derive everything else".
    data_dir: str = ""
    logs_dir: str = ""


class DatabaseConfig(BaseModel):
    url: str = ""
    echo: bool = False
    pool_pre_ping: bool = True


class AuthConfig(BaseModel):
    secret_key: str = "CHANGE_THIS_IN_PRODUCTION_USE_STRONG_RANDOM_KEY"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 480
    refresh_token_expire_days: int = 30
    bcrypt_rounds: int = 12


class WorkerConfig(BaseModel):
    url: str = "http://127.0.0.1:8000"
    timeout_seconds: int = 3600
    evidence_root_windows: str = ""

    @field_validator("url")
    @classmethod
    def _normalise_url(cls, value: str) -> str:
        return loopback_url(value)


class OllamaConfig(BaseModel):
    host: str = "http://127.0.0.1:11434"
    model: str = "phi3:mini"
    timeout_seconds: int = 3600
    temperature: float = 0.3
    # phi3:mini needs about 384 KiB of key/value cache per token. The values
    # below keep it near 5 GiB, which a demo laptop can load; larger windows
    # fail with an out-of-memory error before the first token is generated.
    max_tokens: int = 2048
    context_window_tokens: int = 8192
    provider: str = "ollama"
    cloud_base_url: str = "https://api.openai.com/v1"
    cloud_api_key: str = ""
    cloud_model: str = "gpt-4o-mini"
    # None denotes a legacy configuration; an explicit empty list stays empty.
    chat_local_models: list[str] | None = None
    chat_cloud_models: list[str] | None = None
    chat_connections: list[AIConnectionConfig] | None = None

    @model_validator(mode="after")
    def _migrate_chat_models(self):
        if self.chat_local_models is None:
            self.chat_local_models = [self.model] if self.model.strip() else []
        if self.chat_cloud_models is None:
            self.chat_cloud_models = [self.cloud_model] if self.cloud_model.strip() else []
        return self

    @field_validator("host")
    @classmethod
    def _normalise_host(cls, value: str) -> str:
        return loopback_url(value)


class AIModelConfig(BaseModel):
    """One explicitly configured chat model; disabled models remain stored."""

    id: str
    enabled: bool = True


class AIConnectionConfig(BaseModel):
    """Named chat connection. ``api_key`` is DPAPI-protected when saved.

    IDs are stable caller-supplied identifiers; model IDs are provider IDs, not
    display names. Listing or enabling a connection never changes background AI.
    Use :func:`connection_api_key` to obtain the usable key.
    """

    id: str
    name: str
    provider: Literal["ollama", "openai"]
    base_url: str
    api_key: str = Field(default="", repr=False)
    enabled: bool = True
    models: list[AIModelConfig] = Field(default_factory=list)


def _legacy_ai_connections(ollama: OllamaConfig) -> list[AIConnectionConfig]:
    """Materialize legacy settings once; an explicit empty catalog stays empty."""
    return [
        AIConnectionConfig(
            id="local", name="Local Ollama", provider="ollama",
            base_url=ollama.host,
            models=[AIModelConfig(id=model) for model in ollama.chat_local_models or []],
        ),
        AIConnectionConfig(
            id="cloud", name="Cloud", provider="openai",
            base_url=ollama.cloud_base_url, api_key=ollama.cloud_api_key,
            models=[AIModelConfig(id=model) for model in ollama.chat_cloud_models or []],
        ),
    ]


class EmbeddingConfig(BaseModel):
    # Ollama model name. all-minilm is all-MiniLM-L6-v2, the same 384-dimension
    # model earlier builds loaded through sentence-transformers.
    model_id: str = "all-minilm"
    provider: str = "ollama"
    batch_size: int = 64
    chunk_size: int = 1200
    chunk_overlap: int = 200

    @field_validator("chunk_size")
    @classmethod
    def _validate_chunk_size(cls, value: int) -> int:
        if not 100 <= value <= 20_000:
            raise ValueError("chunk_size must be between 100 and 20000 characters")
        return value

    @field_validator("chunk_overlap")
    @classmethod
    def _validate_chunk_overlap(cls, value: int) -> int:
        if value < 0:
            raise ValueError("chunk_overlap must be non-negative")
        return value

    @model_validator(mode="after")
    def _validate_chunk_relationship(self):
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError("chunk_overlap must be smaller than chunk_size")
        return self

    @field_validator("model_id")
    @classmethod
    def _normalise_model(cls, value: str) -> str:
        return embedding_model_name(value)


class QdrantConfig(BaseModel):
    url: str = "http://127.0.0.1:6333"
    collection_prefix: str = "idfa_case_"
    vector_size: int = 384
    distance: str = "Cosine"
    storage_path: str = ""

    @field_validator("url")
    @classmethod
    def _normalise_url(cls, value: str) -> str:
        return loopback_url(value)


class ForensicsConfig(BaseModel):
    hash_algorithms: list[str] = Field(default_factory=lambda: ["sha256", "md5"])
    chunk_size_bytes: int = 1048576
    max_file_extract_mb: int = 10
    supported_image_extensions: list[str] = Field(
        default_factory=lambda: [
            ".001", ".002", ".003", ".004", ".005", ".006", ".007", ".008",
            ".dd", ".img", ".raw",
        ]
    )
    text_extensions: list[str] = Field(
        default_factory=lambda: [
            ".txt", ".log", ".csv", ".json", ".xml", ".html", ".htm", ".md", ".eml",
        ]
    )
    doc_extensions: list[str] = Field(
        default_factory=lambda: [".pdf", ".docx", ".xlsx", ".pptx"]
    )


class UIConfig(BaseModel):
    theme: str = "dark"
    font_family: str = "Inter, Segoe UI, system-ui, sans-serif"
    language: str = "English"
    auto_refresh: bool = True
    refresh_interval_seconds: int = 30
    sidebar_width: int = 240
    sidebar_collapsed_width: int = 56
    breakpoint_sidebar_collapse: int = 900
    animation_duration_ms: int = 250


class SearchConfig(BaseModel):
    fts5_enabled: bool = True
    semantic_top_k: int = 20
    keyword_top_k: int = 50
    rrf_k: int = 60
    max_context_chunks: int = 20
    max_context_chars: int = 400000


class ReportConfig(BaseModel):
    logo_path: str = ""
    organization: str = "KSIT, Bengaluru"
    jurisdiction: str = "India"
    default_template_id: str = "court-admissible-v1"
    default_limitations: str = ""


class AnalysisConfig(BaseModel):
    """Background entity/relationship analysis.

    The defaults are deliberately cheap: analysis runs after every examination
    and again when evidence is added, so it has to finish quickly and must never
    compete with a running scan.
    """

    enabled: bool = True
    # Queue a job automatically after an examination, and for any completed
    # examination that has no analysis yet (this is what picks up newly added
    # evidence in an existing case).
    auto_queue: bool = True
    # Only start model calls when no examination is running; regex extraction
    # still proceeds.
    defer_llm_while_examining: bool = True
    llm_enabled: bool = True
    # The cloud model is used when configured; this forces local-only.
    use_cloud_when_available: bool = True
    llm_max_artifacts: int = 40
    llm_max_chars: int = 6000
    llm_timeout_seconds: int = 180

    build_timeline: bool = True
    build_relationships: bool = True
    max_entities_per_artifact: int = 60
    # An entity that appears in more than this fraction of artifacts is treated
    # as a hub and is not used to link artifacts.
    hub_fraction: float = 0.5
    hub_min_artifacts: int = 8
    max_relationship_artifacts: int = 40

    poll_seconds: int = 4


class Config(BaseModel):
    app: AppConfig = Field(default_factory=AppConfig)
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    auth: AuthConfig = Field(default_factory=AuthConfig)
    worker: WorkerConfig = Field(default_factory=WorkerConfig)
    ollama: OllamaConfig = Field(default_factory=OllamaConfig)
    embeddings: EmbeddingConfig = Field(default_factory=EmbeddingConfig)
    qdrant: QdrantConfig = Field(default_factory=QdrantConfig)
    forensics: ForensicsConfig = Field(default_factory=ForensicsConfig)
    ui: UIConfig = Field(default_factory=UIConfig)
    search: SearchConfig = Field(default_factory=SearchConfig)
    report: ReportConfig = Field(default_factory=ReportConfig)
    analysis: AnalysisConfig = Field(default_factory=AnalysisConfig)

    @model_validator(mode="after")
    def _derive_paths(self) -> Config:
        """Fill every blank path so a partially written YAML is still usable."""
        if self.ollama.chat_connections is None:
            self.ollama.chat_connections = _legacy_ai_connections(self.ollama)
        root_text = (self.app.data_dir or "").strip()
        root = Path(root_text).expanduser() if root_text else default_data_dir()
        root = Path(os.path.normpath(str(root)))
        self.app.data_dir = root.as_posix()

        if not (self.app.logs_dir or "").strip():
            self.app.logs_dir = (root / "logs").as_posix()
        if not (self.database.url or "").strip():
            self.database.url = f"{SQLITE_PREFIX}{(root / 'idfa.db').as_posix()}"
        if not (self.worker.evidence_root_windows or "").strip():
            self.worker.evidence_root_windows = (root / "cases").as_posix()
        if not (self.qdrant.storage_path or "").strip():
            self.qdrant.storage_path = (root / "qdrant").as_posix()
        return self


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_nested_delimiter="__",
        extra="ignore",
    )

    # Environment overrides use APP__DATA_DIR style names.
    app__data_dir: str | None = None
    app__logs_dir: str | None = None
    auth__secret_key: str | None = None
    database__url: str | None = None
    worker__url: str | None = None
    worker__evidence_root_windows: str | None = None
    ollama__host: str | None = None
    embeddings__model_id: str | None = None
    qdrant__url: str | None = None


_config: Config | None = None
_config_path: Path | None = None


def resolve_paths(config: Config) -> Config:
    """Fill any blank derived path from ``app.data_dir``.

    Only blank values are filled, so a deliberately customised path survives a
    reload. To *change* the data root use :func:`set_data_dir`, which clears
    the derived values first.
    """
    root = Path(config.app.data_dir).expanduser()
    config.app.data_dir = Path(os.path.normpath(str(root))).as_posix()
    if not (config.app.logs_dir or "").strip():
        config.app.logs_dir = (root / "logs").as_posix()
    if not (config.database.url or "").strip():
        config.database.url = f"{SQLITE_PREFIX}{(root / 'idfa.db').as_posix()}"
    if not (config.worker.evidence_root_windows or "").strip():
        config.worker.evidence_root_windows = (root / "cases").as_posix()
    if not (config.qdrant.storage_path or "").strip():
        config.qdrant.storage_path = (root / "qdrant").as_posix()
    return config


def set_data_dir(config: Config, path: str | Path) -> Config:
    """Point every derived path at a new data root.

    The derived values are cleared first so :func:`resolve_paths` recomputes
    them from the new root instead of keeping the old folder's paths.
    """
    config.app.data_dir = str(Path(path).expanduser())
    config.app.logs_dir = ""
    config.database.url = ""
    config.worker.evidence_root_windows = ""
    config.qdrant.storage_path = ""
    return resolve_paths(config)


def database_path(config: Config | None = None) -> Path:
    """Return the SQLite file behind ``database.url``."""
    active = config or get_config()
    url = active.database.url
    if url.startswith(SQLITE_PREFIX):
        return Path(url[len(SQLITE_PREFIX):])
    return Path(url)


def describe_layout_paths(config: Config) -> dict[str, str]:
    """Return the resolved paths that make up the data layout.

    The UI shows these so a user can see exactly what a folder change affects.
    """
    return {
        "data": config.app.data_dir,
        "database": database_path(config).as_posix(),
        "logs": config.app.logs_dir,
        "evidence": config.worker.evidence_root_windows,
        "vectors": config.qdrant.storage_path,
    }


def check_data_folder(path: str | Path) -> tuple[bool, str]:
    """Return ``(usable, reason)`` describing whether a data root is usable."""
    target = Path(path).expanduser()
    if not target.exists():
        return False, (
            "This folder does not exist. If your case data is on an external "
            "or network drive, reconnect it and try again."
        )
    if not target.is_dir():
        return False, "That path is a file, not a folder."
    probe = target / ".idfa_write_test"
    try:
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except OSError as exc:
        return False, f"This folder is not writable ({exc.strerror or exc})."
    return True, ""


def folder_size_bytes(path: str | Path) -> int:
    """Total size of the files under ``path``; 0 when it cannot be read."""
    total = 0
    try:
        for entry in Path(path).rglob("*"):
            if entry.is_file():
                try:
                    total += entry.stat().st_size
                except OSError:
                    continue
    except OSError:
        return 0
    return total


def free_space_bytes(path: str | Path) -> int | None:
    """Free space reported by the volume that holds ``path``."""
    target = Path(path).expanduser()
    probe = target
    while not probe.exists() and probe.parent != probe:
        probe = probe.parent
    try:
        return shutil.disk_usage(probe).free
    except OSError:
        return None


def ensure_data_dirs(config: Config | None = None) -> None:
    """Create the data layout. Only called once the folder has been validated."""
    active = config or get_config()
    for value in (
        active.app.data_dir,
        active.app.logs_dir,
        active.worker.evidence_root_windows,
        active.qdrant.storage_path,
    ):
        if value:
            Path(value).mkdir(parents=True, exist_ok=True)
    database_path(active).parent.mkdir(parents=True, exist_ok=True)


def _deep_merge(base: dict, override: dict) -> dict:
    """Merge ``override`` into ``base``, expanding ``a__b`` keys into nesting."""
    result = dict(base)
    for key, value in override.items():
        if "__" in key:
            parts = key.split("__")
            target = result
            for part in parts[:-1]:
                nested = target.get(part)
                if not isinstance(nested, dict):
                    nested = {}
                    target[part] = nested
                target = nested
            target[parts[-1]] = value
        else:
            result[key] = value
    return result


def load_config(config_path: str | Path | None = None) -> Config:
    """Load configuration from YAML with environment variable overrides."""
    global _config, _config_path

    if _config is not None and config_path is None:
        return _config

    target = Path(config_path) if config_path is not None else default_config_path()

    config_data: dict[str, Any] = {}
    if target.exists():
        with open(target, encoding="utf-8") as handle:
            config_data = yaml.safe_load(handle) or {}

    env_overrides = Settings().model_dump(exclude_none=True)
    config_data = _deep_merge(config_data, env_overrides)

    _config = Config(**config_data)
    _config_path = target
    return _config


def get_config() -> Config:
    """Get the loaded configuration (loads if not already loaded)."""
    if _config is None:
        return load_config()
    return _config


def get_config_path() -> Path:
    """Return the file that configuration is read from and written to."""
    return _config_path or default_config_path()


def cloud_api_key(config: Config | None = None) -> str:
    """The usable cloud provider key, decrypted for the current Windows user.

    ``ollama.cloud_api_key`` holds the encrypted form on disk; everything that
    talks to a provider must read it through this helper.
    """
    active = config or get_config()
    return decrypt_secret(active.ollama.cloud_api_key)


def connection_api_key(connection: AIConnectionConfig) -> str:
    """Return a connection's decrypted key without exposing it in repr/logs."""
    return decrypt_secret(connection.api_key)


def clear_config_cache() -> None:
    """Forget the loaded configuration so the next call re-reads the file.

    Used by tests and by any code path that needs to observe an externally
    edited config file within the same process.
    """
    global _config, _config_path
    _config = None
    _config_path = None


def reset_config(config_path: str | Path | None = None) -> None:
    """Reset every setting except the data folder, which holds case data.

    Keeping ``app.data_dir`` is deliberate: resetting preferences must never
    point the application at a different, empty database.
    """
    global _config, _config_path

    preserved_data_dir = (_config.app.data_dir or "") if _config is not None else ""

    default_config = Config()
    if preserved_data_dir:
        default_config.app.data_dir = preserved_data_dir
        default_config.app.logs_dir = ""
        default_config.database.url = ""
        default_config.worker.evidence_root_windows = ""
        default_config.qdrant.storage_path = ""
        default_config = Config(**default_config.model_dump())

    _config = None
    _config_path = None
    save_config(default_config, config_path)


def _portable_dump(config: Config) -> dict[str, Any]:
    """Serialise ``config`` with derived paths blanked.

    Writing the resolved values back would pin the file to one machine and one
    folder, so any path that already matches what ``app.data_dir`` implies is
    stored as an empty string and recomputed on load.
    """
    data = config.model_dump()
    root = Path(config.app.data_dir)

    expected: list[tuple[tuple[str, str], str]] = [
        (("app", "logs_dir"), (root / "logs").as_posix()),
        (("database", "url"), f"{SQLITE_PREFIX}{(root / 'idfa.db').as_posix()}"),
        (("worker", "evidence_root_windows"), (root / "cases").as_posix()),
        (("qdrant", "storage_path"), (root / "qdrant").as_posix()),
    ]
    for (section, key), derived in expected:
        if str(data[section][key]) == derived:
            data[section][key] = ""
    return data


def save_config(config: Config, config_path: str | Path | None = None) -> None:
    """Write configuration to YAML atomically, storing only portable paths."""
    global _config, _config_path

    # A cloud API key must not sit in the profile as readable text. Encrypting
    # here covers every caller, and upgrades a plain-text value from an older
    # config the first time settings are saved.
    config.ollama.cloud_api_key = encrypt_secret(config.ollama.cloud_api_key)
    for connection in config.ollama.chat_connections or []:
        if connection.api_key:
            protected = encrypt_secret(connection.api_key)
            if not protected.startswith("dpapi:"):
                raise RuntimeError("Unable to protect AI connection key with Windows DPAPI")
            connection.api_key = protected

    target = Path(config_path) if config_path is not None else get_config_path()
    target.parent.mkdir(parents=True, exist_ok=True)

    payload = yaml.safe_dump(
        _portable_dump(config), default_flow_style=False, sort_keys=False
    )

    # Write-then-replace: an interrupted save can never leave a half-written
    # config that would fail to parse on the next launch.
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(payload, encoding="utf-8")
    os.replace(temporary, target)

    _config = config
    _config_path = target
