"""Report provenance uses evidence relationships, not database-key guesses."""
from datetime import datetime
from enum import Enum
from types import SimpleNamespace as NS

from reportlab.platypus import Paragraph, Table

from app.reports.generator import ReportGenerator


class Value(Enum):
    FILE = "file"
    INDEXED = "indexed"
    MANUAL = "manual"
    VERIFIED = "verified"


def artifact(evidence):
    return NS(artifact_id="ART-7", artifact_type=Value.FILE, name="message.txt",
              source_path="/message.txt", source_size=12, created_time=None,
              index_status=Value.INDEXED, evidence_id=42, evidence=evidence, case_id=1)


def test_artifact_table_labels_linked_removed_and_unavailable_evidence(monkeypatch):
    monkeypatch.setattr("app.reports.generator.object_session", lambda _: None)
    generator = ReportGenerator()
    items = [artifact(NS(evidence_id="EV-100", name="Disk & image", removed_at=None, case_id=1)),
             artifact(NS(evidence_id="EV-200", name="Old disk", removed_at=datetime.now(), case_id=1)),
             artifact(None)]
    story = generator._build_artifacts_section(items)
    table = [item for item in story if isinstance(item, Table)][-1]
    labels = [row[3].getPlainText() for row in table._cellvalues[1:]]
    assert labels == ["EV-100 - Disk & image | Device associations unavailable /message.txt",
                      "EV-200 - Old disk (removed from case) | Device associations unavailable /message.txt",
                      "Evidence unavailable /message.txt"]
    assert all("42" not in label for label in labels)


def test_finding_sources_include_evidence_and_handle_missing_links(monkeypatch):
    monkeypatch.setattr("app.reports.generator.object_session", lambda _: None)
    generator = ReportGenerator()
    finding = NS(finding_id="F-1", status=Value.VERIFIED, origin=Value.MANUAL,
                 created_by=None, created_at=None, verified_at=None,
                 description="Description", conclusion=None,
                 artifact_links=[
                     NS(artifact=artifact(NS(evidence_id="EV-3", name="Phone", removed_at=datetime.now(), case_id=1)),
                        notes=None, relevance="supporting"),
                     NS(artifact=artifact(None), notes=None, relevance="context"),
                     NS(artifact=None, notes=None, relevance="context"),
                 ])
    text = "\n".join(p.getPlainText() for p in generator._render_finding(finding)
                     if isinstance(p, Paragraph))
    assert "EV-3 - Phone (removed from case)" in text
    assert "evidence: Evidence unavailable" in text
    assert "Artifact unavailable" in text


def test_explicit_device_associations_and_cross_case_guard(monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE physical_devices (id INTEGER, case_id INTEGER, label TEXT)")
        connection.exec_driver_sql("CREATE TABLE device_evidence_links (device_id INTEGER, evidence_id INTEGER)")
        connection.exec_driver_sql("INSERT INTO physical_devices VALUES (10, 1, 'Phone'), (11, 2, 'Other case')")
        connection.exec_driver_sql("INSERT INTO device_evidence_links VALUES (10, 42), (11, 42)")
    with Session(engine) as session:
        monkeypatch.setattr("app.reports.generator.object_session", lambda _: session)
        ev = NS(id=42, case_id=1, evidence_id="EV-1", name="Image", removed_at=None)
        label = ReportGenerator._artifact_evidence_label(artifact(ev))
        assert "Investigator-associated device(s): record ID 10 - Phone" in label
        assert "Other case" not in label
        ev.case_id = 2
        assert ReportGenerator._artifact_evidence_label(artifact(ev)) == "Evidence unavailable"
