"""Reports service for PDF generation and report templates."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.artifacts.models import Artifact
from app.audit.models import AuditEvent
from app.auth.models import User
from app.cases.models import Case
from app.config import get_config
from app.evidence.models import Evidence
from app.examination.models import ExaminationJob
from app.findings.models import Finding
from app.reports.generator import ReportGenerator
from app.reports.models import Report, ReportFormat, ReportStatus
from app.reports.templates import (
    BUILTIN_DEFAULT_ID,
    ReportTemplate,
    TemplateError,
    TemplateStore,
)


class ReportService:
    """Service for generating, storing, and templating case reports."""

    def __init__(self, session: Session):
        self.session = session
        self.config = get_config()
        self.generator = ReportGenerator()
        self.template_store = TemplateStore()
        configured = getattr(self.config.report, "default_template_id", "") or BUILTIN_DEFAULT_ID
        self.default_template_id = configured

    # ------------------------------------------------------------- templates
    def list_templates(self) -> list[ReportTemplate]:
        """Return the built-in court template and every uploaded template."""
        return self.template_store.list_templates()

    def default_template(self) -> ReportTemplate:
        """Return the configured default template, falling back to the built-in one."""
        try:
            return self.template_store.get_template(self.default_template_id)
        except TemplateError:
            return self.template_store.get_template(BUILTIN_DEFAULT_ID)

    def get_template(self, template_id: str | None = None) -> ReportTemplate:
        if not template_id:
            return self.default_template()
        return self.template_store.get_template(template_id)

    def import_template(self, path: str | Path) -> ReportTemplate:
        """Validate and store an investigator supplied template."""
        return self.template_store.import_template(path)

    def delete_template(self, template_id: str) -> bool:
        return self.template_store.delete_template(template_id)

    def export_template(self, template_id: str, destination: str | Path) -> Path:
        """Write a template (including the built-in default) to a JSON file."""
        template = self.get_template(template_id)
        return self.template_store.write_template(template, destination)

    # --------------------------------------------------------------- reports
    def _next_report_id(self, case_id: int) -> str:
        """Build a report ID that is unique within the case.

        The timestamp alone is not enough: generating two reports in the same
        second used to hit the ``(case_id, report_id)`` unique constraint.
        """
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        base = f"RPT-{case_id:04d}-{stamp}"
        candidate = base
        suffix = 1
        while self.session.execute(
            select(Report.id).where(
                Report.case_id == case_id, Report.report_id == candidate
            )
        ).first() is not None:
            suffix += 1
            candidate = f"{base}-{suffix}"
        return candidate

    def generate_report(
        self,
        case_id: int,
        title: str,
        format: ReportFormat = ReportFormat.PDF,
        generated_by: User | None = None,
        sections: list[str] | None = None,
        template_id: str | None = None,
    ) -> Report:
        """Generate a report for a case using a report template."""
        case = self.session.get(Case, case_id)
        if not case:
            raise ValueError(f"Case {case_id} not found")

        template = self.get_template(template_id)

        # Generate report ID
        report_id = self._next_report_id(case_id)

        # Determine output path
        output_dir = Path(self.config.app.data_dir) / "reports" / str(case_id)
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"{report_id}.pdf"

        # Create report record
        report = Report(
            report_id=report_id,
            case_id=case_id,
            title=title,
            format=format,
            status=ReportStatus.GENERATING,
            generated_by_id=generated_by.id if generated_by else 1,
        )
        self.session.add(report)
        try:
            self.session.flush()
        except Exception:
            self.session.rollback()
            raise

        try:
            # Fetch all data
            # Removed evidence is a tombstone: it stays in the database for the
            # case history but must not appear in the report as case evidence.
            evidence_list = list(self.session.execute(
                select(Evidence).where(
                    Evidence.case_id == case_id,
                    Evidence.removed_at.is_(None),
                )
            ).scalars().all())

            examination_jobs = list(self.session.execute(
                select(ExaminationJob).where(ExaminationJob.case_id == case_id)
            ).scalars().all())

            artifacts = list(self.session.execute(
                select(Artifact).where(Artifact.case_id == case_id)
            ).scalars().all())

            findings = list(self.session.execute(
                select(Finding).where(Finding.case_id == case_id)
            ).scalars().all())

            audit_events = list(self.session.execute(
                select(AuditEvent).where(AuditEvent.case_id == case_id)
                .order_by(AuditEvent.timestamp.desc())
            ).scalars().all())

            # Generate PDF
            result = self.generator.generate_report(
                case=case,
                evidence_list=evidence_list,
                examination_jobs=examination_jobs,
                artifacts=artifacts,
                findings=findings,
                audit_events=audit_events,
                generated_by=generated_by or User(id=1, full_name="System"),
                output_path=str(output_path),
                title=title,
                sections=sections,
                template=template,
                report_id=report_id,
            )

            # Update report record
            report.status = ReportStatus.COMPLETED
            report.file_path = result["file_path"]
            report.file_size_bytes = result["file_size_bytes"]
            report.completed_at = datetime.now(timezone.utc)
            report.included_sections_json = json.dumps({
                "sections": result.get("sections", []),
                "template_id": result.get("template_id", template.template_id),
                "template_name": result.get("template_name", template.name),
                "template_source": result.get("template_source", ""),
            })
            report.finding_ids_json = json.dumps([f.finding_id for f in findings])
            report.artifact_ids_json = json.dumps([a.artifact_id for a in artifacts])

            self.session.commit()
            return report

        except Exception as e:
            report.status = ReportStatus.FAILED
            report.error_message = str(e)
            report.completed_at = datetime.now(timezone.utc)
            self.session.commit()
            raise

    def get_report(self, report_id: int) -> Report | None:
        return self.session.get(Report, report_id)

    def get_report_by_report_id(self, case_id: int, report_id: str) -> Report | None:
        stmt = select(Report).where(Report.case_id == case_id, Report.report_id == report_id)
        return self.session.execute(stmt).scalar_one_or_none()

    def list_reports(self, case_id: int) -> list[Report]:
        stmt = select(Report).where(Report.case_id == case_id).order_by(Report.generated_at.desc())
        return list(self.session.execute(stmt).scalars().all())

    def delete_report(self, report_id: int) -> bool:
        report = self.get_report(report_id)
        if not report:
            return False
        # Delete file if exists
        if report.file_path and Path(report.file_path).exists():
            Path(report.file_path).unlink()
        self.session.delete(report)
        self.session.flush()
        return True
