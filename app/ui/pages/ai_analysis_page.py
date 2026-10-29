"""AI Analysis Page."""
from __future__ import annotations

import asyncio
import re
from datetime import datetime, timezone
from typing import TYPE_CHECKING

import httpx
from PySide6.QtCore import QObject, Qt, QThread, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.config import cloud_api_key, get_config
from app.ui import qt_threads
from app.ui.base import CaseContext, ResponsivePage
from app.ui.layouts import configure_detail_pane, configure_detail_splitter
from app.ui.markdown import MarkdownView, looks_like_markdown
from app.ui.theme.tokens import Color, Spacing, Typography

if TYPE_CHECKING:
    from app.artifacts.service import SearchService


# State names used by the status strip. They map to a coloured icon so the
# strip can say "offline", "not pulled" and "partly indexed" distinctly.
STATUS_WORDS = {
    "ok": "Ready",
    "error": "Offline",
    "partial": "Partial",
    "checking": "Checking",
    "unknown": "Unknown",
}


class ChatMessageWidget(QFrame):
    """Single chat message bubble.

    Assistant text is rendered as Markdown when it contains Markdown syntax and
    as plain text otherwise, so a Markdown report shows real headings and
    tables while an ordinary sentence keeps its literal line breaks.
    """

    def __init__(self, text: str, is_user: bool, citations: list | None = None,
                 parent: QWidget | None = None):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(Spacing.MD, Spacing.SM, Spacing.MD, Spacing.SM)
        layout.setSpacing(Spacing.XS)

        # Message bubble
        bubble = QFrame()
        bubble.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        bubble_layout = QVBoxLayout(bubble)
        bubble_layout.setContentsMargins(Spacing.MD, Spacing.SM, Spacing.MD, Spacing.SM)
        bubble_layout.setSpacing(Spacing.XS)

        if is_user:
            bubble.setStyleSheet(f"""
                QFrame {{
                    background: {Color.PRIMARY.name()};
                    border-radius: {Spacing.MD}px;
                }}
            """)
            msg = QLabel(text)
            msg.setFont(QFont(Typography.FONT_FAMILY, Typography.BODY_MD[0]))
            msg.setStyleSheet("color: white; background: transparent; border: none;")
            msg.setWordWrap(True)
            # Model output and evidence text must never be interpreted as HTML.
            msg.setTextFormat(Qt.TextFormat.PlainText)
            msg.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            bubble_layout.addWidget(msg)

            # Right align
            wrapper = QHBoxLayout()
            wrapper.addStretch()
            wrapper.addWidget(bubble)
            layout.addLayout(wrapper)
        else:
            bubble.setStyleSheet(f"""
                QFrame {{
                    background: {Color.BG_TERTIARY.name()};
                    border-radius: {Spacing.MD}px;
                    border: 1px solid {Color.BORDER_LIGHT.name()};
                }}
            """)
            is_markdown = looks_like_markdown(text)
            if is_markdown:
                # Tables and code need the available width, so a Markdown answer
                # uses the full lane instead of shrinking to its size hint.
                bubble.setSizePolicy(
                    QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
                )
                msg = MarkdownView(text)
            else:
                msg = QLabel(text)
                msg.setFont(QFont(Typography.FONT_FAMILY, Typography.BODY_MD[0]))
                msg.setStyleSheet(
                    f"color: {Color.TEXT_PRIMARY.name()}; "
                    "background: transparent; border: none;"
                )
                msg.setWordWrap(True)
                msg.setTextFormat(Qt.TextFormat.PlainText)
                msg.setTextInteractionFlags(
                    Qt.TextInteractionFlag.TextSelectableByMouse
                )
            bubble_layout.addWidget(msg)

            # AI disclaimer
            disclaimer = QLabel("⚠️ AI-generated, unverified")
            disclaimer.setFont(QFont(Typography.FONT_FAMILY, Typography.LABEL[0]))
            disclaimer.setStyleSheet(
                f"color: {Color.WARNING.name()}; "
                "background: transparent; border: none;"
            )
            bubble_layout.addWidget(disclaimer)

            # Citations
            if citations:
                cite_label = QLabel(f"Sources: {', '.join(citations)}")
                cite_label.setFont(QFont(Typography.FONT_FAMILY, Typography.BODY_SM[0]))
                cite_label.setStyleSheet(
                    f"color: {Color.TEXT_SECONDARY.name()}; "
                    "background: transparent; border: none;"
                )
                cite_label.setWordWrap(True)
                bubble_layout.addWidget(cite_label)

            # Left align
            wrapper = QHBoxLayout()
            if is_markdown:
                wrapper.addWidget(bubble, 1)
            else:
                wrapper.addWidget(bubble)
                wrapper.addStretch()
            layout.addLayout(wrapper)


