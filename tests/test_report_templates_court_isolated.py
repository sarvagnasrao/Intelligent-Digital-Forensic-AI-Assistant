"""Focused template and deletion tests without a database."""
import json

import pytest

from app.reports.templates import BUILTIN_IDS, TemplateError, TemplateStore


def test_builtin_templates_are_selectable_protected_and_exportable(tmp_path):
    store = TemplateStore(tmp_path / "templates")
    templates = store.list_templates()
    assert [t.template_id for t in templates] == list(BUILTIN_IDS)
    for template in templates:
        assert store.get_template(template.template_id).builtin
        with pytest.raises(TemplateError):
            store.delete_template(template.template_id)
        exported = store.write_template(template, tmp_path / f"{template.template_id}.json")
        assert store.import_template(exported).template_id not in BUILTIN_IDS
    assert len({t.report_type for t in templates[1:]}) == 3
    for template in templates[1:]:
        assert {"evidence", "limitations", "integrity"} <= set(template.sections)
        assert "jurisdiction" in template.limitations
        assert "not guaranteed" in template.limitations


def test_uploaded_delete_does_not_delete_reports_or_follow_symlink(tmp_path):
    store = TemplateStore(tmp_path / "templates")
    source = tmp_path / "input.json"
    source.write_text(json.dumps({"name": "Custom", "template_id": "custom-test"}))
    uploaded = store.import_template(source)
    report = tmp_path / "report.pdf"
    report.write_bytes(b"report")
    assert store.delete_template(uploaded.template_id)
    assert not (store.directory / "custom-test.json").exists()
    assert report.read_bytes() == b"report"
    assert not store.delete_template(uploaded.template_id)
    outside = tmp_path / "outside.json"
    outside.write_text(json.dumps({"name": "Outside", "template_id": "outside"}))
    link = store.directory / "linked.json"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("Creating symlinks is not permitted on this system")
    assert not store.delete_template("outside")
    assert outside.exists()
