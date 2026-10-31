"""Synthetic malformed workbook parts must not invent or erase cell evidence."""

from io import BytesIO
from zipfile import ZipFile

from worker.main import extract_text_content


def workbook(parts):
    data = BytesIO()
    with ZipFile(data, "w") as archive:
        for name, xml in parts.items():
            archive.writestr(name, xml)
    return data.getvalue()


def test_invalid_shared_string_indices_do_not_resolve_to_other_evidence():
    data = workbook({
        "xl/sharedStrings.xml": "<sst><si><t>Secret evidence</t></si></sst>",
        "xl/worksheets/sheet1.xml": (
            '<worksheet><c t="s"><v>-1</v></c><c t="s"><v>99</v></c>'
            '<c t="s"><v>invalid</v></c><c t="inlineStr"><is><t>Safe</t></is></c></worksheet>'
        ),
    })
    assert extract_text_content(data, None, ".xlsx") == "Safe"


def test_damaged_sheet_does_not_discard_intact_sheet():
    data = workbook({
        "xl/worksheets/sheet1.xml": "<worksheet><broken>",
        "xl/worksheets/sheet2.xml": (
            '<worksheet><c t="inlineStr"><is><t>Recovered</t></is></c></worksheet>'
        ),
    })
    assert extract_text_content(data, None, ".xlsx") == "Recovered"


def test_damaged_shared_strings_do_not_hide_inline_values_or_expose_indices():
    data = workbook({
        "xl/sharedStrings.xml": "<sst><broken>",
        "xl/worksheets/sheet1.xml": (
            '<worksheet><c t="s"><v>0</v></c>'
            '<c t="inlineStr"><is><t>Inline evidence</t></is></c></worksheet>'
        ),
    })
    assert extract_text_content(data, None, ".xlsx") == "Inline evidence"
