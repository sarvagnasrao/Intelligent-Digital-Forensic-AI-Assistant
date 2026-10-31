"""Formula text is evidence even when a spreadsheet caches a harmless label."""

import io
import zipfile

from app.analysis.extractors import extract_entities
from app.artifacts.models import EntityType
from worker.main import extract_text_content


def test_cached_and_uncached_formulas_remain_searchable_without_evaluation():
    sheet = b'''<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
      <sheetData><row>
        <c r="A1" t="str"><f>HYPERLINK("mailto:lead@example.test","Open")</f><v>Open</v></c>
        <c r="B1"><f>HYPERLINK("https://trail.example.test/path","View")</f></c>
        <c r="C1" t="inlineStr"><is><t>ordinary cell</t></is></c>
      </row></sheetData></worksheet>'''
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("xl/worksheets/sheet1.xml", sheet)

    text = extract_text_content(stream.getvalue(), None, ".xlsx")
    assert text is not None
    assert 'HYPERLINK("mailto:lead@example.test","Open")' in text
    assert 'HYPERLINK("https://trail.example.test/path","View")' in text
    assert "\nOpen\n" in text
    assert "ordinary cell" in text
    entities = extract_entities(text)
    email = next(e for e in entities if e.entity_type == EntityType.EMAIL)
    assert email.value == "lead@example.test"
    assert text[email.start:email.end] == email.value
    assert any(
        e.entity_type == EntityType.URL and "trail.example.test/path" in e.value
        for e in entities
    )
