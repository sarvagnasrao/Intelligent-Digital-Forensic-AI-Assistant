"""Regression coverage for report provenance boundaries."""
from enum import Enum
from types import SimpleNamespace as NS

from reportlab.platypus import Paragraph, Table

from app.reports.generator import ReportGenerator


class Value(Enum):
    VERIFIED = "verified"
    INVESTIGATOR = "investigator"
    SHA256 = "sha256"


def test_finding_does_not_disclose_cross_case_artifact():
    foreign = NS(case_id=2, artifact_id="SECRET-ID", name="secret filename")
    finding = NS(case_id=1, finding_id="F-1", status=Value.VERIFIED,
                 origin=Value.INVESTIGATOR, created_by=None, created_at=None,
                 verified_at=None, description="Finding", conclusion=None,
                 artifact_links=[NS(artifact=foreign, notes=None, relevance="supports")])
    text = "\n".join(p.getPlainText() for p in ReportGenerator()._render_finding(finding)
                     if isinstance(p, Paragraph))
    assert "Artifact unavailable" in text
    assert "SECRET-ID" not in text
    assert "secret filename" not in text


def test_integrity_does_not_promote_computed_hash_to_reference():
    computed = NS(is_reference=False, algorithm=Value.SHA256, hash_value="computed-digest",
                  match_result=True)
    evidence = NS(evidence_id="EV-1", name="Image", hashes=[computed])
    story = ReportGenerator()._build_integrity_section([evidence])
    table = next(item for item in story if isinstance(item, Table))
    row = [cell.getPlainText() for cell in table._cellvalues[1]]
    assert row[2] == "No reference hash recorded"
    assert row[3] == "Not verified"
    assert "computed-digest" not in " ".join(row)
