from worker.main import extract_text_content
from worker.rtf_extraction import extract_rtf_text


def test_rtf_visible_text_and_unicode():
    source = (br"{\rtf1\ansi\ansicpg1252{\fonttbl{\f0 Arial;}}"
              br"Hello \'e9 \uc1\u233?\par next\tab item}")
    assert extract_text_content(source, "application/rtf", ".rtf") == "Hello é é\nnext\titem"


def test_rtf_excludes_metadata_and_binary():
    source = (br"{\rtf1 visible {\*\unknown secret}{\pict\bin4 {}xx}"
              br"{\field{\*\fldinst HIDDEN}{\fldrslt result}}}")
    assert extract_rtf_text(source) == "visible result"


def test_rtf_rejects_malformed_and_empty():
    for source in (b"not rtf", br"{\rtf1 broken", br"{\rtf1\bin20 x}",
                   br"{\rtf1\'zz}", br"{\rtf1{\pict data}}"):
        assert extract_rtf_text(source) is None


def test_rtf_surrogate_pairs():
    assert extract_rtf_text(br"{\rtf1\uc1\u-10179?\u-8704?}") == "😀"
