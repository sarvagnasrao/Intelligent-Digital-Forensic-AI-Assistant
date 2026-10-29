"""Report templates for case reports.

The application ships a court-oriented default template and lets investigators
import their laboratory's own template.  JSON templates can override every
heading, paragraph and section order; text, Markdown, HTML and Word templates
are treated as a narrative that is rendered with the same placeholders.

All template text is plain text with ``{{ placeholder }}`` substitutions so it
can be rendered into the PDF without executing arbitrary code.
"""
from __future__ import annotations

import json
import re
import zipfile
from dataclasses import dataclass, field, replace
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

import jinja2
from jinja2 import meta

from app.config import get_config

TEMPLATE_FORMAT = "idfa-report-template"
TEMPLATE_VERSION = 1
BUILTIN_DEFAULT_ID = "court-admissible-v1"

#: Section keys in the order the reports page offers them.  A template chooses
#: which of these appear and in what order.
SECTION_LABELS: dict[str, str] = {
    "cover": "Cover page",
    "authority_scope": "Authority, scope and purpose",
    "examiner_declaration": "Examiner declaration",
    "case_summary": "Case summary",
    "methodology": "Methodology, tools and standards",
    "evidence": "Evidence inventory and chain of custody",
    "examinations": "Examination jobs",
    "artifacts": "Extracted artifacts",
    "findings": "Findings and opinions",
    "narrative": "Examiner narrative (uploaded template)",
    "limitations": "Limitations and qualifications",
    "certification": "Certification and signature",
    "integrity": "Appendix A - evidence integrity hashes",
    "audit_trail": "Appendix B - chain of custody audit log",
    "custom_sections": "Additional sections from template",
}

VALID_SECTIONS = tuple(SECTION_LABELS)

#: Placeholders investigators may use in uploaded templates.
PLACEHOLDERS: dict[str, str] = {
    "case_id": "Human readable case identifier, e.g. CASE-0001",
    "case_title": "Case title",
    "case_status": "Case status",
    "case_priority": "Case priority",
    "report_id": "Generated report number, e.g. RPT-0001-20260101-120000",
    "report_type": "Report type from the template",
    "classification": "Classification marking, e.g. CONFIDENTIAL",
    "organization": "Laboratory / organisation name",
    "jurisdiction": "Jurisdiction of the examining laboratory",
    "prepared_for": "Recipient, e.g. Court / Investigating Agency",
    "examiner": "Full name of the examiner generating the report",
    "generated_date": "Report generation date and time in UTC",
    "evidence_count": "Number of evidence items in the case",
    "examination_count": "Number of examination jobs in the case",
    "artifact_count": "Number of extracted artifacts in the case",
    "finding_count": "Number of findings in the case",
}

ALLOWED_PLACEHOLDERS = tuple(PLACEHOLDERS)


class TemplateError(ValueError):
    """Raised when a report template cannot be read or is invalid."""


@dataclass(slots=True)
class CustomSection:
    """Extra section supplied by an investigator template."""

    title: str
    body: str


@dataclass(slots=True)
class ReportTemplate:
    """A complete description of how a case report is laid out."""

    template_id: str
    name: str
    description: str
    organization: str
    jurisdiction: str
    report_type: str
    classification: str
    prepared_for: str
    sections: list[str]
    authority: str
    methodology: str
    declaration: str
    certification: str
    limitations: str
    signature_lines: list[str]
    custom_sections: list[CustomSection] = field(default_factory=list)
    narrative: str | None = None
    source_path: str | None = None
    builtin: bool = False

    @property
    def source_label(self) -> str:
        if self.builtin:
            return "Built-in default template"
        return self.source_path or "Uploaded template"

    def resolved_sections(self, selected: list[str] | None = None) -> list[str]:
        """Return the template's section order, optionally filtered."""
        ordered = [key for key in self.sections if key in SECTION_LABELS]
        if selected is None:
            return ordered
        chosen = set(selected)
        return [key for key in ordered if key in chosen]

    def to_dict(self) -> dict[str, Any]:
        """Serialise the template to the on-disk JSON format."""
        data: dict[str, Any] = {
            "format": TEMPLATE_FORMAT,
            "version": TEMPLATE_VERSION,
            "template_id": self.template_id,
            "name": self.name,
            "description": self.description,
            "organization": self.organization,
            "jurisdiction": self.jurisdiction,
            "report_type": self.report_type,
            "classification": self.classification,
            "prepared_for": self.prepared_for,
            "sections": list(self.sections),
            "authority": self.authority,
            "methodology": self.methodology,
            "declaration": self.declaration,
            "certification": self.certification,
            "limitations": self.limitations,
            "signature_lines": list(self.signature_lines),
        }
        if self.custom_sections:
            data["custom_sections"] = [
                {"title": section.title, "body": section.body}
                for section in self.custom_sections
            ]
        if self.narrative:
            data["narrative"] = self.narrative
        return data


