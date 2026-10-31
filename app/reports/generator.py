"""ReportLab PDF generator for case reports.

Reports are built from a :class:`~app.reports.templates.ReportTemplate`.  The
built-in default template produces a court-oriented report: authority and
scope, examiner declaration, methodology and standards, evidence integrity
hashes, verified findings kept separate from unverified work product,
limitations, a signed certification page, and chain of custody appendices.
"""
from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, Any
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    HRFlowable,
    KeepTogether,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)
from sqlalchemy import select
from sqlalchemy.orm import object_session

from app.config import get_config
from app.devices.models import DeviceEvidenceLink, PhysicalDevice
from app.reports.templates import (
    ReportTemplate,
    build_context,
    get_default_template,
    render_text,
)
from app.util.time import format_local_date

if TYPE_CHECKING:
    from app.artifacts.models import Artifact
    from app.audit.models import AuditEvent
    from app.auth.models import Case, User
    from app.evidence.models import Evidence
    from app.examination.models import ExaminationJob
    from app.findings.models import Finding

ACCENT = "#2563EB"
INK = "#1E293B"
MUTED = "#64748B"
RULE = "#E2E8F0"


def _rich(text: Any) -> str:
    """Escape text for ReportLab and support **bold** / *italic* markup."""
    value = escape(str(text or ""))
    value = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", value)
    value = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"<i>\1</i>", value)
    return value


def _markdown_inline(text: str) -> str:
    """Convert safe inline Markdown to ReportLab Paragraph markup."""
    value = str(text or "")
    code_spans: list[str] = []

    def hold_code(match: re.Match) -> str:
        code_spans.append(f'<font name="Courier">{escape(match.group(1))}</font>')
        return f"IDFAMDCODE{len(code_spans) - 1}END"

    value = re.sub(r"`([^`\n]+)`", hold_code, value)
    value = escape(value)
    value = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", value)
    value = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"<i>\1</i>", value)
    value = re.sub(
        r"\[([^\]]+)\]\((https?://[^)\s]+)\)",
        r'<link href="\2" color="#2563EB">\1</link>',
        value,
    )
    for index, markup in enumerate(code_spans):
        value = value.replace(f"IDFAMDCODE{index}END", markup)
    return value


