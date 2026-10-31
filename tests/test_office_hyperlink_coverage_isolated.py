"""Office hyperlink targets are evidence, even when labels are innocuous."""

from io import BytesIO
from zipfile import ZipFile

import pytest

from worker.main import extract_text_content


@pytest.mark.parametrize(("ext", "base", "part"), [
    (".docx", "word", "document.xml"),
    (".xlsx", "xl/worksheets", "sheet1.xml"),
    (".pptx", "ppt/slides", "slide1.xml"),
])
def test_external_relationship_target_is_preserved_without_following_it(ext, base, part):
    data = BytesIO()
    rels = f"{base}/_rels/{part}.rels"
    with ZipFile(data, "w") as archive:
        archive.writestr(f"{base}/{part}", "<root><p><t>Click here</t></p></root>")
        archive.writestr(rels, '''<Relationships>
          <Relationship Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink"
            TargetMode="External" Target="https://example.invalid/investigation?account=lead42"/>
          <Relationship Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image"
            TargetMode="External" Target="https://example.invalid/not-a-link"/>
          <Relationship Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink"
            Target="internal-only"/>
        </Relationships>''')
    text = extract_text_content(data.getvalue(), None, ext)
    assert "https://example.invalid/investigation?account=lead42" in text
    assert rels in text
    assert "not-a-link" not in text
    assert "internal-only" not in text


def test_damaged_relationship_is_reported_without_losing_document():
    data = BytesIO()
    with ZipFile(data, "w") as archive:
        archive.writestr("word/document.xml", "<root><p><t>Surviving text</t></p></root>")
        archive.writestr("word/_rels/document.xml.rels", "<broken")
    warnings = []
    text = extract_text_content(data.getvalue(), None, ".docx", warnings=warnings)
    assert "Surviving text" in text
    assert "word/_rels/document.xml.rels" in warnings