def _config_organization() -> str:
    return getattr(get_config().report, "organization", "") or "Digital Forensic Laboratory"


def _config_jurisdiction() -> str:
    return getattr(get_config().report, "jurisdiction", "") or "India"


def get_default_template() -> ReportTemplate:
    """Return the built-in court-admissible template.

    The wording deliberately follows the structure courts and opposing experts
    expect: authority and scope, an examiner declaration, methodology and
    standards, evidence integrity, verified findings separated from unverified
    work product, limitations, and a signed certification.
    """
    organization = _config_organization()
    jurisdiction = _config_jurisdiction()

    authority = """This report documents the forensic examination of digital evidence in Case {{case_id}} - {{case_title}}. It has been prepared by {{examiner}} of {{organization}} at the request of the case owner and is intended to be relied upon in judicial or quasi-judicial proceedings.

**Scope of examination.** The examination was confined to the evidence items recorded in the Evidence Inventory and to the questions recorded in the case file. No other device, account, or data source was examined. This report is intended to be read as a whole and no section should be read in isolation or quoted out of context.

**Authority.** The examination was carried out under the authority of the case owner. Where the examiner was directed to examine specific material only, that direction is reflected in the scope above.

**Standards and guidance.** The examination and this report have been prepared with reference to ISO/IEC 27037:2012 (identification, collection, acquisition and preservation of digital evidence), ISO/IEC 27041:2015 (assurance of investigative methods), NIST SP 800-86 (integrating forensic techniques into incident response), and the SWGDE Best Practices for Digital Evidence."""

    declaration = """I, {{examiner}}, declare that:

1. I am a digital forensic examiner engaged by {{organization}} and have the training, experience and competence to conduct the examination described in this report and to express the opinions contained in it.

2. The evidence described in this report was identified, acquired and preserved using accepted digital forensic practice. Where a forensic image or working copy was made, its integrity was verified by cryptographic hash as recorded in Appendix A.

3. The analysis was performed using the tools and methods described in the Methodology section, and every material step was recorded in the audit trail reproduced in Appendix B.

4. The findings and opinions in this report are based on the evidence examined and are expressed within a reasonable degree of professional certainty. Where a conclusion depends on an assumption, or is limited by the available data, that limitation is stated.

5. Any content produced with the assistance of artificial intelligence is identified as such. No AI-generated statement has been relied upon as a finding unless it was independently verified by me and recorded as a verified finding.

6. I have no interest in the outcome of the matter and no conflict of interest in relation to the parties."""

    methodology = """The following method was applied to the evidence in this case:

1. **Preservation.** Source evidence was acquired without alteration. A SHA-256 hash was calculated at acquisition and recalculated after processing; the values are recorded in Appendix A. Those hash values are the primary means by which the integrity of the evidence can be independently checked.

2. **Processing.** Evidence was parsed at partition and file-system level using read-only libraries (pytsk3) running on a Linux worker. No write operation was performed against source evidence.

3. **Extraction.** File-system metadata, allocated and deleted entries, and file content were extracted and hashed. Extracted data is stored in the case repository, separate from the source evidence.

4. **Analysis.** Extracted artifacts were searched, correlated and reviewed by the examiner. Keyword and semantic indexes were used only to locate material; each cited artifact was opened and reviewed before being relied upon.

5. **Verification.** Findings were reviewed and marked verified by the examiner before inclusion in the Findings and Opinions section. Findings that were not verified are placed in a separate, clearly marked subsection and were not relied upon for any opinion.

6. **Artificial intelligence.** Where used, the locally hosted AI assistant was applied only to summarise or locate material (triage assistance). Its output is unverified by design and is identified as such in this report. No external or cloud AI service was used.

All times are expressed in UTC unless stated otherwise. The examination environment and tool versions are recorded in the audit trail."""

    certification = """I certify that:

1. The contents of this report are true and accurate to the best of my knowledge, information and belief.

2. This report has been prepared in accordance with accepted digital forensic practice and the standards referred to in the Authority, Scope and Purpose section.

3. This report, together with its appendices, is a complete and accurate record of the examination carried out, and no material fact known to me has been withheld.

4. The evidence referred to in this report has been preserved and remains available for independent examination, subject to any lawful direction of the court.

This report is issued under my hand. The signed original is the authoritative version; electronic copies are uncontrolled once distributed."""

    limitations = """1. **Scope.** This report addresses only the evidence items listed in the Evidence Inventory and the questions recorded in the case file. It does not address any other device, account or data source.

2. **Preservation limits.** Deleted, encrypted or damaged data, data in unallocated space, and data held by third-party or cloud providers may be partly or wholly unrecoverable. The absence of an artifact from this report is not proof that it never existed.

3. **Timestamps.** File-system and application timestamps depend on the system clock and time-zone settings of the device examined. Timestamps are reported as recorded and are not independently verified against an external time source unless stated.

4. **Tool limitations.** Forensic tools may fail to parse unsupported formats, may produce false positives or false negatives, and are subject to version-specific defects. Where a tool limitation affects a finding, it is stated with that finding.

5. **Artificial intelligence.** AI-assisted output is probabilistic, may be incomplete or incorrect, and is expressly marked as unverified in this report. It is used for triage only and does not replace examiner judgement.

6. **Opinions.** The opinions expressed are limited to the material examined and the information available at the date of this report. They may be revised if new evidence becomes available.

7. **Legal effect.** This report records the examiner's technical findings. Its admissibility and weight are matters for the court, to be determined under the applicable law and procedure."""

    signature_lines = [
        "Examiner signature: ______________________________________",
        "Name: {{examiner}}",
        "Designation: Digital Forensic Examiner, {{organization}}",
        "Place: __________________________________________________",
        "Date (UTC): {{generated_date}}",
        "",
        "Reviewer signature: _____________________________________",
        "Name: ___________________________________________________",
        "Designation: ____________________________________________",
        "Date (UTC): _____________________________________________",
    ]

    return ReportTemplate(
        template_id=BUILTIN_DEFAULT_ID,
        name="Court-Admissible Forensic Report (default)",
        description=(
            "Default court-oriented template with authority and scope, examiner "
            "declaration, methodology and standards, evidence integrity hashes, "
            "verified findings separated from unverified work product, limitations, "
            "and a signed certification page."
        ),
        organization=organization,
        jurisdiction=jurisdiction,
        report_type="Forensic Examination Report",
        classification="CONFIDENTIAL",
        prepared_for="Court / Investigating Agency",
        sections=[
            "cover",
            "authority_scope",
            "examiner_declaration",
            "case_summary",
            "methodology",
            "evidence",
            "examinations",
            "artifacts",
            "findings",
            "limitations",
            "certification",
            "integrity",
            "audit_trail",
        ],
        authority=authority,
        methodology=methodology,
        declaration=declaration,
        certification=certification,
        limitations=limitations,
        signature_lines=signature_lines,
        builtin=True,
    )