class CitationPanel(QFrame):
    """Right panel showing retrieved evidence citations."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("CitationPanel")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        configure_detail_pane(self)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(Spacing.MD, Spacing.MD, Spacing.MD, Spacing.MD)
        layout.setSpacing(Spacing.SM)

        title = QLabel("Retrieved Evidence")
        title.setFont(QFont(Typography.FONT_FAMILY, Typography.HEADING_SM[0], Typography.HEADING_SM[1]))
        layout.addWidget(title)

        self.caption = QLabel(
            "Artifacts sent to the model as context for the last question."
        )
        self.caption.setWordWrap(True)
        self.caption.setFont(QFont(Typography.FONT_FAMILY, Typography.BODY_SM[0]))
        self.caption.setStyleSheet(f"color: {Color.TEXT_SECONDARY.name()};")
        layout.addWidget(self.caption)

        self.citation_list = QTextEdit()
        self.citation_list.setReadOnly(True)
        self.citation_list.setFont(QFont(Typography.FONT_FAMILY, Typography.BODY_SM[0]))
        layout.addWidget(self.citation_list, 1)

        self.set_citations([])

    def set_message(self, text: str):
        """Show a neutral message instead of citations."""
        self.citation_list.setPlainText(text)

    def set_citations(self, citations: list[dict]):
        """Set citations from retrieval results."""
        self.citation_list.clear()
        if not citations:
            self.citation_list.setPlainText(
                "No artifacts retrieved yet.\n\n"
                "Ask a question and the artifacts used as context will be "
                "listed here."
            )
            return

        for i, cite in enumerate(citations, 1):
            name = cite.get("name") or cite.get("source") or "Unknown artifact"
            artifact_type = cite.get("artifact_type") or cite.get("type") or "file"
            self.citation_list.append(f"{i}. {name} ({artifact_type})")
            if cite.get("artifact_id"):
                self.citation_list.append(f"   Artifact: {cite['artifact_id']}")
            if cite.get("provenance"):
                self.citation_list.append(f"   Provenance: {cite['provenance']}")
            if cite.get("chunk_index") is not None:
                self.citation_list.append(
                    f"   Passage: chunk {cite['chunk_index']} "
                    f"(characters {cite.get('char_start', 0)}–{cite.get('char_end', 0)})"
                )
            try:
                score = float(cite.get("score") or 0.0)
            except (TypeError, ValueError):
                score = 0.0
            if score:
                self.citation_list.append(f"   Score: {score:.3f}")
            path = cite.get("path") or cite.get("source_path")
            if path:
                self.citation_list.append(f"   Path: {path}")
            snippet = (cite.get("snippet") or "").strip()
            if snippet:
                snippet = " ".join(snippet.split())
                if len(snippet) > 240:
                    snippet = snippet[:237] + "..."
                self.citation_list.append(f"   Snippet: {snippet}")
            self.citation_list.append("")


class StatusStrip(QFrame):
    """Live health of the services the assistant depends on.

    Each label answers one question: is the forensic worker reachable, is Ollama
    running, is the configured chat model pulled, is the embedding model
    usable, is Qdrant up, and how much of this case is embedded for semantic
    search. Keyword retrieval still works when the embedding/index pieces are
    missing, so the strip never blocks the chat.
    """

    refresh_requested = Signal()

    SERVICES = ("Worker", "Ollama", "Model", "Embedding", "Qdrant", "Index")

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("StatusStrip")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setMinimumHeight(56)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(Spacing.MD, Spacing.XS, Spacing.MD, Spacing.XS)
        layout.setSpacing(Spacing.SM)

        config = get_config()
        self._base_tooltips = {
            "Worker": f"Local forensic/AI worker at {config.worker.url}. "
                      "AI answers are generated here.",
            "Ollama": f"Local LLM runtime at {config.ollama.host}.",
            "Model": f"Chat model the worker asks Ollama for "
                     f"({config.ollama.model}).",
            "Embedding": f"Embedding model used for semantic search "
                         f"({config.embeddings.model_id} in Ollama).",
            "Qdrant": f"Vector database at {config.qdrant.url}.",
            "Index": "Embedded artifacts for this case. When this is empty, "
                     "retrieval falls back to keyword search. Index on the "
                     "Artifacts & Search page.",
        }

        self.services: dict[str, QLabel] = {}
        for service in self.SERVICES:
            label = QLabel(f"{service} · Unknown")
            label.setObjectName("AIServiceStatus")
            label.setProperty("status", "unknown")
            label.setFont(QFont(Typography.FONT_FAMILY, Typography.BODY_SM[0]))
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setMinimumHeight(28)
            label.setToolTip(self._base_tooltips[service])
            self.services[service] = label
            layout.addWidget(label)

        layout.addStretch()

        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.setObjectName("AIStatusAction")
        self.refresh_btn.setProperty("secondary", True)
        self.refresh_btn.setFixedHeight(36)
        self.refresh_btn.setToolTip(
            "Re-check the AI services, models and this case's search index."
        )
        self.refresh_btn.clicked.connect(self.refresh_requested)
        layout.addWidget(self.refresh_btn)
        self.download_embedding_btn = QPushButton("Pull Embedding Model")
        self.download_embedding_btn.setObjectName("AIStatusAction")
        self.download_embedding_btn.setProperty("secondary", True)
        self.download_embedding_btn.setFixedHeight(36)
        self.download_embedding_btn.setToolTip(
            f"Ask Ollama for the {get_config().embeddings.model_id} embedding model. "
            "The offline bundle already includes it, so this is only needed on a "
            "connected machine."
        )
        self.download_embedding_btn.hide()
        layout.addWidget(self.download_embedding_btn)

    def set_status(self, service: str, state: str = "unknown",
                   detail: str = "", tooltip: str = ""):
        label = self.services.get(service)
        if label is None:
            return
        text = f"{service} · {STATUS_WORDS.get(state, STATUS_WORDS['unknown'])}"
        if detail and service == "Index":
            text += f"  {detail}"
        label.setText(text)
        label.setProperty("status", state)
        label.style().unpolish(label)
        label.style().polish(label)
        base = self._base_tooltips.get(service, "")
        label.setToolTip(f"{base}\n\n{tooltip}".strip() if tooltip else base)

    def set_all_unknown(self, detail: str = ""):
        for service in self.SERVICES:
            self.set_status(service, "unknown", detail)

    def set_all_checking(self):
        for service in self.SERVICES:
            self.set_status(service, "checking")


class StatusCheckWorker(QObject):
    """Checks the AI services and this case's index off the UI thread."""

    finished = Signal(dict)

    def __init__(self, case_id: int):
        super().__init__()
        self.case_id = case_id

    def run(self):
        config = get_config()
        payload: dict = {"case_id": self.case_id}
        try:
            with httpx.Client(timeout=5.0) as client:
                payload.update(self._service_status(config, client))
                payload["Index"] = self._index_status(config, client)
        except Exception as exc:  # never leave the strip stuck on "checking"
            payload.setdefault("Worker", {
                "state": "error",
                "detail": "check failed",
                "tooltip": str(exc),
            })
            payload["Index"] = {
                "state": "unknown",
                "detail": "check failed",
                "tooltip": str(exc),
            }
        self.finished.emit(payload)

    @staticmethod
    def _get(client: httpx.Client, url: str):
        try:
            return client.get(url)
        except Exception:
            return None

    def _service_status(self, config, client: httpx.Client) -> dict:
        status: dict = {}

        # --- local worker -------------------------------------------------
        resp = self._get(client, f"{config.worker.url}/health")
        if resp is None:
            status["Worker"] = {
                "state": "error",
                "detail": "unreachable",
                "tooltip": f"No response from {config.worker.url}. Start the "
                           "worker to enable AI answers.",
            }
        elif resp.status_code != 200:
            status["Worker"] = {
                "state": "error",
                "detail": f"HTTP {resp.status_code}",
                "tooltip": f"{config.worker.url}/health returned HTTP "
                           f"{resp.status_code}.",
            }
        else:
            try:
                health = resp.json()
            except Exception:
                health = {}
            degraded = [
                key for key in ("pytsk3", "ollama", "qdrant")
                if health.get(key) is False
            ]
            status["Worker"] = {
                "state": "partial" if degraded else "ok",
                "detail": "degraded" if degraded else "ready",
                "tooltip": (
                    f"{config.worker.url}/health: "
                    + (", ".join(f"{key}=false" for key in degraded)
                       if degraded else "all required components available")
                ),
            }

        # --- Ollama + models --------------------------------------------
        # Cloud chat plus cloud embeddings is a deliberately Ollama-free setup:
        # IDFA stops the instance it manages, so a red "offline" tile here would
        # report a fault that does not exist.
        local_ollama_needed = (
            config.ollama.provider != "openai"
            or config.embeddings.provider != "openai"
        )
        tags = (
            self._get(client, f"{config.ollama.host}/api/tags")
            if local_ollama_needed
            else None
        )
        model_names: list[str] = []
        if not local_ollama_needed:
            status["Ollama"] = {
                "state": "ok",
                "detail": "not needed",
                "tooltip": "Chat and embeddings both use cloud providers, so IDFA "
                           "stopped the Ollama instance it manages. Set either "
                           "provider back to Local to start it again.",
            }
        elif tags is None or tags.status_code != 200:
            status["Ollama"] = {
                "state": "error",
                "detail": "offline",
                "tooltip": f"No response from {config.ollama.host}. "
                           "Start Ollama, then press Refresh.",
            }
        else:
            try:
                model_names = [
                    item.get("name", "")
                    for item in tags.json().get("models", [])
                ]
            except Exception:
                model_names = []
            status["Ollama"] = {
                "state": "ok",
                "detail": "up",
                "tooltip": f"{len(model_names)} model(s) available: "
                           + (", ".join(model_names) or "none"),
            }

        chat_model = (
            config.ollama.cloud_model
            if config.ollama.provider == "openai"
            else config.ollama.model
        )
        if config.ollama.provider == "openai":
            has_key = bool(cloud_api_key(config).strip())
            status["Model"] = {
                "state": "ok" if has_key else "error",
                "detail": chat_model if has_key else "API key missing",
                "tooltip": (
                    f"Cloud model {chat_model} via {config.ollama.cloud_base_url}. "
                    "Credentials are configured; connection is verified when you send a request."
                    if has_key else "Enter a cloud provider API key in Settings."
                ),
            }
        elif "Ollama" in status and status["Ollama"]["state"] == "error":
            status["Model"] = {
                "state": "unknown",
                "detail": chat_model,
                "tooltip": "Ollama is offline, so the chat model cannot be "
                           "checked.",
            }
        else:
            def normalize_model(value: str) -> str:
                return value.casefold().removesuffix(":latest")

            if normalize_model(chat_model) in {normalize_model(name) for name in model_names}:
                status["Model"] = {
                    "state": "ok",
                    "detail": chat_model,
                    "tooltip": f"{chat_model} is pulled in Ollama and will "
                               "answer the questions.",
                }
            else:
                status["Model"] = {
                    "state": "error",
                    "detail": "missing",
                    "tooltip": f"{chat_model} is not pulled in Ollama. Run: "
                               f"ollama pull {chat_model}",
                }

        # Embeddings come from the same Ollama runtime, so this check only asks
        # whether the model is pulled. It never triggers a download.
        try:
            from app.ai.embeddings import model_available

            available = model_available()
        except Exception:
            available = False
        if available:
            status["Embedding"] = {
                "state": "ok",
                "detail": "ready",
                "tooltip": (
                    f"{config.embeddings.model_id} uses the configured cloud API."
                    if config.embeddings.provider == "openai"
                    else f"{config.embeddings.model_id} is available in Ollama at "
                         f"{config.ollama.host}."
                ),
            }
        else:
            status["Embedding"] = {
                "state": "error",
                "detail": (
                    "API key missing"
                    if config.embeddings.provider == "openai"
                    else "not pulled"
                ),
                "tooltip": (
                    "Enter a cloud API key in Settings to enable cloud embeddings."
                    if config.embeddings.provider == "openai"
                    else f"{config.embeddings.model_id} is not pulled in Ollama. "
                         f"Press \"Pull Embedding Model\", or run: "
                         f"ollama pull {config.embeddings.model_id}"
                ),
            }

        # --- Qdrant ------------------------------------------------------
        collections = self._get(client, f"{config.qdrant.url}/collections")
        if collections is None or collections.status_code != 200:
            status["Qdrant"] = {
                "state": "error",
                "detail": "offline",
                "tooltip": f"No response from {config.qdrant.url}. Start the "
                           "local Qdrant service to enable semantic search.",
            }
        else:
            try:
                names = [
                    item.get("name", "")
                    for item in collections.json().get("result", {}).get("collections", [])
                ]
            except Exception:
                names = []
            status["Qdrant"] = {
                "state": "ok",
                "detail": "up",
                "tooltip": f"{len(names)} collection(s): "
                           + (", ".join(names) or "none"),
            }

        return status

    def _index_status(self, config, client: httpx.Client) -> dict:
        total = 0
        eligible = 0
        indexed = 0
        try:
            from sqlalchemy import func, select

            from app.artifacts.models import Artifact, IndexStatus
            from app.db.session import get_session_factory
            from app.evidence.models import Evidence

            session = get_session_factory()()
            try:
                total = session.scalar(
                    select(func.count(Artifact.id))
                    .join(Evidence, Artifact.evidence_id == Evidence.id)
                    .where(
                        Artifact.case_id == self.case_id,
                        Evidence.removed_at.is_(None),
                    )
                ) or 0
                eligible = session.scalar(
                    select(func.count(Artifact.id))
                    .join(Evidence, Artifact.evidence_id == Evidence.id)
                    .where(
                        Artifact.case_id == self.case_id,
                        Evidence.removed_at.is_(None),
                        Artifact.content_text.is_not(None),
                        func.trim(Artifact.content_text) != "",
                    )
                ) or 0
                indexed = session.scalar(
                    select(func.count(Artifact.id))
                    .join(Evidence, Artifact.evidence_id == Evidence.id)
                    .where(
                        Artifact.case_id == self.case_id,
                        Evidence.removed_at.is_(None),
                        Artifact.content_text.is_not(None),
                        func.trim(Artifact.content_text) != "",
                        Artifact.index_status == IndexStatus.INDEXED,
                    )
                ) or 0
            finally:
                session.close()
        except Exception as exc:
            return {
                "state": "unknown",
                "detail": "unknown",
                "tooltip": f"Could not count this case's artifacts: {exc}",
            }

        collection = f"{config.qdrant.collection_prefix}{self.case_id}"
        points = None
        info = self._get(client, f"{config.qdrant.url}/collections/{collection}")
        if info is not None and info.status_code == 200:
            try:
                points = info.json().get("result", {}).get("points_count", 0)
            except Exception:
                points = None

        tooltip = (
            f"{indexed} of {eligible} active, text-bearing artifacts embedded for semantic search"
            + (
                f"; {total - eligible} artifact(s) have no extracted text and cannot be embedded"
                if total > eligible else ""
            )
            + (f" ({points} Qdrant point(s) in {collection})." if points is not None
               else f" (collection {collection} does not exist yet).")
            + " Index on the Artifacts & Search page; keyword search is used "
              "until then."
        )
        if total == 0:
            return {
                "state": "unknown",
                "detail": "no artifacts",
                "tooltip": "This case has no examined artifacts yet, so there "
                           "is nothing to retrieve. Run an examination first.",
            }
        if eligible == 0:
            return {
                "state": "unknown",
                "detail": "no text",
                "tooltip": tooltip + ". Examine evidence that contains extractable text to enable semantic search.",
            }
        if indexed == 0:
            return {"state": "error", "detail": f"0/{eligible}", "tooltip": tooltip}
        if indexed < eligible:
            return {"state": "partial", "detail": f"{indexed}/{eligible}", "tooltip": tooltip}
        return {"state": "ok", "detail": f"{indexed}/{eligible}", "tooltip": tooltip}


