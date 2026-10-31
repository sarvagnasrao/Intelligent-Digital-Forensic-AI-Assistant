"""Recover intact Office parts from synthetic, partially damaged archives."""

from io import BytesIO
from zipfile import ZipFile

import pytest

from worker.main import describe_file_evidence, extract_text_content


@pytest.mark.parametrize(
    ("extension", "damaged", "intact"),
    [
        (".docx", "word/document.xml", "word/header1.xml"),
        (".docx", "word/header1.xml", "word/document.xml"),
        (".pptx", "ppt/slides/slide1.xml", "ppt/notesSlides/notesSlide1.xml"),
        (".pptx", "ppt/notesSlides/notesSlide1.xml", "ppt/slides/slide1.xml"),
    ],
)
def test_damaged_part_does_not_discard_intact_text(extension, damaged, intact):
    data = BytesIO()
    with ZipFile(data, "w") as archive:
        archive.writestr(damaged, "<root><broken>")
        archive.writestr(intact, "<root><p><t>Recovered evidence</t></p></root>")

    assert extract_text_content(data.getvalue(), None, extension) == "Recovered evidence"


def test_only_damaged_parts_have_no_extracted_text():
    data = BytesIO()
    with ZipFile(data, "w") as archive:
        archive.writestr("word/document.xml", "<root><broken>")

    assert extract_text_content(data.getvalue(), None, ".docx") is None


@pytest.mark.parametrize(
    ("extension", "damaged", "intact", "text"),
    [
        (".docx", "word/header1.xml", "word/document.xml", "<root><p><t>Recovered</t></p></root>"),
        (".pptx", "ppt/slides/slide1.xml", "ppt/notesSlides/notesSlide1.xml", "<root><p><t>Recovered</t></p></root>"),
        (".xlsx", "xl/sharedStrings.xml", "xl/worksheets/sheet1.xml", "<root><c t='inlineStr'><is><t>Recovered</t></is></c></root>"),
    ],
)
def test_file_evidence_reports_partial_extraction(tmp_path, extension, damaged, intact, text):
    path = tmp_path / ("synthetic" + extension)
    with ZipFile(path, "w") as archive:
        archive.writestr(damaged, "<root><broken>")
        archive.writestr(intact, text)

    artifact = describe_file_evidence(str(path))
    assert artifact["content_text"] == "Recovered"
    assert artifact["extraction_status"] == "partial"
    assert "Partial Office extraction" in artifact["read_error"]
    assert damaged in artifact["read_error"]
    assert artifact["content_hash"]