def build_context(
    *,
    case: Any,
    report_id: str,
    template: ReportTemplate,
    examiner: str,
    generated_at: Any,
    evidence_count: int,
    examination_count: int,
    artifact_count: int,
    finding_count: int,
) -> dict[str, str]:
    """Build the placeholder values available to template authors."""
    return {
        "case_id": str(getattr(case, "case_id", "") or ""),
        "case_title": str(getattr(case, "title", "") or ""),
        "case_status": str(getattr(case, "status", "") or "").replace("_", " ").title(),
        "case_priority": str(getattr(case, "priority", "") or "").capitalize(),
        "report_id": report_id,
        "report_type": template.report_type,
        "classification": template.classification,
        "organization": template.organization,
        "jurisdiction": template.jurisdiction,
        "prepared_for": template.prepared_for,
        "examiner": examiner,
        "generated_date": generated_at.strftime("%Y-%m-%d %H:%M UTC"),
        "evidence_count": str(evidence_count),
        "examination_count": str(examination_count),
        "artifact_count": str(artifact_count),
        "finding_count": str(finding_count),
    }


def render_text(text: str, context: dict[str, str]) -> str:
    """Render ``{{ placeholders }}`` in template text."""
    if not text:
        return ""
    try:
        return jinja2.Template(text, undefined=jinja2.Undefined).render(**context)
    except jinja2.TemplateError as exc:
        raise TemplateError(f"Template could not be rendered: {exc}") from exc