class EmbeddingModelPullWorker(QObject):
    """Asks Ollama to pull the embedding model on explicit user request."""

    finished = Signal(dict)

    def run(self):
        try:
            from app.ai.embeddings import pull_model

            name = pull_model()
            self.finished.emit({"model": name, "error": None})
        except Exception as exc:
            self.finished.emit({"model": "", "error": str(exc)})


class AskWorker(QObject):
    """Retrieves context for a question, then asks the worker to answer it.

    The worker owns its database session: Qt threads cannot share a session
    with the UI thread, and the search service needs one for FTS5.
    """

    finished = Signal(dict)

    def __init__(
        self,
        case_id: int,
        question: str,
        token: int,
        *,
        conversation: bool = False,
        case_reference: str = "",
        case_title: str = "",
        conversation_history: list[dict] | None = None,
        expand_graph: bool = False,
        cloud_consent: bool = False,
    ):
        super().__init__()
        self.case_id = case_id
        self.question = question
        self.token = token
        self.conversation = conversation
        self.case_reference = case_reference
        self.case_title = case_title
        self.conversation_history = list(conversation_history or [])
        self.expand_graph = expand_graph
        self.cloud_consent = cloud_consent
        config = get_config()
        self.max_artifacts = max(1, config.search.max_context_chunks)
        self.max_content_chars = max(
            1000, config.search.max_context_chars // self.max_artifacts
        )

    def run(self):
        result = {
            "token": self.token,
            "case_id": self.case_id,
            "question": self.question,
            "mode": "conversation" if self.conversation else "analysis",
            "answer": "",
            "citations": [],
            "error": None,
        }
        session = None
        try:
            if self.conversation:
                result["answer"] = self._generate([], mode="conversation")
            else:
                config = get_config()
                if (config.ollama.provider == "openai" and not self.cloud_consent):
                    result["error"] = (
                        "Cloud AI is configured, but this case has not consented "
                        "to sending evidence text. Enable the case disclosure option."
                    )
                    return
                from app.db.session import get_session_factory

                session = get_session_factory()()
                retrieved = self._retrieve(session)
                result["citations"] = [item["citation"] for item in retrieved]
                if not retrieved:
                    result["error"] = (
                        "No examined artifacts were found for this case. Register "
                        "evidence and run an examination on the Examination page, "
                        "then ask again."
                    )
                    return
                result["answer"] = self._generate(
                    [item["context"] for item in retrieved]
                )
        except Exception as exc:
            if self.conversation:
                result["error"] = (
                    "I couldn't get a reply from the local model just now. "
                    f"Please try again in a moment. (Details: {exc})"
                )
            else:
                result["error"] = str(exc)
        finally:
            if session is not None:
                session.close()
            self.finished.emit(result)

    def _retrieve(self, session) -> list[dict]:
        """Hybrid search with a newest-artifacts fallback.

        Semantic search needs an embedding model and a populated collection;
        when either is missing hybrid_search simply returns keyword hits, and
        with no hits at all the newest artifacts are used so the assistant can
        still describe the evidence.
        """
        results: list[dict] = []
        try:
            from app.artifacts.service import SearchService

            service: "SearchService" = SearchService(session)
            loop = asyncio.new_event_loop()
            try:
                results = loop.run_until_complete(
                    service.hybrid_search(
                        self.case_id, self.question,
                        keyword_limit=100, semantic_limit=100,
                    )
                )
            finally:
                try:
                    loop.run_until_complete(service.close())
                except Exception:
                    pass
                loop.close()
        except Exception:
            results = []

        items: list[dict] = []
        seen: set[int] = set()
        for result in results:
            artifact = result.get("artifact")
            if artifact is None:
                continue
            items.append(self._as_item(session, artifact, score=result.get("score"),
                                       chunk_index=result.get("chunk_index"),
                                       source=result.get("source")))
            seen.add(getattr(artifact, "id", None))
            if len(items) >= self.max_artifacts:
                break

        if items:
            if self.expand_graph:
                items = self._expand_graph(session, items)
            return items

        try:
            from sqlalchemy import select

            from app.artifacts.models import Artifact
            from app.evidence.models import Evidence

            stmt = (
                select(Artifact)
                .join(Evidence, Artifact.evidence_id == Evidence.id)
                .where(
                    Artifact.case_id == self.case_id,
                    Evidence.removed_at.is_(None),
                )
                .order_by(Artifact.created_at.desc())
                .limit(self.max_artifacts)
            )
            for artifact in session.execute(stmt).scalars().all():
                if getattr(artifact, "id", None) in seen:
                    continue
                items.append(self._as_item(session, artifact, score=None))
        except Exception:
            pass
        return items

    def _as_item(self, session, artifact, score, chunk_index=None, source=None) -> dict:
        """Turn an Artifact row into context + citation data."""
        artifact_type = getattr(artifact, "artifact_type", "")
        artifact_type = getattr(artifact_type, "value", artifact_type) or "file"
        name = getattr(artifact, "name", "") or "artifact"
        path = getattr(artifact, "source_path", "") or ""
        content = (getattr(artifact, "content_text", "") or "").strip()

        if not content:
            # Artifacts without extracted text still give the model useful
            # metadata instead of an empty context block.
            parts = [f"{name} ({artifact_type})"]
            description = (getattr(artifact, "description", "") or "").strip()
            if description:
                parts.append(description)
            if path:
                parts.append(f"Source path: {path}")
            size = getattr(artifact, "source_size", None)
            if size:
                parts.append(f"Size: {size} bytes")
            modified = getattr(artifact, "modified_time", None)
            if modified:
                parts.append(f"Modified: {modified.isoformat()}")
            content = "\n".join(parts)

        passage = content
        char_start = 0
        if chunk_index is not None:
            from app.artifacts.models import ArtifactChunk
            chunk = None
            # Use indexed passage text and offsets when the semantic hit carries provenance.
            try:
                from sqlalchemy import select
                chunk = session.scalar(select(ArtifactChunk).where(
                    ArtifactChunk.artifact_id == artifact.id,
                    ArtifactChunk.chunk_index == int(chunk_index),
                ))
            except Exception:
                chunk = None
            if chunk is not None:
                passage, char_start = chunk.text, chunk.char_start
        elif content:
            # Keyword-only retrieval still needs an attributable passage, not
            # the beginning of an unrelated long file. Center a bounded window
            # on the earliest literal query term and preserve its source span.
            terms = [term for term in re.findall(r"[\w@.+-]+", self.question) if len(term) > 1]
            match_positions = [
                position
                for term in terms
                if (position := content.casefold().find(term.casefold())) >= 0
            ]
            if match_positions:
                char_start = max(
                    0,
                    min(match_positions) - max(0, self.max_content_chars // 3),
                )
                passage = content[char_start : char_start + self.max_content_chars]
        content = passage[: self.max_content_chars]
        snippet = " ".join(content.split())[:400] or name

        context = {
            "artifact_id": getattr(artifact, "artifact_id", None),
            "name": name,
            "path": path,
            "artifact_type": artifact_type,
            "content_text": content,
            "passage_start": char_start,
            "passage_end": char_start + len(content),
            "retrieval_source": source or "keyword/fallback",
        }
        citation = {
            "db_id": getattr(artifact, "id", None),
            "artifact_id": getattr(artifact, "artifact_id", None),
            "name": name,
            "artifact_type": artifact_type,
            "path": path,
            "score": score,
            "snippet": snippet,
            "chunk_index": chunk_index,
            "char_start": char_start,
            "char_end": char_start + len(content),
            "provenance": "indexed passage" if chunk_index is not None else "artifact text",
        }
        return {"context": context, "citation": citation}

    def _expand_graph(self, session, items: list[dict]) -> list[dict]:
        """Optionally add artifacts linked by recorded entity relationships."""
        try:
            import json

            from sqlalchemy import select

            from app.analysis.models import EntityRelationship
            from app.artifacts.models import Artifact
            from app.evidence.models import Evidence
            seed_ids = {item["citation"].get("db_id") for item in items}
            linked: set[int] = set()
            for row in session.execute(select(EntityRelationship).where(
                EntityRelationship.case_id == self.case_id
            )).scalars():
                try:
                    ids = set(json.loads(row.artifact_ids_json or "[]"))
                except (TypeError, ValueError):
                    continue
                if ids & seed_ids:
                    linked.update(ids - seed_ids)
            if not linked:
                return items
            rows = session.execute(select(Artifact).join(
                Evidence, Evidence.id == Artifact.evidence_id
            ).where(Artifact.id.in_(linked), Artifact.case_id == self.case_id,
                    Evidence.removed_at.is_(None)).limit(10)).scalars()
            for artifact in rows:
                item = self._as_item(session, artifact, None, source="graph expansion")
                item["citation"]["provenance"] = "investigator-enabled entity graph expansion"
                items.append(item)
        except Exception:
            pass
        return items[:self.max_artifacts + 10]

    def _generate(self, context_artifacts: list[dict], mode: str = "analysis") -> str:
        config = get_config()
        payload = {
            "case_id": self.case_id,
            "question": self.question,
            "context_artifacts": context_artifacts,
            "grounding_guidance": (
                "Answer only from supplied evidence passages. Cite artifact IDs and passage "
                "character offsets for factual claims. State when evidence is insufficient; "
                "identify conflicts explicitly and keep unverified lead hypotheses separate "
                "from observed facts."
            ) if mode != "conversation" else "",
            "mode": mode,
            "case_reference": self.case_reference,
            "case_title": self.case_title,
            "conversation_history": (
                self.conversation_history if mode == "conversation" else []
            ),
            "model": (
                config.ollama.cloud_model
                if config.ollama.provider == "openai"
                else config.ollama.model
            ),
            "provider": config.ollama.provider,
            "api_base_url": config.ollama.cloud_base_url,
            "api_key": cloud_api_key(config),
            "max_tokens": config.ollama.max_tokens,
            "context_window_tokens": config.ollama.context_window_tokens,
            "timeout_seconds": config.ollama.timeout_seconds,
            "temperature": config.ollama.temperature,
        }
        url = f"{config.worker.url}/generate"
        try:
            with httpx.Client(timeout=config.worker.timeout_seconds) as client:
                response = client.post(url, json=payload)
        except httpx.ConnectError as exc:
            raise RuntimeError(
                f"Cannot reach the forensic worker at {config.worker.url}. "
                "Start it, then press Refresh above and ask again."
            ) from exc
        except httpx.TimeoutException as exc:
            raise RuntimeError(
                "The AI request timed out. The model may still be loading; "
                "try again in a moment or use a smaller question."
            ) from exc

        if response.status_code != 200:
            raise RuntimeError(
                f"The worker returned HTTP {response.status_code} for "
                f"{url}."
            )
        try:
            data = response.json()
        except Exception as exc:
            raise RuntimeError(f"The worker returned an invalid response: {exc}") from exc
        if not data.get("success"):
            raise RuntimeError(
                data.get("error") or "The AI model did not return an answer."
            )
        answer = (data.get("answer") or "").strip()
        if not answer:
            raise RuntimeError("The AI model returned an empty answer.")
        return answer

class AIAnalysisPage(ResponsivePage):
    CASE_TOPIC_TERMS = re.compile(
        r"\b(case|evidence|artifact|suspect|device|file|email|timeline|event|hash|"
        r"examin\w*|forensic|report|finding|activity|log|image|disk|partition|"
        r"deleted|browser|account|network|malware|document|docx|pdf|xlsx|pptx|"
        r"photo|metadata|timestamp|custody|"
        r"investigation|investigat\w*)\b",
        re.IGNORECASE,
    )
    def __init__(self, nav=None, parent: QWidget | None = None):
        self.nav = nav
        super().__init__(parent=parent)

    def _setup_layout(self):
        self._status_thread: QThread | None = None
        self._status_worker: StatusCheckWorker | None = None
        self._status_case_id: int | None = None
        self._embedding_download_thread: QThread | None = None
        self._embedding_download_worker: EmbeddingModelPullWorker | None = None
        self._ask_threads: list[QThread] = []
        self._request_seq = 0
        self._active_request: int | None = None
        self._last_exchange: dict | None = None
        self._last_exchange_saved = False
        self._conversation_history: list[dict[str, str]] = []
        self._pending_widget: ChatMessageWidget | None = None
        self._messages: list[QWidget] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(Spacing.LG, Spacing.LG, Spacing.LG, Spacing.LG)
        layout.setSpacing(Spacing.SM)

        # Status strip + one-line explanation of what it means right now.
        self.status_strip = StatusStrip()
        self.status_strip.refresh_requested.connect(self._refresh_status)
        self.status_strip.download_embedding_btn.clicked.connect(self._download_embedding_model)
        layout.addWidget(self.status_strip)

        self.status_hint = QLabel(
            "Checking the local AI services…"
        )
        self.status_hint.setWordWrap(True)
        self.status_hint.setObjectName("AIStatusHint")
        self.status_hint.setFont(QFont(Typography.FONT_FAMILY, Typography.BODY_SM[0]))
        layout.addWidget(self.status_hint)

        # Main chat area
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left: Chat
        chat_container = QWidget()
        chat_layout = QVBoxLayout(chat_container)
        chat_layout.setContentsMargins(0, 0, 0, 0)
        chat_layout.setSpacing(Spacing.MD)

        chat_title = QLabel("AI Assistant")
        chat_title.setFont(QFont(Typography.FONT_FAMILY, Typography.HEADING_MD[0], Typography.HEADING_MD[1]))
        chat_layout.addWidget(chat_title)

        # Chat history
        self.chat_scroll = QScrollArea()
        self.chat_scroll.setWidgetResizable(True)
        self.chat_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.chat_scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        self.chat_container = QWidget()
        self.chat_layout = QVBoxLayout(self.chat_container)
        self.chat_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.chat_layout.setSpacing(Spacing.MD)
        self.chat_layout.setContentsMargins(Spacing.MD, Spacing.MD, Spacing.MD, Spacing.MD)

        self.chat_scroll.setWidget(self.chat_container)
        chat_layout.addWidget(self.chat_scroll, 1)

        # Keep options and actions on separate rows so the chat controls remain
        # usable when the window or citation pane is narrow.
        options_column = QVBoxLayout()
        options_column.setSpacing(Spacing.XS)
        self.graph_expansion_check = QCheckBox("Expand through entity graph")
        self.graph_expansion_check.setToolTip(
            "Include up to 10 active artifacts linked to retrieved artifacts by recorded entity relationships."
        )
        options_column.addWidget(self.graph_expansion_check)
        self.cloud_consent_check = QCheckBox(
            "Allow this case's evidence text to be sent to configured cloud AI"
        )
        self.cloud_consent_check.setToolTip(
            "Per-case consent for sending extracted evidence text to configured cloud chat, "
            "NER, or embedding providers. Consent is saved with the case and can be revoked."
        )
        self.cloud_consent_check.hide()
        self.cloud_consent_check.toggled.connect(self._on_cloud_consent_toggled)
        options_column.addWidget(self.cloud_consent_check)
        chat_layout.addLayout(options_column)

        input_row = QHBoxLayout()
        self.input_edit = QLineEdit()
        self.input_edit.setPlaceholderText(
            "Chat naturally, or ask me to look into this case..."
        )
        self.input_edit.setToolTip(
            "Chat naturally. When you ask about this case, I’ll search its examined evidence. "
            "Press Enter or Send."
        )
        self.input_edit.returnPressed.connect(self._on_send)
        input_row.addWidget(self.input_edit, 1)

        self.send_btn = QPushButton("Send")
        self.send_btn.setToolTip("Send your message to the local AI assistant.")
        self.send_btn.clicked.connect(self._on_send)
        input_row.addWidget(self.send_btn)
        chat_layout.addLayout(input_row)

        action_row = QHBoxLayout()
        action_row.addStretch()
        self.clear_context_btn = QPushButton("Clear Context")
        self.clear_context_btn.setProperty("secondary", True)
        self.clear_context_btn.setToolTip(
            "Clear this case's saved chat transcript and casual-chat memory. "
            "This does not delete case data or evidence."
        )
        self.clear_context_btn.clicked.connect(self._on_clear_context)
        action_row.addWidget(self.clear_context_btn)

        self.save_finding_btn = QPushButton("Save as Draft Finding")
        self.save_finding_btn.setProperty("secondary", True)
        self.save_finding_btn.setToolTip(
            "Store the last answer as a draft, AI-suggested finding with its "
            "cited artifacts. It still needs investigator verification."
        )
        self.save_finding_btn.setEnabled(False)
        self.save_finding_btn.clicked.connect(self._on_save_finding)
        action_row.addWidget(self.save_finding_btn)

        chat_layout.addLayout(action_row)
        splitter.addWidget(chat_container)

        # Right: Citations
        self.citation_panel = CitationPanel()
        splitter.addWidget(self.citation_panel)

        configure_detail_splitter(splitter, preferred_detail_width=340)
        layout.addWidget(splitter, 1)

        self._reset_conversation()

    # ------------------------------------------------------------------
    # Case scope and lifecycle
    # ------------------------------------------------------------------
    def set_case_context(self, context: CaseContext):
        previous = getattr(self.case_context, "case_id", None)
        self.case_context = context
        if previous != getattr(context, "case_id", None):
            self._reset_conversation()
            self._load_saved_conversation()
        config = get_config()
        self.cloud_consent_check.setVisible(
            config.ollama.provider == "openai"
            or config.embeddings.provider == "openai"
        )
        self._load_cloud_consent()
        self._refresh_status()

    def _load_cloud_consent(self) -> None:
        """Load the persisted, case-specific cloud data consent state."""
        from app.auth.models import Case
        from app.db.session import get_session_factory

        session = get_session_factory()()
        try:
            case = session.get(Case, self._case_id) if self._case_id else None
            enabled = bool(case and case.cloud_ai_consent_at)
            self.cloud_consent_check.blockSignals(True)
            self.cloud_consent_check.setChecked(enabled)
            self.cloud_consent_check.blockSignals(False)
        except Exception as exc:
            self.cloud_consent_check.blockSignals(True)
            self.cloud_consent_check.setChecked(False)
            self.cloud_consent_check.blockSignals(False)
            self.status_hint.setText(f"Cloud consent state could not be loaded: {exc}")
        finally:
            session.close()

    def _on_cloud_consent_toggled(self, enabled: bool) -> None:
        """Record or revoke cloud consent for the currently open case."""
        if not self._case_id:
            return
        if enabled:
            answer = QMessageBox.question(
                self,
                "Allow cloud AI for this case?",
                "Extracted evidence text may be sent to the cloud provider selected in Settings "
                "for chat, named-entity analysis, or embeddings. The provider is configured by "
                "your organization, not IDFA. Continue and record consent for this case?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                self.cloud_consent_check.blockSignals(True)
                self.cloud_consent_check.setChecked(False)
                self.cloud_consent_check.blockSignals(False)
                return

        from app.auth.models import Case
        from app.db.session import get_session_factory

        user = None
        getter = getattr(self.nav, "get_current_user", None)
        if callable(getter):
            user = getter()
        if enabled and user is None:
            self.cloud_consent_check.blockSignals(True)
            self.cloud_consent_check.setChecked(False)
            self.cloud_consent_check.blockSignals(False)
            QMessageBox.warning(
                self, "Investigator required",
                "A signed-in investigator is required to record cloud consent.",
            )
            return

        session = get_session_factory()()
        try:
            case = session.get(Case, self._case_id)
            if case is None:
                raise ValueError("The open case no longer exists.")
            if enabled:
                case.cloud_ai_consent_at = datetime.now(timezone.utc)
                case.cloud_ai_consent_by_id = int(user.id)
            else:
                case.cloud_ai_consent_at = None
                case.cloud_ai_consent_by_id = None
            session.commit()
        except Exception as exc:
            session.rollback()
            self.cloud_consent_check.blockSignals(True)
            self.cloud_consent_check.setChecked(not enabled)
            self.cloud_consent_check.blockSignals(False)
            QMessageBox.warning(self, "Cloud consent not saved", str(exc))
        finally:
            session.close()

    def on_page_shown(self):
        """Re-check the services whenever the page is opened."""
        self._refresh_status()

    def shutdown(self) -> None:
        """Stop the status/ask threads so closing the window cannot abort Qt."""
        qt_threads.stop(self._status_thread)
        qt_threads.stop(self._embedding_download_thread)
        for thread in list(self._ask_threads):
            qt_threads.stop(thread, wait_ms=1000)

    def refresh(self):
        self._refresh_status()

    @property
    def _case_id(self) -> int:
        return getattr(self.case_context, "case_id", 0) or 0

    def _reset_conversation(self):
        self._active_request = None
        self._last_exchange = None
        self._last_exchange_saved = False
        self._conversation_history = []
        self._pending_widget = None
        self._clear_chat()
        self.citation_panel.set_citations([])
        self._set_busy(False)

        hint = QLabel(
            "Chat naturally, or ask about this case and I’ll search its examined evidence. "
            "Case-related AI analysis is unverified until you confirm it."
        )
        hint.setWordWrap(True)
        hint.setFont(QFont(Typography.FONT_FAMILY, Typography.BODY_MD[0]))
        hint.setStyleSheet(f"color: {Color.TEXT_SECONDARY.name()};")
        self.chat_layout.addWidget(hint)
        self._messages.append(hint)
        self._hint_widget = hint

    def _chat_service(self):
        from app.ai.chat_service import AIChatService
        from app.db.session import get_session_factory

        return AIChatService(get_session_factory()())

    def _save_chat_message(
        self,
        role: str,
        content: str,
        *,
        mode: str,
        citations: list[dict] | None = None,
    ):
        """Persist one visible message so it survives closing the application."""
        if not self._case_id or not content:
            return
        service = None
        try:
            service = self._chat_service()
            service.add_message(
                self._case_id, role, content, mode=mode, citations=citations
            )
        except Exception as exc:
            QMessageBox.warning(
                self, "Chat History Not Saved",
                f"This message is visible now but could not be saved to the case database:\n{exc}",
            )
        finally:
            if service is not None:
                service.session.close()

    def _load_saved_conversation(self):
        """Restore this case's transcript and casual-chat context from SQLite."""
        if not self._case_id:
            return
        service = None
        try:
            service = self._chat_service()
            messages = service.list_messages(self._case_id)
        except Exception as exc:
            self.status_hint.setText(f"Chat history could not be loaded: {exc}")
            return
        finally:
            if service is not None:
                service.session.close()

        if not messages:
            return
        self._remove_hint()
        casual_history: list[dict[str, str]] = []
        for message in messages:
            role = message["role"]
            content = message.get("content") or ""
            citations = message.get("citations") or []
            # This exact legacy fallback was a canned response, not an AI
            # answer. Keep the database record intact but don't replay it.
            if role == "assistant" and content.startswith(
                "I’ll keep our conversation focused on "
            ):
                continue
            if role == "user":
                self._add_message(content, is_user=True)
            elif role == "assistant":
                self._add_ai_response(content, citations)
            if role in {"user", "assistant"}:
                casual_history.append({"role": role, "content": content})
        self._conversation_history = casual_history[-20:]

    def _on_clear_context(self):
        if not self._case_id:
            self._reset_conversation()
            return
        answer = QMessageBox.question(
            self,
            "Clear Case Chat",
            "Permanently clear this case's saved chat transcript and conversational memory?\n\n"
            "Evidence, artifacts, findings, and reports will not be affected.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        service = None
        try:
            service = self._chat_service()
            service.clear(self._case_id)
        except Exception as exc:
            QMessageBox.critical(self, "Could Not Clear Chat", str(exc))
            return
        finally:
            if service is not None:
                service.session.close()
        self._reset_conversation()

    def _remove_hint(self):
        hint = getattr(self, "_hint_widget", None)
        self._hint_widget = None
        if hint is None:
            return
        self.chat_layout.removeWidget(hint)
        if hint in self._messages:
            self._messages.remove(hint)
        hint.setParent(None)
        hint.deleteLater()

    def _clear_chat(self):
        self._hint_widget = None
        for widget in self._messages:
            widget.setParent(None)
            widget.deleteLater()
        self._messages = []
        while self.chat_layout.count():
            item = self.chat_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()

    def _scroll_to_bottom(self):
        bar = self.chat_scroll.verticalScrollBar()
        bar.setValue(bar.maximum())

    # ------------------------------------------------------------------
    # Status strip
    # ------------------------------------------------------------------
    def _refresh_status(self):
        if self._case_id == 0:
            self.status_strip.set_all_unknown()
            self.status_hint.setText(
                "Open a case to check the AI services for its evidence."
            )
            return
        if self._status_thread is not None:
            return

        self.status_strip.set_all_checking()
        self.status_hint.setText("Checking the local AI services…")
        self.status_strip.refresh_btn.setEnabled(False)
        self._status_case_id = self._case_id

        self._status_thread = QThread()
        self._status_worker = StatusCheckWorker(self._case_id)
        qt_threads.track(self._status_thread)
        self._status_worker.moveToThread(self._status_thread)
        self._status_thread.started.connect(self._status_worker.run)
        self._status_worker.finished.connect(self._on_status_checked)
        self._status_worker.finished.connect(self._status_thread.quit)
        self._status_worker.finished.connect(self._status_worker.deleteLater)
        self._status_thread.finished.connect(self._status_thread.deleteLater)
        self._status_thread.finished.connect(self._clear_status_thread)
        self._status_thread.start()

    def _clear_status_thread(self):
        self._status_thread = None
        self._status_worker = None
        self.status_strip.refresh_btn.setEnabled(True)
        # A case switch during a check leaves the new case showing the old
        # results; run the check again for the case that is open now.
        if self._status_case_id != self._case_id and self._case_id:
            self._refresh_status()

    def _on_status_checked(self, payload: dict):
        if payload.get("case_id") != self._case_id:
            return
        for service in StatusStrip.SERVICES:
            entry = payload.get(service) or {}
            self.status_strip.set_status(
                service,
                entry.get("state", "unknown"),
                entry.get("detail", ""),
                entry.get("tooltip", ""),
            )
        embedding_state = (payload.get("Embedding") or {}).get("state")
        self.status_strip.download_embedding_btn.setVisible(embedding_state == "error")
        self.status_hint.setText(self._status_summary(payload))

    @staticmethod
    def _status_summary(payload: dict) -> str:
        worker = (payload.get("Worker") or {}).get("state")
        ollama = (payload.get("Ollama") or {}).get("state")
        model = (payload.get("Model") or {}).get("state")
        index = (payload.get("Index") or {}).get("state")
        embedding = (payload.get("Embedding") or {}).get("state")
        qdrant = (payload.get("Qdrant") or {}).get("state")

        if worker == "error":
            return (
                "The forensic worker is unreachable, so answers cannot be generated. "
                "Start it, then press Refresh."
            )
        if ollama == "error":
            return (
                "Ollama is offline, so AI-generated replies are unavailable. "
                "Local keyword/semantic search remains available; start Ollama and refresh."
            )
        if model == "error":
            config = get_config()
            return (
                f"Ollama is running but {config.ollama.model} is not pulled, so "
                f"answers cannot be generated. Run: ollama pull {config.ollama.model}"
            )
        if index in ("error", "partial"):
            if embedding == "error":
                return (
                    "The embedding model is not pulled in Ollama, so semantic "
                    "search is unavailable and answers use keyword retrieval."
                )
            return (
                "This case is only partly embedded, so answers combine keyword "
                "and semantic retrieval. Index it on the Artifacts & Search page "
                "for full semantic search."
            )
        if index == "unknown":
            index_detail = (payload.get("Index") or {}).get("detail")
            if index_detail == "no text":
                return (
                    "This case has artifacts but none contain extracted text to embed. "
                    "Keyword and case-context retrieval remain available; run an "
                    "examination that extracts text for semantic search."
                )
            return (
                "No examined artifacts were found for this case yet. Run an "
                "examination before asking questions."
            )
        if embedding == "error" or qdrant == "error":
            return (
                "Semantic search is unavailable, so answers use keyword retrieval "
                "over this case's examined artifacts."
            )
        config = get_config()
        if config.ollama.provider == "openai":
            return (
                f"Cloud AI is ready ({config.ollama.cloud_model}). Evidence context "
                "leaves this machine, so answers are marked unverified for review."
            )
        return (
            "All local AI services are ready. Ask naturally; when you ask about "
            "this case, I’ll use its artifacts and mark the analysis unverified."
        )

    # ------------------------------------------------------------------
    # Chat
    # ------------------------------------------------------------------
    def _set_busy(self, busy: bool):
        self.send_btn.setEnabled(not busy)
        self.send_btn.setText("Thinking…" if busy else "Send")
        self.input_edit.setEnabled(not busy)
        self.save_finding_btn.setEnabled(
            (not busy)
            and self._last_exchange is not None
            and not self._last_exchange_saved
        )

    def _download_embedding_model(self):
        if self._embedding_download_thread is not None:
            return
        config = get_config()
        if config.embeddings.provider == "openai":
            QMessageBox.information(
                self,
                "Cloud embeddings",
                "Cloud embeddings do not need to be pulled. Configure an API key in Settings.",
            )
            return
        model = config.embeddings.model_id
        self.status_strip.download_embedding_btn.setEnabled(False)
        self.status_strip.download_embedding_btn.setText("Pulling…")
        self.status_hint.setText(
            f"Asking Ollama for the {model} embedding model. The offline bundle "
            "already contains it, so this is only needed on a connected machine."
        )
        self._embedding_download_thread = QThread()
        self._embedding_download_worker = EmbeddingModelPullWorker()
        qt_threads.track(self._embedding_download_thread)
        self._embedding_download_worker.moveToThread(self._embedding_download_thread)
        self._embedding_download_thread.started.connect(self._embedding_download_worker.run)
        self._embedding_download_worker.finished.connect(self._on_embedding_model_pulled)
        self._embedding_download_worker.finished.connect(self._embedding_download_thread.quit)
        self._embedding_download_worker.finished.connect(self._embedding_download_worker.deleteLater)
        self._embedding_download_thread.finished.connect(self._embedding_download_thread.deleteLater)
        self._embedding_download_thread.finished.connect(self._clear_embedding_download_thread)
        self._embedding_download_thread.start()

    def _clear_embedding_download_thread(self):
        self._embedding_download_thread = None
        self._embedding_download_worker = None
        self.status_strip.download_embedding_btn.setEnabled(True)
        self.status_strip.download_embedding_btn.setText("Pull Embedding Model")

    def _on_embedding_model_pulled(self, result: dict):
        if result.get("error"):
            QMessageBox.warning(
                self,
                "Embedding model unavailable",
                f"Ollama could not provide the embedding model:\n\n{result['error']}",
            )
            self.status_hint.setText(
                "Embedding model is still unavailable. Check that Ollama is running "
                "and that this machine can reach the model registry, then retry."
            )
            return
        self.status_hint.setText(
            f"{result.get('model')} is ready. Refreshing service status…"
        )
        self._refresh_status()

    def _on_send(self):
        question = self.input_edit.text().strip()
        if not question or self._active_request is not None:
            return
        if self._case_id == 0:
            QMessageBox.warning(
                self, "No case", "Open a case before asking the assistant."
            )
            return

        self.input_edit.clear()
        self._remove_hint()

        # Only explicit case-related messages trigger evidence retrieval.
        # Ordinary conversation is answered naturally without adding case
        # details or forcing the user back to the investigation.
        is_conversation = not self.CASE_TOPIC_TERMS.search(question)
        mode = "conversation" if is_conversation else "analysis"
        self._add_message(question, is_user=True)
        self._save_chat_message("user", question, mode=mode)
        if is_conversation:
            self._last_exchange = None
            self._last_exchange_saved = False
            self.save_finding_btn.setEnabled(False)

        self._pending_widget = ChatMessageWidget(
            "💬 Thinking…" if is_conversation else
            "⏳ Retrieving case artifacts and asking the local model… "
            "a long answer can take a few minutes on a CPU.",
            is_user=False,
        )
        self.chat_layout.addWidget(self._pending_widget)
        self._messages.append(self._pending_widget)
        self._scroll_to_bottom()

        self._request_seq += 1
        token = self._request_seq
        self._active_request = token
        self._set_busy(True)
        self.citation_panel.set_message(
            "Just chatting — no case evidence was retrieved."
            if is_conversation else "Retrieving artifacts for this question…"
        )

        self._ask_thread = QThread()
        self._ask_threads.append(self._ask_thread)
        qt_threads.track(self._ask_thread)
        self._ask_worker = AskWorker(
            self._case_id,
            question,
            token,
            conversation=is_conversation,
            case_reference=getattr(self.case_context, "case_id_str", ""),
            case_title=getattr(self.case_context, "title", ""),
            conversation_history=self._conversation_history,
            expand_graph=self.graph_expansion_check.isChecked(),
            cloud_consent=self.cloud_consent_check.isChecked(),
        )
        self._ask_worker.moveToThread(self._ask_thread)
        self._ask_thread.started.connect(self._ask_worker.run)
        self._ask_worker.finished.connect(self._on_answer)
        self._ask_worker.finished.connect(self._ask_thread.quit)
        self._ask_worker.finished.connect(self._ask_worker.deleteLater)
        self._ask_thread.finished.connect(self._ask_thread.deleteLater)
        self._ask_thread.finished.connect(
            lambda thread=self._ask_thread: self._forget_ask_thread(thread)
        )
        self._ask_thread.start()

    def _forget_ask_thread(self, thread: QThread):
        """Drop a finished request thread so it can be collected."""
        if thread in self._ask_threads:
            self._ask_threads.remove(thread)

    def _on_answer(self, result: dict):
        if result.get("token") != self._active_request:
            return
        self._active_request = None
        self._remove_pending()
        self._set_busy(False)

        citations = result.get("citations") or []
        error = result.get("error")
        if error:
            error_message = f"⚠️ {error}"
            self._add_message(error_message, is_user=False)
            self._save_chat_message(
                "assistant", error_message,
                mode=result.get("mode") or "analysis",
                citations=citations,
            )
            self.citation_panel.set_citations(citations)
            return

        answer = result.get("answer", "")
        self._add_ai_response(answer, citations)
        self._save_chat_message(
            "assistant", answer,
            mode=result.get("mode") or "analysis",
            citations=citations,
        )
        self._conversation_history.extend([
            {"role": "user", "content": result.get("question", "")},
            {"role": "assistant", "content": answer},
        ])
        self._conversation_history = self._conversation_history[-20:]
        if result.get("mode") == "conversation":
            self.citation_panel.set_message(
                "Just chatting — no case evidence was retrieved."
            )
            self._last_exchange = None
            self._last_exchange_saved = False
            self._set_busy(False)
            return
        self._last_exchange = {
            "case_id": result.get("case_id"),
            "question": result.get("question", ""),
            "answer": result.get("answer", ""),
            "citations": citations,
        }
        self._last_exchange_saved = False
        self.save_finding_btn.setEnabled(True)

    def _remove_pending(self):
        widget = self._pending_widget
        self._pending_widget = None
        if widget is None:
            return
        self.chat_layout.removeWidget(widget)
        if widget in self._messages:
            self._messages.remove(widget)
        widget.setParent(None)
        widget.deleteLater()

    def _add_message(self, text: str, is_user: bool):
        msg_widget = ChatMessageWidget(text, is_user)
        self.chat_layout.addWidget(msg_widget)
        self._messages.append(msg_widget)
        self._scroll_to_bottom()

    def _add_ai_response(self, text: str, citations: list):
        names = [
            str(cite.get("name") or cite.get("artifact_id") or "")
            for cite in citations
        ]
        msg_widget = ChatMessageWidget(
            text, is_user=False, citations=[name for name in names if name]
        )
        self.chat_layout.addWidget(msg_widget)
        self._messages.append(msg_widget)
        self.citation_panel.set_citations(citations)
        self._scroll_to_bottom()

    # ------------------------------------------------------------------
    # Findings
    # ------------------------------------------------------------------
    def _resolve_user(self, session):
        """Find the signed-in investigator in ``session``.

        The navigation controller holds a detached ``User`` (its session was
        closed after login), so re-load it by id and fall back to the seeded
        administrator like the Findings page does.
        """
        from app.auth.models import User

        user_id = None
        nav = getattr(self, "nav", None)
        if nav is not None and hasattr(nav, "get_current_user"):
            try:
                user_id = getattr(nav.get_current_user(), "id", None)
            except Exception:
                user_id = None
        if user_id is not None:
            user = session.get(User, user_id)
            if user is not None:
                return user
        return session.get(User, 1)

    def _on_save_finding(self):
        if self._last_exchange is None:
            QMessageBox.information(
                self, "Nothing to save",
                "Ask the assistant a question first; its answer is what gets "
                "saved as a draft finding.",
            )
            return
        if self._last_exchange_saved:
            QMessageBox.information(
                self, "Already saved",
                "This answer was already saved as a draft finding.",
            )
            return
        if self._case_id == 0:
            return

        try:
            from app.db.session import get_session_factory
            from app.findings.models import FindingOrigin
            from app.findings.service import FindingService

            session = get_session_factory()()
        except Exception as exc:
            QMessageBox.critical(self, "Save failed", f"Cannot open the database: {exc}")
            return

        finding_ref = None
        try:
            user = self._resolve_user(session)
            if user is None:
                QMessageBox.warning(
                    self, "Not signed in",
                    "A finding needs a signed-in investigator.",
                )
                return

            question = self._last_exchange["question"]
            answer = self._last_exchange["answer"]
            title = question if len(question) <= 80 else question[:77] + "..."
            service = FindingService(session)
            finding = service.create_finding(
                case_id=self._case_id,
                title=title,
                description=answer,
                conclusion=(
                    "AI-assisted draft. The investigator must verify this "
                    "answer against the cited evidence before relying on it."
                ),
                created_by=user,
                origin=FindingOrigin.AI_SUGGESTED,
                ai_question=question,
                ai_answer=answer,
                ai_citations=self._last_exchange["citations"],
                ai_model=get_config().ollama.model,
            )
            # Link only artifacts that still exist; citations are unique per
            # answer, so a duplicate link cannot occur for a new finding.
            from app.artifacts.models import Artifact

            linked: set[int] = set()
            for cite in self._last_exchange["citations"]:
                artifact_pk = cite.get("db_id")
                if artifact_pk is None or artifact_pk in linked:
                    continue
                if session.get(Artifact, artifact_pk) is None:
                    continue
                service.link_artifact(
                    finding.id, artifact_pk,
                    relevance="supports", cited_in_ai=True,
                )
                linked.add(artifact_pk)
            session.commit()
            finding_ref = finding.finding_id
        except Exception as exc:
            session.rollback()
            QMessageBox.critical(
                self, "Save failed", f"Failed to create the draft finding: {exc}"
            )
            return
        finally:
            session.close()

        self._last_exchange_saved = True
        self._set_busy(False)

        # Keep the Findings page in step if it is already built.
        try:
            findings_page = getattr(getattr(self.nav, "case_shell", None), "findings_page", None)
            if findings_page is not None and hasattr(findings_page, "refresh"):
                findings_page.refresh()
        except Exception:
            pass

        QMessageBox.information(
            self, "Draft finding saved",
            f"Saved {finding_ref} as a draft, AI-suggested finding with "
            f"{len(self._last_exchange['citations'])} linked artifact(s).\n\n"
            "Open the Findings page to review and verify it.",
        )
