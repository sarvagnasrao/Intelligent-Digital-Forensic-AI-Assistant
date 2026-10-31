"""Safety and reporting checks: no network or model invocation."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

PATH = Path(__file__).parent / "demo_case" / "harbor_fiction" / "benchmark_ai.py"
spec = importlib.util.spec_from_file_location("harbor_benchmark", PATH)
bench = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bench)


def config():
    return SimpleNamespace(ollama=SimpleNamespace(provider="ollama", host="http://127.0.0.1:11434"),
                           embeddings=SimpleNamespace(provider="ollama"),
                           worker=SimpleNamespace(url="http://127.0.0.1:8000"),
                           qdrant=SimpleNamespace(url="http://127.0.0.1:6333"))


def test_opt_in_and_local_guards(capsys):
    assert bench.main([]) == 0
    assert "--run" in capsys.readouterr().out
    with pytest.raises(SystemExit):
        bench.main(["--run", "--case-id", "1"])
    cfg = config()
    bench.validate_config(cfg)
    cfg.embeddings.provider = "openai"
    with pytest.raises(ValueError):
        bench.validate_config(cfg)
    cfg = config()
    cfg.worker.url = "http://example.com:8000"
    with pytest.raises(ValueError):
        bench.validate_config(cfg)


def test_retrieval_generation_and_citation_observation():
    artifact = SimpleNamespace(artifact_id="ART-0001-0001", name="NOTE.TXT", source_path="/NOTE.TXT")
    context = {"artifact_id": artifact.artifact_id, "name": "NOTE.TXT", "path": "/NOTE.TXT",
               "artifact_type": "file", "content_warning": "", "retrieval_source": "keyword",
               "content_text": bench.TEXTS["NOTE.TXT"], "passage_start": 0, "passage_end": len(bench.TEXTS["NOTE.TXT"])}
    class Worker:
        def _retrieve(self, session):
            return [{"context": context}]
        def _generate(self, items):
            assert items == [context]
            return "Claim [1] without an artifact ID", [{"artifact_id": "ART-1"}]
    ticks = iter([1., 2., 3., 5.])
    result = bench.measure(Worker(), None, {artifact.artifact_id: artifact}, lambda: next(ticks))
    assert result["total_seconds"] == 4
    assert result["generation_seconds"] == 2
    assert result["validation_seconds"] == 1
    assert result["supplied_source_ids"] == [artifact.artifact_id]
    assert result["answer_literal_supplied_ids"] == []
    assert result["answer_bracket_markers"] == ["[1]"]
    context["content_text"] = "private"
    with pytest.raises(ValueError):
        bench.measure(Worker(), None, {artifact.artifact_id: artifact})


def test_no_hits_skip_generation():
    class Worker:
        def _retrieve(self, session):
            return []
        def _generate(self, items):
            raise AssertionError("generation must not run")
    assert "error" in bench.measure(Worker(), None, {})


def test_case_validation_rejects_extra_or_modified_artifacts(tmp_path, monkeypatch):
    import hashlib

    image = tmp_path / "image.img"
    image.write_bytes(b"fictional")
    monkeypatch.setattr(bench, "IMAGE_SHA256", hashlib.sha256(b"fictional").hexdigest())
    evidence = SimpleNamespace(id=1, removed_at=None, stored_path=str(image), source_path="")
    artifacts = [SimpleNamespace(id=i, artifact_id=f"ART-0001-{i:04d}", name=name,
                                 artifact_type="file", content_text=text, evidence_id=1, source_path="/" + name)
                 for i, (name, text) in enumerate(bench.TEXTS.items(), 1)]
    class Rows:
        def __init__(self, values):
            self.values = values
        def all(self):
            return self.values
    class Session:
        def __init__(self, groups):
            self.groups = iter(groups)
        def scalars(self, query):
            return Rows(next(self.groups))
    assert len(bench.validate_case(Session([[evidence], artifacts, []]), 1)) == 4
    extra = SimpleNamespace(id=9, name="$MFT", content_text=None)
    assert len(bench.validate_case(Session([[evidence], artifacts + [extra], []]), 1)) == 4
    artifacts[0].artifact_id = "ART-0001-PRIVATE"
    with pytest.raises(ValueError):
        bench.validate_case(Session([[evidence], artifacts, []]), 1)
    artifacts[0].artifact_id = "ART-0001-0001"
    artifacts[0].artifact_type = "image"
    with pytest.raises(ValueError):
        bench.validate_case(Session([[evidence], artifacts, []]), 1)
    artifacts[0].artifact_type = "file"
    artifacts[0].content_text = "real or unexpected content"
    with pytest.raises(ValueError):
        bench.validate_case(Session([[evidence], artifacts, []]), 1)
    with pytest.raises(ValueError):
        bench.validate_case(Session([[evidence], artifacts + [artifacts[0]], []]), 1)


@pytest.mark.parametrize("field,value", [
    ("artifact_type", "private"), ("content_warning", "private"),
    ("retrieval_source", "private"), ("extra", "private"),
    ("passage_start", -1), ("passage_end", 99999),
])
def test_unexpected_context_never_reaches_generation(field, value):
    artifact = SimpleNamespace(artifact_id="ART-0001-0001", name="NOTE.TXT", source_path="/NOTE.TXT")
    text = bench.TEXTS[artifact.name]
    context = {"artifact_id": artifact.artifact_id, "name": artifact.name, "path": artifact.source_path,
               "artifact_type": "file", "content_warning": "", "retrieval_source": "keyword",
               "content_text": text, "passage_start": 0, "passage_end": len(text)}
    context[field] = value
    class Worker:
        def _retrieve(self, session):
            return [{"context": context}]
        def _generate(self, items):
            raise AssertionError("unsafe context reached generation")
    with pytest.raises(ValueError):
        bench.measure(Worker(), None, {artifact.artifact_id: artifact})


def test_sqlite_retrieval_guard_and_provenance(tmp_path, monkeypatch, config_home):
    """Real retrieval and guard, with synthetic rows and no service connections."""
    import hashlib
    import asyncio
    import socket

    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from app.artifacts.models import Artifact, ArtifactChunk, ArtifactType
    from app.db import load_all_models
    from app.evidence.models import Evidence
    from app.ui.pages.ai_analysis_page import AskWorker
    import app.artifacts.service as search_module

    def blocked(*args, **kwargs):
        raise AssertionError("network access forbidden in isolated benchmark")

    # Windows event loops construct an internal loopback socketpair. Prepare
    # them before blocking connections; none is used for service traffic.
    loops = [asyncio.new_event_loop() for _ in range(4)]
    monkeypatch.setattr(asyncio, "new_event_loop", lambda: loops.pop())
    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)
    image = tmp_path / "fictional.img"
    image.write_bytes(b"synthetic Harbor fixture")
    monkeypatch.setattr(bench, "IMAGE_SHA256", hashlib.sha256(image.read_bytes()).hexdigest())
    load_all_models()
    engine = create_engine(f"sqlite:///{tmp_path / 'harbor.sqlite'}")
    for table in (Evidence.__table__, Artifact.__table__, ArtifactChunk.__table__):
        table.create(engine)
    try:
        with Session(engine) as session:
            session.add(Evidence(id=1, case_id=1, evidence_id="E-1", name="fictional",
                                 source_path=str(image), registered_by_id=1))
            rows = [Artifact(case_id=1, evidence_id=1, artifact_id=f"ART-0001-{i:04d}",
                             name=name, source_path="/" + name, artifact_type=ArtifactType.FILE,
                             content_text=text)
                    for i, (name, text) in enumerate(bench.TEXTS.items(), 1)]
            session.add_all(rows)
            session.flush()
            text = rows[1].content_text
            start, end = 17, 65
            chunk = ArtifactChunk(case_id=1, artifact_id=rows[1].id, chunk_index=0,
                                  char_start=start, char_end=end, text=text[start:end])
            session.add(chunk)
            session.commit()
            allowed = bench.validate_case(session, 1)
            results = [dict(artifact=rows[0], score=0.8, source="keyword"),
                       dict(artifact=rows[1], score=0.9, source="semantic", chunk_index=0)]
            calls = []

            class Search:
                def __init__(self, actual_session):
                    assert actual_session is session

                async def hybrid_search(self, case_id, question, **limits):
                    assert (case_id, question) == (1, bench.QUESTION)
                    assert limits == {"keyword_limit": 100, "semantic_limit": 100}
                    return results

                async def close(self):
                    calls.append("closed")

            monkeypatch.setattr(search_module, "SearchService", Search)
            worker = AskWorker(1, bench.QUESTION, 0, provider="ollama")
            def generate(contexts):
                calls.append(contexts)
                return "Synthetic answer [1]", [{"artifact_id": rows[0].artifact_id}]
            monkeypatch.setattr(worker, "_generate", generate)
            items = worker._retrieve(session)
            assert [item["context"]["retrieval_source"] for item in items] == ["keyword", "semantic"]
            citation = items[1]["citation"]
            assert (citation["artifact_id"], citation["path"]) == (rows[1].artifact_id, "/REPLY.TXT")
            assert (citation["char_start"], citation["char_end"]) == (start, end)
            assert items[1]["context"]["content_text"] == text[start:end]
            report = bench.measure(worker, session, allowed)
            assert report["supplied_source_ids"] == [rows[0].artifact_id, rows[1].artifact_id]
            assert report["worker_reported_citations"] == [{"artifact_id": rows[0].artifact_id}]
            assert report["answer_bracket_markers"] == ["[1]"]
            assert calls[-1] == [item["context"] for item in items]

            # A search hit outside the validated allowlist must never reach generation.
            outsider = Artifact(case_id=2, evidence_id=1, artifact_id="ART-0002-0001",
                               name="private.txt", source_path="/private.txt",
                               artifact_type=ArtifactType.FILE, content_text="unexpected")
            results[:] = [dict(artifact=outsider, source="keyword")]
            before = len([c for c in calls if isinstance(c, list)])
            with pytest.raises(ValueError, match="unexpected source"):
                bench.measure(worker, session, allowed)
            assert len([c for c in calls if isinstance(c, list)]) == before

            # A corrupted index passage must also be rejected before generation.
            chunk.text = "untrusted passage"
            session.flush()
            results[:] = [dict(artifact=rows[1], source="semantic", chunk_index=0)]
            with pytest.raises(ValueError, match="unexpected context"):
                bench.measure(worker, session, allowed)
            assert len([c for c in calls if isinstance(c, list)]) == before
            with pytest.raises(ValueError, match="Unexpected indexed passage"):
                bench.validate_case(session, 1)
    finally:
        for loop in loops:
            loop.close()
        engine.dispose()