def _validate_text(label: str, text: str) -> None:
    """Validate template syntax and placeholders before saving."""
    if not text:
        return
    env = jinja2.Environment()
    try:
        parsed = env.parse(text)
    except jinja2.TemplateSyntaxError as exc:
        raise TemplateError(
            f"{label} has a template syntax error on line {exc.lineno}: {exc.message}"
        ) from exc
    unknown = sorted(meta.find_undeclared_variables(parsed) - set(ALLOWED_PLACEHOLDERS))
    if unknown:
        raise TemplateError(
            f"{label} uses unknown placeholder(s): {', '.join(unknown)}. "
            f"Allowed placeholders: {', '.join(ALLOWED_PLACEHOLDERS)}."
        )


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "template"


def template_from_dict(data: dict[str, Any], source_path: str | None = None) -> ReportTemplate:
    """Validate and normalise a template loaded from JSON."""
    if not isinstance(data, dict):
        raise TemplateError("Template JSON must contain an object at the top level.")

    default = get_default_template()

    name = str(data.get("name") or "").strip()
    if not name:
        raise TemplateError("Template JSON must include a non-empty 'name'.")

    template_id = str(data.get("template_id") or _slugify(name)).strip()
    if not template_id:
        template_id = _slugify(name)
    if template_id == BUILTIN_DEFAULT_ID:
        raise TemplateError(
            f"Template id '{BUILTIN_DEFAULT_ID}' is reserved for the built-in default template."
        )

    def text_field(key: str, fallback: str) -> str:
        value = data.get(key)
        if value is None:
            return fallback
        if not isinstance(value, str):
            raise TemplateError(f"'{key}' must be text.")
        return value.strip() or fallback

    sections_raw = data.get("sections")
    if sections_raw is None:
        sections = list(default.sections)
    else:
        if not isinstance(sections_raw, list) or not all(
            isinstance(item, str) for item in sections_raw
        ):
            raise TemplateError("'sections' must be a list of section keys.")
        sections = []
        for item in sections_raw:
            key = item.strip()
            if key not in SECTION_LABELS:
                raise TemplateError(
                    f"Unknown section '{key}'. Allowed sections: "
                    f"{', '.join(VALID_SECTIONS)}."
                )
            if key not in sections:
                sections.append(key)
        if not sections:
            raise TemplateError("'sections' must contain at least one section.")
        if "cover" not in sections:
            sections.insert(0, "cover")

    custom_sections: list[CustomSection] = []
    custom_raw = data.get("custom_sections")
    if custom_raw is not None:
        if not isinstance(custom_raw, list):
            raise TemplateError("'custom_sections' must be a list.")
        for item in custom_raw:
            if not isinstance(item, dict):
                raise TemplateError("Each custom section must be an object with 'title' and 'body'.")
            title = str(item.get("title") or "").strip()
            body = item.get("body")
            if not title:
                raise TemplateError("Each custom section must have a non-empty 'title'.")
            if not isinstance(body, str):
                raise TemplateError(f"Custom section '{title}' must have a text 'body'.")
            custom_sections.append(CustomSection(title=title, body=body.strip()))
        if custom_sections and "custom_sections" not in sections:
            anchor = "authority_scope" if "authority_scope" in sections else "cover"
            sections.insert(sections.index(anchor) + 1, "custom_sections")

    narrative = data.get("narrative")
    if narrative is not None and not isinstance(narrative, str):
        raise TemplateError("'narrative' must be text.")
    narrative = (narrative or "").strip() or None
    if narrative and "narrative" not in sections:
        anchor = "methodology" if "methodology" in sections else "cover"
        sections.insert(sections.index(anchor) + 1, "narrative")

    signature_raw = data.get("signature_lines", default.signature_lines)
    if not isinstance(signature_raw, list) or not all(
        isinstance(line, str) for line in signature_raw
    ):
        raise TemplateError("'signature_lines' must be a list of text lines.")
    signature_lines = [line.strip() for line in signature_raw]
    if not any(line for line in signature_lines):
        signature_lines = list(default.signature_lines)

    template = ReportTemplate(
        template_id=template_id,
        name=name,
        description=text_field("description", "Investigator supplied report template."),
        organization=text_field("organization", default.organization),
        jurisdiction=text_field("jurisdiction", default.jurisdiction),
        report_type=text_field("report_type", default.report_type),
        classification=text_field("classification", default.classification),
        prepared_for=text_field("prepared_for", default.prepared_for),
        sections=sections,
        authority=text_field("authority", default.authority),
        methodology=text_field("methodology", default.methodology),
        declaration=text_field("declaration", default.declaration),
        certification=text_field("certification", default.certification),
        limitations=text_field("limitations", default.limitations),
        signature_lines=signature_lines,
        custom_sections=custom_sections,
        narrative=narrative,
        source_path=source_path,
        builtin=False,
    )

    for label, text in (
        ("Authority and scope", template.authority),
        ("Methodology", template.methodology),
        ("Examiner declaration", template.declaration),
        ("Certification", template.certification),
        ("Limitations", template.limitations),
        ("Signature block", "\n".join(template.signature_lines)),
    ):
        _validate_text(label, text)
    for section in template.custom_sections:
        _validate_text(f"Custom section '{section.title}'", section.body)
    if template.narrative:
        _validate_text("Narrative", template.narrative)

    return template


