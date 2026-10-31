"""Selecting a job must not load its potentially enormous result payload."""
from types import SimpleNamespace

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session

from app.examination.models import ExaminationOperation, JobStatus
from app.examination.service import ExaminationService
from app.ui.pages.examination_page import ExaminationPage


def test_select_interrupted_job_does_not_fetch_large_result_json(qt_app):
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(text(
            "CREATE TABLE examination_results (id INTEGER PRIMARY KEY, job_id INTEGER, "
            "result_type TEXT, summary TEXT, artifact_count INTEGER, content_json TEXT)"
        ))
        connection.execute(text(
            "INSERT INTO examination_results VALUES (1, 1, 'file_list', "
            "'Partial scan', 12000, :payload)"
        ), {"payload": '["' + ('x' * 10_000_000) + '"]'})

    statements = []
    event.listen(
        engine, "before_cursor_execute",
        lambda conn, cursor, statement, params, context, many: statements.append(statement),
    )
    with Session(engine) as session:
        page = ExaminationPage()
        page.exam_service = ExaminationService(session)
        job = SimpleNamespace(
            id=1, job_id="interrupted", evidence_id=1, evidence=None,
            operation=ExaminationOperation.FULL_EXAMINATION,
            status=JobStatus.INTERRUPTED, progress_percent=93,
            progress_message="Interrupted", started_at=None, completed_at=None,
            parameters_json=None, error_message=None,
        )
        page._jobs = [job]
        page.jobs_model.populate(page._jobs)
        page.jobs_table.selectRow(0)
        assert "Partial scan" in page.results_summary.toPlainText()
        assert "12000" in page.results_summary.toPlainText()
        assert statements
        assert all("content_json" not in sql.lower() for sql in statements)
        page.deleteLater()
    engine.dispose()
