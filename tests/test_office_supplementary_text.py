"""Supplementary Office document text remains searchable as evidence."""

from io import BytesIO
from zipfile import ZipFile

from worker.main import extract_text_content


def office_archive(parts):
    output = BytesIO()
    with ZipFile(output, "w") as archive:
        for name, text in parts.items():
            archive.writestr(name, f"<root><p><t>{text}</t></p></root>")
    return output.getvalue()


def test_word_supplementary_text_in_light_extraction():
    data = office_archive({
        "word/document.xml": "Main document",
        "word/footnotes.xml": "Footnote evidence",
        "word/endnotes.xml": "Endnote evidence",
        "word/comments.xml": "Comment evidence",
    })
    text = extract_text_content(data, None, ".docx")
    for value in ("Main document", "Footnote evidence", "Endnote evidence", "Comment evidence"):
        assert value in text


def test_powerpoint_speaker_notes_in_light_extraction():
    data = office_archive({
        "ppt/slides/slide1.xml": "Slide evidence",
        "ppt/notesSlides/notesSlide1.xml": "Speaker notes evidence",
        "ppt/notesSlides/_rels/notesSlide1.xml.rels": "Not document text",
    })
    text = extract_text_content(data, None, ".pptx")
    assert "Slide evidence" in text
    assert "Speaker notes evidence" in text
    assert "Not document text" not in text