class _HTMLTextExtractor(HTMLParser):
    """Convert a simple HTML template to readable text."""

    _BLOCK_TAGS = {
        "p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6",
        "table", "section", "article", "header", "footer", "blockquote",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in ("script", "style"):
            self._skip_depth += 1
        elif tag == "li":
            self._parts.append("\n- ")
        elif tag in self._BLOCK_TAGS:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style") and self._skip_depth:
            self._skip_depth -= 1
        elif tag in self._BLOCK_TAGS:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        self._parts.append(data)

    def text(self) -> str:
        raw = "".join(self._parts)
        raw = raw.replace("\xa0", " ")
        raw = re.sub(r"[ \t]+\n", "\n", raw)
        raw = re.sub(r"\n{3,}", "\n\n", raw)
        return raw.strip()


def extract_docx_text(path: str | Path) -> str:
    """Extract paragraph text from a Word (.docx) template using the stdlib."""
    namespace = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    try:
        with zipfile.ZipFile(path) as archive:
            try:
                payload = archive.read("word/document.xml")
            except KeyError as exc:
                raise TemplateError(
                    "The selected .docx file does not contain a Word document body."
                ) from exc
    except zipfile.BadZipFile as exc:
        raise TemplateError("The selected file is not a valid .docx document.") from exc

    try:
        root = ElementTree.fromstring(payload)
    except ElementTree.ParseError as exc:
        raise TemplateError("The selected .docx file could not be read.") from exc

    lines: list[str] = []
    for paragraph in root.iter(f"{namespace}p"):
        text = "".join(node.text or "" for node in paragraph.iter(f"{namespace}t")).strip()
        lines.append(text)
    while lines and not lines[0]:
        lines.pop(0)
    while lines and not lines[-1]:
        lines.pop()
    return "\n".join(lines).strip()


def _html_to_text(source: str) -> str:
    parser = _HTMLTextExtractor()
    parser.feed(source)
    parser.close()
    return parser.text()


def _markdown_to_text(source: str) -> str:
    lines = []
    for line in source.splitlines():
        line = re.sub(r"^\s{0,3}#{1,6}\s*", "", line)
        line = re.sub(r"^\s*>\s?", "", line)
        if line.strip().startswith("```"):
            continue
        lines.append(line.replace("`", ""))
    text = "\n".join(lines)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _read_text_file(path: Path) -> str:
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "utf-8", "cp1252"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _template_from_narrative(path: Path, narrative: str) -> ReportTemplate:
    default = get_default_template()
    stem = path.stem.replace("_", " ").replace("-", " ").strip() or "Investigator Template"
    sections = list(default.sections)
    anchor = "methodology" if "methodology" in sections else "cover"
    sections.insert(sections.index(anchor) + 1, "narrative")
    suffix = path.suffix.lower().lstrip(".").upper()
    template_id = _slugify(path.stem)
    if template_id == BUILTIN_DEFAULT_ID:
        template_id = f"custom-{template_id}"
    template = ReportTemplate(
        template_id=template_id,
        name=stem.title(),
        description=(
            f"Narrative template imported from {path.name}. The {suffix} content is "
            "included as the Examiner Narrative section and keeps the default "
            "court-oriented cover, declaration, methodology, integrity and "
            "certification sections."
        ),
        organization=default.organization,
        jurisdiction=default.jurisdiction,
        report_type=default.report_type,
        classification=default.classification,
        prepared_for=default.prepared_for,
        sections=sections,
        authority=default.authority,
        methodology=default.methodology,
        declaration=default.declaration,
        certification=default.certification,
        limitations=default.limitations,
        signature_lines=list(default.signature_lines),
        narrative=narrative,
        source_path=str(path),
        builtin=False,
    )
    _validate_text("Narrative", narrative)
    return template


def load_template_file(path: str | Path) -> ReportTemplate:
    """Load a template from disk, accepting JSON, text, HTML and Word files."""
    source = Path(path)
    if not source.is_file():
        raise TemplateError(f"Template file not found: {source}")

    suffix = source.suffix.lower()
    if suffix in (".json", ""):
        try:
            data = json.loads(_read_text_file(source))
        except json.JSONDecodeError as exc:
            raise TemplateError(
                f"Template JSON is not valid JSON (line {exc.lineno}): {exc.msg}."
            ) from exc
        return template_from_dict(data, source_path=str(source))

    if suffix == ".docx":
        narrative = extract_docx_text(source)
        if not narrative.strip():
            raise TemplateError("No readable text was found in the selected .docx file.")
        return _template_from_narrative(source, narrative)

    if suffix in (".html", ".htm"):
        narrative = _html_to_text(_read_text_file(source))
        if not narrative:
            raise TemplateError("No readable text was found in the selected HTML file.")
        return _template_from_narrative(source, narrative)

    if suffix in (".txt", ".md", ".markdown"):
        narrative = _read_text_file(source)
        if suffix != ".txt":
            narrative = _markdown_to_text(narrative)
        narrative = narrative.strip()
        if not narrative:
            raise TemplateError("The selected template file is empty.")
        return _template_from_narrative(source, narrative)

    raise TemplateError(
        "Unsupported template format "
        f"'{suffix or 'unknown'}'. Supported formats: .json, .docx, .html, .htm, .txt, .md."
    )


class TemplateStore:
    """Templates available to investigators: the built-in default plus uploads."""

    def __init__(self, templates_dir: str | Path | None = None):
        config = get_config()
        base = templates_dir or Path(config.app.data_dir) / "report_templates"
        self.directory = Path(base)

    def _ensure_directory(self) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)

    def list_templates(self) -> list[ReportTemplate]:
        templates = [get_default_template()]
        if self.directory.is_dir():
            for path in sorted(self.directory.glob("*.json")):
                try:
                    template = load_template_file(path)
                except TemplateError:
                    # A broken upload must not break the reports page.
                    continue
                if template.template_id == BUILTIN_DEFAULT_ID:
                    continue
                templates.append(template)
        return templates

    def get_template(self, template_id: str) -> ReportTemplate:
        if template_id in (None, "", BUILTIN_DEFAULT_ID):
            return get_default_template()
        for template in self.list_templates():
            if template.template_id == template_id:
                return template
        raise TemplateError(f"Report template '{template_id}' was not found.")

    def import_template(self, path: str | Path) -> ReportTemplate:
        """Validate and store an investigator template in the case data directory."""
        template = load_template_file(path)
        self._ensure_directory()
        destination = self.directory / f"{_slugify(template.template_id)}.json"

        # Keep the stored copy normalised and point it at the stored file.
        stored = replace(template, source_path=str(destination))
        destination.write_text(
            json.dumps(stored.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return stored

    def delete_template(self, template_id: str) -> bool:
        if template_id == BUILTIN_DEFAULT_ID:
            raise TemplateError("The built-in default template cannot be deleted.")
        if not self.directory.is_dir():
            return False
        for path in self.directory.glob("*.json"):
            try:
                template = load_template_file(path)
            except TemplateError:
                continue
            if template.template_id == template_id:
                path.unlink()
                return True
        return False

    def write_template(self, template: ReportTemplate, destination: str | Path) -> Path:
        """Save any template (including the built-in default) as JSON."""
        target = Path(destination)
        if target.suffix.lower() != ".json":
            target = target.with_suffix(target.suffix + ".json")
        target.parent.mkdir(parents=True, exist_ok=True)
        data = template.to_dict()
        if template.builtin:
            # An exported default becomes an editable copy: the reserved
            # built-in id must not be reused when the copy is uploaded again.
            data["template_id"] = "custom-court-admissible"
            data["name"] = f"{template.name} (copy)"
        data["notes"] = [
            "IDFA report template. Edit the text, then upload this file on the "
            "Reports page to use it.",
            "Available placeholders: " + ", ".join(ALLOWED_PLACEHOLDERS),
            "Section keys: " + ", ".join(VALID_SECTIONS),
        ]
        target.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        return target