class NumberedCanvas(canvas.Canvas):
    """Canvas that writes "Page X of Y" footers once the page count is known."""

    def __init__(
        self,
        *args,
        case_id: str = "",
        report_id: str = "",
        organization: str = "",
        classification: str = "",
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self._case_id = case_id
        self._report_id = report_id
        self._organization = organization
        self._classification = classification
        self._page_states: list[dict] = []

    def showPage(self):
        self._page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        total = len(self._page_states)
        for state in self._page_states:
            self.__dict__.update(state)
            self._draw_footer(total)
            super().showPage()
        super().save()

    def _draw_footer(self, total: int) -> None:
        self.saveState()
        y = 1.05 * cm
        font_size = 7.5
        self.setStrokeColor(colors.HexColor(RULE))
        self.setLineWidth(0.5)
        self.line(2 * cm, y + 0.35 * cm, A4[0] - 2 * cm, y + 0.35 * cm)
        self.setFont("Helvetica", font_size)
        self.setFillColor(colors.HexColor(MUTED))
        centre = (
            f"Page {self.getPageNumber()} of {total}"
            f"   |   Case {self._case_id}"
            f"   |   Report {self._report_id}"
        )
        side_limit = max(
            18.0,
            (A4[0] - stringWidth(centre, "Helvetica", font_size)) / 2 - 2 * cm - 8,
        )
        self.drawString(
            2 * cm, y, _fit_text(self._organization, font_size, side_limit)
        )
        self.drawCentredString(A4[0] / 2, y, centre)
        self.drawRightString(
            A4[0] - 2 * cm, y, _fit_text(self._classification, font_size, side_limit)
        )
        self.restoreState()


def _fit_text(value: str, font_size: float, max_width: float) -> str:
    """Trim footer text to the space left beside the centred page line."""
    text = str(value or "")
    if stringWidth(text, "Helvetica", font_size) <= max_width:
        return text
    suffix = "..."
    while text and stringWidth(text + suffix, "Helvetica", font_size) > max_width:
        text = text[:-1]
    return (text.rstrip() + suffix) if text else ""


class ReportGenerator:
    """Generate PDF reports from case data."""

    def __init__(self):
        self.config = get_config()
        self.styles = getSampleStyleSheet()
        self._setup_custom_styles()

    # ------------------------------------------------------------------ styles
    def _add_style(self, name: str, **kwargs) -> None:
        if name not in self.styles:
            self.styles.add(ParagraphStyle(name=name, **kwargs))

    def _setup_custom_styles(self) -> None:
        body = self.styles["Normal"]

        self._add_style(
            "CoverOrg",
            parent=body,
            fontSize=15,
            leading=19,
            alignment=TA_CENTER,
            textColor=colors.HexColor(INK),
            fontName="Helvetica-Bold",
            spaceAfter=4,
        )
        self._add_style(
            "CoverTitle",
            parent=self.styles["Title"],
            fontSize=26,
            leading=32,
            alignment=TA_CENTER,
            spaceAfter=18,
            textColor=colors.HexColor(INK),
        )
        self._add_style(
            "CoverSubtitle",
            parent=body,
            fontSize=13,
            leading=18,
            alignment=TA_CENTER,
            spaceAfter=8,
            textColor=colors.HexColor("#475569"),
        )
        self._add_style(
            "CoverMeta",
            parent=body,
            fontSize=10,
            leading=14,
            alignment=TA_CENTER,
            textColor=colors.HexColor(MUTED),
        )
        self._add_style(
            "CoverClassification",
            parent=body,
            fontSize=11,
            leading=14,
            alignment=TA_CENTER,
            textColor=colors.HexColor("#B91C1C"),
            fontName="Helvetica-Bold",
        )
        self._add_style(
            "SectionHeading",
            parent=self.styles["Heading1"],
            fontSize=16,
            leading=20,
            spaceBefore=0,
            spaceAfter=8,
            textColor=colors.HexColor(INK),
        )
        self._add_style(
            "SubSectionHeading",
            parent=self.styles["Heading2"],
            fontSize=12,
            leading=15,
            spaceBefore=10,
            spaceAfter=4,
            textColor=colors.HexColor("#334155"),
        )
        self._add_style(
            "BodyText2",
            parent=body,
            fontSize=10,
            leading=13.5,
            alignment=TA_LEFT,
            spaceAfter=6,
        )
        self._add_style(
            "SmallNote",
            parent=body,
            fontSize=8.5,
            leading=11,
            alignment=TA_LEFT,
            textColor=colors.HexColor("#475569"),
            spaceAfter=6,
        )
        self._add_style(
            "TableCell",
            parent=body,
            fontSize=9,
            leading=11.5,
            alignment=TA_LEFT,
        )
        self._add_style(
            "TableLabel",
            parent=body,
            fontSize=9,
            leading=11.5,
            alignment=TA_LEFT,
            fontName="Helvetica-Bold",
            textColor=colors.HexColor("#334155"),
        )
        self._add_style(
            "SmallCell",
            parent=body,
            fontSize=7.5,
            leading=9.5,
            alignment=TA_LEFT,
        )
        self._add_style(
            "TableHeader",
            parent=body,
            fontSize=9,
            leading=11,
            alignment=TA_CENTER,
            textColor=colors.white,
            fontName="Helvetica-Bold",
        )
        self._add_style(
            "MonoCell",
            parent=body,
            fontSize=6.5,
            leading=9,
            fontName="Courier",
            textColor=colors.HexColor("#334155"),
        )
        self._add_style(
            "CodeBlock",
            parent=body,
            fontSize=8.5,
            leading=11,
            fontName="Courier",
            leftIndent=8,
            spaceAfter=6,
            textColor=colors.HexColor("#334155"),
        )
        self._add_style(
            "FindingTitle",
            parent=body,
            fontSize=11,
            leading=14,
            fontName="Helvetica-Bold",
            textColor=colors.HexColor(INK),
            spaceBefore=8,
            spaceAfter=4,
        )
        self._add_style(
            "FindingMeta",
            parent=body,
            fontSize=8.5,
            leading=11,
            textColor=colors.HexColor(MUTED),
            spaceAfter=4,
        )
        self._add_style(
            "AIHeading",
            parent=self.styles["Heading3"],
            fontSize=11,
            leading=14,
            spaceBefore=6,
            spaceAfter=3,
            textColor=colors.HexColor(INK),
        )
        self._add_style(
            "AIList",
            parent=self.styles["BodyText2"],
            leftIndent=14,
            firstLineIndent=0,
            spaceAfter=3,
        )
        self._add_style(
            "AIQuote",
            parent=self.styles["BodyText2"],
            leftIndent=12,
            borderColor=colors.HexColor(RULE),
            borderWidth=1,
            borderPadding=5,
            textColor=colors.HexColor(MUTED),
        )
        self._add_style(
            "SignatureBlock",
            parent=body,
            fontSize=10,
            leading=18,
            textColor=colors.HexColor(INK),
        )

    # ------------------------------------------------------------------ public
    def generate_report(
        self,
        case: "Case",
        evidence_list: list["Evidence"],
        examination_jobs: list["ExaminationJob"],
        artifacts: list["Artifact"],
        findings: list["Finding"],
        audit_events: list["AuditEvent"],
        generated_by: "User",
        output_path: str,
        title: str | None = None,
        sections: list[str] | None = None,
        template: ReportTemplate | None = None,
        report_id: str | None = None,
    ) -> dict:
        """Generate a complete PDF report and return its metadata."""
        template = template or get_default_template()
        title = (title or template.report_type or "Forensic Examination Report").strip()
        report_id = report_id or "UNASSIGNED"
        generated_at = datetime.now(timezone.utc)
        examiner = (
            getattr(generated_by, "full_name", None)
            or getattr(generated_by, "username", None)
            or "System"
        )
        context = build_context(
            case=case,
            report_id=report_id,
            template=template,
            examiner=examiner,
            generated_at=generated_at,
            evidence_count=len(evidence_list),
            examination_count=len(examination_jobs),
            artifact_count=len(artifacts),
            finding_count=len(findings),
        )

        selected_sections = template.resolved_sections(sections)
        if not selected_sections:
            selected_sections = ["cover"]

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)

        doc = BaseDocTemplate(
            output_path,
            pagesize=A4,
            leftMargin=2 * cm,
            rightMargin=2 * cm,
            topMargin=2 * cm,
            bottomMargin=2 * cm,
            title=f"{case.case_id} - {title}",
            author=examiner,
            subject=f"Forensic examination report for case {case.case_id}",
            creator="IDFA - Intelligent Digital Forensic Analysis",
        )
        frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="normal")
        doc.addPageTemplates([PageTemplate(id="main", frames=[frame])])

        builders = {
            "cover": lambda: self._build_cover_page(case, title, template, context),
            "authority_scope": lambda: self._build_text_section(
                "Authority, Scope and Purpose", template.authority, context
            ),
            "examiner_declaration": lambda: self._build_declaration_section(
                template, context
            ),
            "case_summary": lambda: self._build_case_summary(case, template, context),
            "methodology": lambda: self._build_methodology_section(template, context),
            "evidence": lambda: self._build_evidence_section(evidence_list),
            "examinations": lambda: self._build_examinations_section(examination_jobs),
            "artifacts": lambda: self._build_artifacts_section(artifacts),
            "findings": lambda: self._build_findings_section(findings),
            "narrative": lambda: self._build_narrative_section(template, context),
            "limitations": lambda: self._build_limitations_section(template),
            "certification": lambda: self._build_certification_section(template, context),
            "integrity": lambda: self._build_integrity_section(evidence_list),
            "audit_trail": lambda: self._build_audit_section(audit_events),
            "custom_sections": lambda: self._build_custom_sections(template, context),
        }

        story: list = []
        for index, key in enumerate(selected_sections):
            builder = builders.get(key)
            if builder is None:
                continue
            story.extend(builder())
            if index < len(selected_sections) - 1:
                story.append(PageBreak())

        doc.build(
            story,
            canvasmaker=partial(
                NumberedCanvas,
                case_id=str(case.case_id),
                report_id=report_id,
                organization=template.organization,
                classification=template.classification,
            ),
        )

        return {
            "file_path": output_path,
            "file_size_bytes": os.path.getsize(output_path),
            "pages": doc.page,
            "sections": selected_sections,
            "template_id": template.template_id,
            "template_name": template.name,
            "template_source": "builtin" if template.builtin else (template.source_path or "uploaded"),
        }

    # --------------------------------------------------------------- utilities
    def _heading(self, title: str, color: str = ACCENT) -> list:
        return [
            Paragraph(_rich(title), self.styles["SectionHeading"]),
            HRFlowable(width="100%", thickness=1.5, color=colors.HexColor(color)),
            Spacer(1, 0.45 * cm),
        ]

    def _paragraphs(self, text: str, style: str = "BodyText2") -> list:
        flowables: list = []
        blocks = re.split(r"\n\s*\n", (text or "").strip())
        for block in blocks:
            lines = [line.strip() for line in block.splitlines() if line.strip()]
            if not lines:
                continue
            content = "<br/>".join(_rich(line) for line in lines)
            flowables.append(Paragraph(content, self.styles[style]))
            flowables.append(Spacer(1, 0.15 * cm))
        return flowables

    def _render_ai_answer(self, text: str) -> list:
        """Render common Markdown blocks used by AI findings into PDF flowables.

        Paragraphs and tables remain splittable by ReportLab, so long answers
        continue cleanly across pages instead of being flattened into one block.
        """
        lines = (text or "").splitlines()
        flowables: list = []
        paragraph: list[str] = []
        index = 0

        def flush_paragraph() -> None:
            if paragraph:
                content = _markdown_inline(" ".join(line.strip() for line in paragraph))
                flowables.append(Paragraph(content, self.styles["BodyText2"]))
                paragraph.clear()

        def is_table_separator(line: str) -> bool:
            cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
            return bool(cells) and all(
                re.fullmatch(r":?-{3,}:?", cell.replace(" ", ""))
                for cell in cells
            )

        def table_cells(line: str) -> list[str]:
            return [cell.strip() for cell in line.strip().strip("|").split("|")]

        while index < len(lines):
            line = lines[index].strip()
            if not line:
                flush_paragraph()
                index += 1
                continue

            if line.startswith("```") or line.startswith("~~~"):
                flush_paragraph()
                fence = line[:3]
                code: list[str] = []
                index += 1
                while index < len(lines) and not lines[index].strip().startswith(fence):
                    code.append(lines[index])
                    index += 1
                code_markup = "<br/>".join(escape(row) or "&#160;" for row in code)
                if code_markup:
                    flowables.append(Paragraph(code_markup, self.styles["CodeBlock"]))
                index += 1
                continue

            if (
                line.startswith("|")
                and index + 1 < len(lines)
                and is_table_separator(lines[index + 1])
            ):
                flush_paragraph()
                headers = table_cells(line)
                rows = [headers]
                index += 2
                while index < len(lines) and lines[index].strip().startswith("|"):
                    cells = table_cells(lines[index])
                    if len(cells) < len(headers):
                        cells.extend([""] * (len(headers) - len(cells)))
                    rows.append(cells[:len(headers)])
                    index += 1
                data = [
                    [
                        Paragraph(
                            _markdown_inline(cell),
                            self.styles["TableHeader"] if row_index == 0
                            else self.styles["SmallCell"],
                        )
                        for cell in row
                    ]
                    for row_index, row in enumerate(rows)
                ]
                column_count = max(1, len(headers))
                table = Table(
                    data,
                    colWidths=[17 * cm / column_count] * column_count,
                    repeatRows=1,
                    hAlign="LEFT",
                    splitByRow=1,
                )
                table.setStyle(TableStyle([
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(ACCENT)),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor(RULE)),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 5),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1),
                     [colors.white, colors.HexColor("#F8FAFC")]),
                ]))
                flowables.extend([table, Spacer(1, 0.15 * cm)])
                continue

            heading = re.match(r"^#{1,6}\s+(.+)$", line)
            if heading:
                flush_paragraph()
                level = len(line) - len(line.lstrip("#"))
                style = "SubSectionHeading" if level <= 2 else "AIHeading"
                flowables.append(Paragraph(_markdown_inline(heading.group(1)), self.styles[style]))
                index += 1
                continue

            if re.fullmatch(r"(?:-{3,}|\*{3,}|_{3,})", line):
                flush_paragraph()
                flowables.append(HRFlowable(
                    width="100%", thickness=0.5, color=colors.HexColor(RULE),
                    spaceBefore=3, spaceAfter=6,
                ))
                index += 1
                continue

            bullet = re.match(r"^[-*+]\s+(.+)$", line)
            numbered = re.match(r"^(\d+)[.)]\s+(.+)$", line)
            quote = re.match(r"^>\s?(.*)$", line)
            if bullet or numbered or quote:
                flush_paragraph()
                if bullet:
                    markup = f"- {_markdown_inline(bullet.group(1))}"
                    style = "AIList"
                elif numbered:
                    markup = f"{numbered.group(1)}. {_markdown_inline(numbered.group(2))}"
                    style = "AIList"
                else:
                    markup = _markdown_inline(quote.group(1))
                    style = "AIQuote"
                flowables.append(Paragraph(markup, self.styles[style]))
                index += 1
                continue

            paragraph.append(line)
            index += 1

        flush_paragraph()
        return flowables

    def _render(self, text: str, context: dict[str, str], style: str = "BodyText2") -> list:
        return self._paragraphs(render_text(text, context), style=style)

    def _meta_table(self, rows: list[list[str]], label_width=4.2 * cm, value_width=10.6 * cm) -> Table:
        data = [
            [
                Paragraph(_rich(label), ParagraphStyle(
                    name="meta-label", fontName="Helvetica-Bold", fontSize=9.5, leading=12,
                    alignment=TA_LEFT, textColor=colors.HexColor("#334155"),
                )),
                Paragraph(_rich(value), ParagraphStyle(
                    name="meta-value", fontName="Helvetica", fontSize=9.5, leading=12,
                    alignment=TA_LEFT, textColor=colors.HexColor("#0F172A"),
                )),
            ]
            for label, value in rows
        ]
        table = Table(data, colWidths=[label_width, value_width])
        table.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("LINEBELOW", (0, 0), (-1, -2), 0.4, colors.HexColor(RULE)),
        ]))
        return table

    def _property_table(
        self, rows: list[list[str]], label_width=4.2 * cm, value_width=12.8 * cm
    ) -> Table:
        """Two-column property/value table whose cells wrap long paths and hashes."""
        data: list = []
        for index, (label, value) in enumerate(rows):
            header = index == 0
            data.append([
                Paragraph(_rich(label), self.styles["TableHeader" if header else "TableLabel"]),
                Paragraph(_rich(value), self.styles["TableHeader" if header else "TableCell"]),
            ])
        table = Table(data, colWidths=[label_width, value_width])
        table.setStyle(self._get_table_style())
        return table

    # ---------------------------------------------------------------- sections
    def _build_cover_page(
        self,
        case: "Case",
        title: str,
        template: ReportTemplate,
        context: dict[str, str],
    ) -> list:
        story: list = [Spacer(1, 1.6 * cm)]
        story.append(Paragraph(_rich(template.organization), self.styles["CoverOrg"]))
        if template.jurisdiction:
            story.append(Paragraph(_rich(template.jurisdiction), self.styles["CoverMeta"]))
        story.append(Spacer(1, 0.5 * cm))
        story.append(HRFlowable(width="70%", thickness=1, color=colors.HexColor("#94A3B8"), hAlign="CENTER"))
        story.append(Spacer(1, 1.0 * cm))
        story.append(Paragraph(_rich(template.classification), self.styles["CoverClassification"]))
        story.append(Spacer(1, 1.6 * cm))
        story.append(Paragraph(_rich(title), self.styles["CoverTitle"]))
        story.append(Paragraph(_rich(f"Case {case.case_id}"), self.styles["CoverSubtitle"]))
        story.append(Paragraph(_rich(case.title), self.styles["CoverSubtitle"]))
        story.append(Spacer(1, 1.6 * cm))

        rows = [
            ["Report number", context["report_id"]],
            ["Prepared for", template.prepared_for],
            ["Examiner", context["examiner"]],
            ["Organisation", template.organization],
            ["Jurisdiction", template.jurisdiction],
            ["Report generated", context["generated_date"]],
            ["Evidence items", context["evidence_count"]],
            ["Examination jobs", context["examination_count"]],
            ["Findings", context["finding_count"]],
            ["Classification", template.classification],
        ]
        story.append(self._meta_table(rows))
        story.append(Spacer(1, 1.2 * cm))
        story.append(HRFlowable(width="100%", thickness=0.8, color=colors.HexColor(RULE)))
        story.append(Spacer(1, 0.4 * cm))
        story.append(Paragraph(
            _rich(
                "Investigator and legal review is required under the applicable jurisdiction's "
                "rules. Admissibility and weight are determined by the court and are not "
                "guaranteed by this report. Missing information must be supplied or identified."
            ),
            ParagraphStyle(
                name="CoverNotice", parent=self.styles["Normal"], fontSize=9,
                leading=12, alignment=TA_CENTER, textColor=colors.HexColor(MUTED),
            ),
        ))
        return story

    def _build_text_section(self, title: str, text: str, context: dict[str, str]) -> list:
        return [*self._heading(title), *self._render(text, context)]

    def _build_declaration_section(self, template: ReportTemplate, context: dict[str, str]) -> list:
        story = self._heading("Examiner Declaration")
        story.extend(self._render(template.declaration, context))
        story.append(Spacer(1, 0.4 * cm))
        story.append(Paragraph("Examiner details", self.styles["SubSectionHeading"]))
        story.append(self._meta_table([
            ["Name", context["examiner"]],
            ["Role", "Digital Forensic Examiner"],
            ["Organisation", template.organization],
            ["Jurisdiction", template.jurisdiction],
            ["Declaration date", context["generated_date"]],
        ]))
        return story

    def _build_case_summary(
        self,
        case: "Case",
        template: ReportTemplate,
        context: dict[str, str],
    ) -> list:
        story = self._heading("Case Summary")
        if case.description:
            story.append(Paragraph("Case description", self.styles["SubSectionHeading"]))
            story.append(Paragraph(_rich(case.description), self.styles["BodyText2"]))
        if case.objective:
            story.append(Paragraph("Investigation scope", self.styles["SubSectionHeading"]))
            story.append(Paragraph(_rich(case.objective), self.styles["BodyText2"]))

        story.append(Paragraph("Case and report details", self.styles["SubSectionHeading"]))
        print_status = str(case.status or "").replace("_", " ").title()
        metrics = [
            ["Report number", context["report_id"]],
            ["Report type", template.report_type],
            ["Case identifier", f"{case.case_id} - {case.title}"],
            ["Case status", print_status],
            ["Priority", str(case.priority or "").capitalize()],
            ["Assigned investigator", case.assignee.full_name if case.assignee else "Unassigned"],
            ["Case created", format_local_date(case.created_at) if case.created_at else "-"],
            ["Last updated", format_local_date(case.updated_at) if case.updated_at else "-"],
            ["Evidence items", context["evidence_count"]],
            ["Examination jobs", context["examination_count"]],
            ["Extracted artifacts", context["artifact_count"]],
            ["Findings recorded", context["finding_count"]],
        ]
        story.append(self._meta_table(metrics))
        return story

    def _build_methodology_section(self, template: ReportTemplate, context: dict[str, str]) -> list:
        story = self._heading("Methodology, Tools and Standards")
        story.extend(self._render(template.methodology, context))
        story.append(Paragraph("Examination environment", self.styles["SubSectionHeading"]))
        tools = [
            ["Item", "Detail"],
            ["Application", f"IDFA {self.config.app.version} (local-first digital forensic analysis)"],
            ["Evidence processing", "IDFA supports pytsk3 / The Sleuth Kit; actual use and version require verification"],
            ["Integrity hashing", "See recorded hash values and verification results"],
            ["Keyword index", "SQLite FTS5 full-text index"],
            ["Semantic index", "Qdrant vector index (optional, local)"],
            [
                "AI assistance",
                (
                    f"Cloud model '{self.config.ollama.cloud_model}' "
                    f"({self.config.ollama.cloud_base_url}) - triage only, unverified"
                    if self.config.ollama.provider == "openai"
                    else f"Local Ollama model '{self.config.ollama.model}' - triage only, unverified"
                ),
            ],
            ["Time standard", "Review displayed timestamps and source time zones"],
            [
                "Network exposure",
                (
                    "Cloud AI is currently configured; actual use requires verification"
                    if self.config.ollama.provider == "openai"
                    else "Local AI is currently configured; actual use requires verification"
                ),
            ],
        ]
        table = Table(tools, colWidths=[4.4 * cm, 12.6 * cm])
        table.setStyle(self._get_table_style())
        story.append(table)
        return story

    def _build_evidence_section(self, evidence_list: list["Evidence"]) -> list:
        story = self._heading("Evidence Inventory and Chain of Custody")
        if not evidence_list:
            story.append(Paragraph("No evidence was registered for this case.", self.styles["BodyText2"]))
            return story

        story.append(Paragraph(
            _rich(
                "The following inventory reflects available case records. Hashes and "
                "verification results are shown where recorded; missing entries require review."
            ),
            self.styles["SmallNote"],
        ))

        for index, ev in enumerate(evidence_list, 1):
            story.append(Paragraph(
                _rich(f"Evidence {index}: {ev.evidence_id} - {ev.name}"),
                self.styles["SubSectionHeading"],
            ))
            ev_data = [
                ["Property", "Value"],
                ["Evidence ID", ev.evidence_id],
                ["Type", ev.evidence_type.value.replace("_", " ").title()],
                ["Source path", ev.source_path],
                ["Stored copy", ev.stored_path or "Not copied"],
                ["Size", self._format_size(ev.size_bytes)],
                ["MIME type", ev.mime_type or "Unknown"],
                ["Status", ev.status.value.replace("_", " ").title()],
                ["Registered", format_local_date(ev.registered_at) if ev.registered_at else "-"],
                ["Registered by", ev.registered_by.full_name if ev.registered_by else "-"],
            ]
            if ev.hashes:
                for hash_row in ev.hashes:
                    status = ""
                    if hash_row.is_reference:
                        if hash_row.match_result is True:
                            status = " - verified, recalculated value matches"
                        elif hash_row.match_result is False:
                            status = " - MISMATCH, recalculated value differs"
                        else:
                            status = " - reference value"
                    ev_data.append([
                        f"{self._algorithm_label(hash_row.algorithm.value)} hash",
                        f"{hash_row.hash_value}{status}",
                    ])
            else:
                ev_data.append(["Hashes", "No hash recorded"])

            table = self._property_table(ev_data)
            story.append(table)
            story.append(Spacer(1, 0.45 * cm))
        return story
    def _build_examinations_section(self, jobs: list["ExaminationJob"]) -> list:
        story = self._heading("Examination Jobs")
        if not jobs:
            story.append(Paragraph("No examination jobs were recorded.", self.styles["BodyText2"]))
            return story

        for job in jobs:
            story.append(Paragraph(_rich(f"Job {job.job_id}"), self.styles["SubSectionHeading"]))
            job_data = [
                ["Property", "Value"],
                ["Job ID", job.job_id],
                ["Operation", job.operation.value.replace("_", " ").title()],
                ["Evidence", job.evidence.name if job.evidence else f"ID:{job.evidence_id}"],
                ["Status", job.status.value.title()],
                ["Progress", f"{job.progress_percent}%"],
                ["Started", format_local_date(job.started_at) if job.started_at else "-"],
                ["Completed", format_local_date(job.completed_at) if job.completed_at else "-"],
                ["Created by", job.created_by.full_name if job.created_by else "-"],
            ]
            if job.error_message:
                job_data.append(["Error", job.error_message])

            table = self._property_table(job_data)
            story.append(table)
            story.append(Spacer(1, 0.3 * cm))

            if job.results:
                story.append(Paragraph("Results summary", self.styles["SubSectionHeading"]))
                for result in job.results:
                    story.append(Paragraph(
                        _rich(f"- {result.result_type}: {result.summary or 'No summary'}"),
                        self.styles["BodyText2"],
                    ))
                    if result.artifact_count:
                        story.append(Paragraph(
                            _rich(f"Artifacts extracted: {result.artifact_count}"),
                            self.styles["SmallNote"],
                        ))
                story.append(Spacer(1, 0.3 * cm))
        return story

    def _build_artifacts_section(self, artifacts: list["Artifact"]) -> list:
        story = self._heading("Extracted Artifacts")
        if not artifacts:
            story.append(Paragraph("No artifacts were extracted.", self.styles["BodyText2"]))
            return story

        type_counts: dict[str, int] = {}
        for artifact in artifacts:
            key = artifact.artifact_type.value
            type_counts[key] = type_counts.get(key, 0) + 1

        story.append(Paragraph("Artifact summary by type", self.styles["SubSectionHeading"]))
        type_data = [["Type", "Count"]]
        for artifact_type, count in sorted(type_counts.items(), key=lambda item: -item[1]):
            type_data.append([artifact_type.replace("_", " ").title(), str(count)])
        type_table = Table(type_data, colWidths=[10 * cm, 3 * cm])
        type_table.setStyle(self._get_table_style())
        story.append(type_table)
        story.append(Spacer(1, 0.45 * cm))

        story.append(Paragraph(
            "Artifact details (first 100 shown)" if len(artifacts) > 100 else "Artifact details",
            self.styles["SubSectionHeading"],
        ))
        headers = ["ID", "Type", "Name", "Evidence / source path", "Size", "Created", "Indexed"]
        rows: list = [[Paragraph(_rich(header), self.styles["TableHeader"]) for header in headers]]
        for artifact in artifacts[:100]:
            values = [
                artifact.artifact_id,
                artifact.artifact_type.value,
                artifact.name,
                f"{self._artifact_evidence_label(artifact)}\n{artifact.source_path or 'N/A'}",
                self._format_size(artifact.source_size or 0),
                format_local_date(artifact.created_time) if artifact.created_time else "-",
                "Yes" if artifact.index_status.value == "indexed" else "No",
            ]
            rows.append([Paragraph(_rich(value), self.styles["SmallCell"]) for value in values])

        table = Table(
            rows,
            colWidths=[2.0 * cm, 2.0 * cm, 2.8 * cm, 4.0 * cm, 1.4 * cm, 2.6 * cm, 1.4 * cm],
            repeatRows=1,
        )
        table.setStyle(self._get_table_style(small=True))
        story.append(table)
        if len(artifacts) > 100:
            story.append(Spacer(1, 0.3 * cm))
            story.append(Paragraph(
                _rich(f"... and {len(artifacts) - 100} more artifacts in the case index."),
                self.styles["SmallNote"],
            ))
        return story

    @staticmethod
    def _artifact_evidence_label(artifact: "Artifact") -> str:
        """Describe the linked evidence, never treating its database key as its public ID."""
        evidence = artifact.evidence
        if evidence is None or evidence.case_id != artifact.case_id:
            return "Evidence unavailable"
        label = f"{evidence.evidence_id} - {evidence.name}"
        if evidence.removed_at is not None:
            label += " (removed from case)"
        session = object_session(evidence)
        if session is None:
            return label + " | Device associations unavailable"
        devices = session.execute(
            select(PhysicalDevice.id, PhysicalDevice.label)
            .join(DeviceEvidenceLink, DeviceEvidenceLink.device_id == PhysicalDevice.id)
            .where(DeviceEvidenceLink.evidence_id == evidence.id,
                   PhysicalDevice.case_id == artifact.case_id)
            .order_by(PhysicalDevice.id)
        ).all()
        if devices:
            label += " | Investigator-associated device(s): " + ", ".join(
                f"record ID {device_id} - {name}" for device_id, name in devices
            )
        else:
            label += " | No associated physical device"
        return label

    def _build_findings_section(self, findings: list["Finding"]) -> list:
        story = self._heading("Findings and Opinions")
        if not findings:
            story.append(Paragraph("No findings were recorded for this case.", self.styles["BodyText2"]))
            return story

        verified = [finding for finding in findings if finding.status.value == "verified"]
        others = [finding for finding in findings if finding.status.value != "verified"]

        if verified:
            story.append(Paragraph(
                f"Verified findings and opinions ({len(verified)})",
                self.styles["SubSectionHeading"],
            ))
            story.append(Paragraph(
                _rich(
                    "The following findings were reviewed and verified by the examiner and "
                    "are relied upon in this report."
                ),
                self.styles["SmallNote"],
            ))
            for finding in verified:
                story.extend(self._render_finding(finding))

        if others:
            story.append(Paragraph(
                f"Work product not verified - not relied upon ({len(others)})",
                self.styles["SubSectionHeading"],
            ))
            story.append(Paragraph(
                _rich(
                    "The following entries are work in progress or were generated with AI "
                    "assistance and have not been verified. They are recorded for "
                    "completeness only and are not relied upon for any opinion in this report."
                ),
                self.styles["SmallNote"],
            ))
            for finding in others:
                story.extend(self._render_finding(finding))
        return story

    def _render_finding(self, finding: "Finding") -> list:
        story: list = [Paragraph(_rich(finding.finding_id), self.styles["FindingTitle"])]
        meta = [
            f"Status: {finding.status.value.replace('_', ' ').title()}",
            f"Origin: {finding.origin.value.replace('_', ' ').title()}",
            f"Created by: {finding.created_by.full_name if finding.created_by else 'Unknown'}"
            f" on {format_local_date(finding.created_at) if finding.created_at else '-'}",
        ]
        if finding.verified_at:
            meta.append(
                f"Verified by: {finding.verified_by.full_name if finding.verified_by else '-'}"
                f" on {format_local_date(finding.verified_at)}"
            )
        story.append(Paragraph(_rich(" | ".join(meta)), self.styles["FindingMeta"]))

        story.append(Paragraph("Description", self.styles["SubSectionHeading"]))
        story.append(Paragraph(_rich(finding.description), self.styles["BodyText2"]))
        if finding.conclusion:
            story.append(Paragraph("Conclusion", self.styles["SubSectionHeading"]))
            story.append(Paragraph(_rich(finding.conclusion), self.styles["BodyText2"]))

        if finding.origin.value == "ai_suggested":
            story.append(Paragraph(
                "AI-assisted material (unverified unless stated above)",
                self.styles["SubSectionHeading"],
            ))
            if finding.ai_question:
                story.append(Paragraph(_rich(f"Question: {finding.ai_question}"), self.styles["CodeBlock"]))
            if finding.ai_answer:
                story.extend(self._render_ai_answer(finding.ai_answer))

        if finding.artifact_links:
            story.append(Paragraph("Supporting artifacts", self.styles["SubSectionHeading"]))
            for link in finding.artifact_links:
                artifact = link.artifact
                note = f" - {link.notes}" if link.notes else ""
                if artifact is None or artifact.case_id != getattr(finding, "case_id", artifact.case_id):
                    story.append(Paragraph(
                        _rich(f"- Artifact unavailable (relevance: {link.relevance}){note}"),
                        self.styles["BodyText2"],
                    ))
                    continue
                story.append(Paragraph(
                    _rich(
                        f"- {artifact.artifact_id}: {artifact.name} "
                        f"(evidence: {self._artifact_evidence_label(artifact)}; "
                        f"relevance: {link.relevance}){note}"
                    ),
                    self.styles["BodyText2"],
                ))
        else:
            story.append(Paragraph("No supporting artifact links recorded.", self.styles["SmallNote"]))
        story.append(Spacer(1, 0.35 * cm))
        return story

    def _build_narrative_section(self, template: ReportTemplate, context: dict[str, str]) -> list:
        if not template.narrative:
            return []
        return self._render(template.narrative, context)

    def _build_limitations_section(self, template: ReportTemplate) -> list:
        story = self._heading("Limitations and Qualifications")
        limitations = template.limitations or getattr(get_config().report, "default_limitations", "")
        if not limitations:
            story.append(Paragraph(
                "The opinions expressed are limited to the material examined and the "
                "information available at the date of this report.",
                self.styles["BodyText2"],
            ))
            return story
        story.extend(self._paragraphs(limitations))
        return story

    def _build_certification_section(self, template: ReportTemplate, context: dict[str, str]) -> list:
        story = self._heading("Certification and Signature")
        story.extend(self._render(template.certification, context))
        story.append(Spacer(1, 0.7 * cm))

        signature_flowables: list = []
        for line in template.signature_lines:
            if not line.strip():
                signature_flowables.append(Spacer(1, 0.5 * cm))
            else:
                signature_flowables.append(Paragraph(
                    _rich(render_text(line, context)),
                    self.styles["SignatureBlock"],
                ))
        signature_flowables.append(Spacer(1, 0.4 * cm))
        signature_flowables.append(Paragraph(
            _rich(
                "Signature and review must be completed by the appropriate persons."
            ),
            self.styles["SmallNote"],
        ))
        story.append(KeepTogether(signature_flowables))
        return story

    def _build_integrity_section(self, evidence_list: list["Evidence"]) -> list:
        story = self._heading("Appendix A - Evidence Integrity (SHA-256)")
        story.append(Paragraph(
            _rich(
                "Reference hashes and recorded verification results are shown below. "
                "A recorded reference alone does not establish that verification occurred."
            ),
            self.styles["SmallNote"],
        ))

        rows: list = [[
            Paragraph("Evidence", self.styles["TableHeader"]),
            Paragraph("Algorithm", self.styles["TableHeader"]),
            Paragraph("Reference hash", self.styles["TableHeader"]),
            Paragraph("Verification", self.styles["TableHeader"]),
        ]]
        for ev in evidence_list:
            references = [h for h in (ev.hashes or []) if h.is_reference]
            if not references:
                rows.append([
                    Paragraph(_rich(f"{ev.evidence_id} - {ev.name}"), self.styles["TableCell"]),
                    Paragraph("-", self.styles["TableCell"]),
                    Paragraph("No reference hash recorded", self.styles["TableCell"]),
                    Paragraph("Not verified", self.styles["TableCell"]),
                ])
                continue
            for hash_row in references:
                if hash_row.match_result is True:
                    verification = "Verified - recalculated value matches"
                elif hash_row.match_result is False:
                    verification = "MISMATCH - recalculation differs"
                else:
                    verification = "Reference recorded"
                rows.append([
                    Paragraph(_rich(f"{ev.evidence_id} - {ev.name}"), self.styles["TableCell"]),
                    Paragraph(_rich(self._algorithm_label(hash_row.algorithm.value)), self.styles["TableCell"]),
                    Paragraph(_rich(hash_row.hash_value), self.styles["MonoCell"]),
                    Paragraph(_rich(verification), self.styles["TableCell"]),
                ])

        if len(rows) == 1:
            story.append(Paragraph("No evidence hashes are recorded for this case.", self.styles["BodyText2"]))
            return story

        table = Table(rows, colWidths=[2.8 * cm, 1.9 * cm, 9.2 * cm, 3.1 * cm], repeatRows=1)
        table.setStyle(self._get_table_style(small=True))
        story.append(table)
        story.append(Spacer(1, 0.4 * cm))
        story.append(Paragraph(
            _rich(
                "A hash match confirms integrity of the stored copy. It does not by itself "
                "establish that the copy was made lawfully or that it is complete; see the "
                "Evidence Inventory and Appendix B."
            ),
            self.styles["SmallNote"],
        ))
        return story

    def _build_audit_section(self, events: list["AuditEvent"]) -> list:
        story = self._heading("Appendix B - Chain of Custody and Audit Log")
        if not events:
            story.append(Paragraph("No audit events were recorded for this case.", self.styles["BodyText2"]))
            return story

        story.append(Paragraph(
            _rich(
                "The following application-level audit log is not a complete physical chain "
                "of custody. Obtain and review external custody and transfer records. "
                "Events are shown in reverse chronological order."
            ),
            self.styles["SmallNote"],
        ))
        rows: list = [[
            Paragraph("Timestamp", self.styles["TableHeader"]),
            Paragraph("Type", self.styles["TableHeader"]),
            Paragraph("Action", self.styles["TableHeader"]),
            Paragraph("Result", self.styles["TableHeader"]),
            Paragraph("Target", self.styles["TableHeader"]),
            Paragraph("User", self.styles["TableHeader"]),
        ]]
        for event in events[:100]:
            target = (
                f"{event.target_type}:{event.target_id}"
                if event.target_type and event.target_id else "-"
            )
            rows.append([
                Paragraph(_rich(format_local_date(event.timestamp) if event.timestamp else "-"), self.styles["TableCell"]),
                Paragraph(_rich(event.event_type), self.styles["TableCell"]),
                Paragraph(_rich(event.action[:80]), self.styles["TableCell"]),
                Paragraph(_rich(event.result), self.styles["TableCell"]),
                Paragraph(_rich(target[:40]), self.styles["TableCell"]),
                Paragraph(_rich(event.user.username if event.user else "System"), self.styles["TableCell"]),
            ])
        table = Table(
            rows,
            colWidths=[2.5 * cm, 2.2 * cm, 4.6 * cm, 2.0 * cm, 3.2 * cm, 2.5 * cm],
            repeatRows=1,
        )
        table.setStyle(self._get_table_style(small=True))
        story.append(table)
        if len(events) > 100:
            story.append(Spacer(1, 0.3 * cm))
            story.append(Paragraph(
                _rich(f"... and {len(events) - 100} earlier events in the case audit log."),
                self.styles["SmallNote"],
            ))
        return story

    def _build_custom_sections(self, template: ReportTemplate, context: dict[str, str]) -> list:
        story: list = []
        for index, section in enumerate(template.custom_sections):
            story.extend(self._heading(section.title, color=INK))
            story.extend(self._render(section.body, context))
            if index < len(template.custom_sections) - 1:
                story.append(Spacer(1, 0.4 * cm))
        return story

    # ------------------------------------------------------------------ tables
    def _get_table_style(self, small: bool = False) -> TableStyle:
        font_size = 8 if small else 9
        return TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(INK)),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), font_size),
            ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
            ("ALIGN", (0, 0), (-1, 0), "CENTER"),
            ("ALIGN", (0, 1), (-1, -1), "LEFT"),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor(RULE)),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8FAFC")]),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LEFTPADDING", (0, 0), (-1, -1), 5),
            ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ])

    @staticmethod
    def _format_size(bytes_val: int | float | None) -> str:
        value = float(bytes_val or 0)
        for unit in ["B", "KB", "MB", "GB", "TB"]:
            if value < 1024:
                return f"{value:.1f} {unit}"
            value /= 1024
        return f"{value:.1f} PB"

    @staticmethod
    def _algorithm_label(value: Any) -> str:
        """Render ``sha256`` as the standard ``SHA-256`` algorithm name."""
        label = str(value or "").upper().replace("-", "").replace("_", "")
        match = re.fullmatch(r"SHA(\d+)", label)
        if match:
            return f"SHA-{match.group(1)}"
        return label or "-"
