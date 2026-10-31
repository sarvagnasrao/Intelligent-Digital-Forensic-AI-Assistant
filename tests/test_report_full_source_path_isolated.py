"""Report source identifiers must not be silently truncated."""
from enum import Enum
from types import SimpleNamespace as NS

from reportlab.platypus import Table

from app.reports.generator import ReportGenerator


class Value(Enum):
    FILE = "file"
    INDEXED = "indexed"


def test_artifact_table_preserves_long_distinct_source_paths_and_names(monkeypatch):
    monkeypatch.setattr("app.reports.generator.object_session", lambda _: None)
    evidence = NS(case_id=1, evidence_id="EV-1", name="Image", removed_at=None)
    prefix = "/" + "directory/" * 12
    items = [
        NS(artifact_id=f"ART-{suffix}", artifact_type=Value.FILE,
           name="n" * 75 + suffix, source_path=prefix + suffix,
           source_size=1, created_time=None, index_status=Value.INDEXED,
           evidence=evidence, case_id=1)
        for suffix in ("first", "second")
    ]
    tables = [flowable for flowable in ReportGenerator()._build_artifacts_section(items)
              if isinstance(flowable, Table)]
    rows = tables[-1]._cellvalues[1:]
    for row, item in zip(rows, items):
        assert row[2].getPlainText() == item.name
        assert item.source_path in row[3].getPlainText()
