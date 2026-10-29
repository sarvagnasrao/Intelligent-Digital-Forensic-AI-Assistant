"""Initial migration - create all tables.

Revision ID: 001
Revises: 
Create Date: 2026-10-25 22:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '001'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Users table
    op.create_table(
        'users',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('username', sa.String(length=64), nullable=False),
        sa.Column('email', sa.String(length=128), nullable=False),
        sa.Column('password_hash', sa.String(length=256), nullable=False),
        sa.Column('full_name', sa.String(length=128), nullable=False),
        sa.Column('role', sa.String(length=16), nullable=False, server_default='investigator'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='1'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('last_login_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('username', name='uq_users_username'),
        sa.UniqueConstraint('email', name='uq_users_email'),
    )
    op.create_index('ix_users_username', 'users', ['username'], unique=False)
    op.create_index('ix_users_email', 'users', ['email'], unique=False)

    # Cases table
    op.create_table(
        'cases',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('case_id', sa.String(length=64), nullable=False),
        sa.Column('title', sa.String(length=256), nullable=False),
        sa.Column('description', sa.String(length=2048), nullable=True),
        sa.Column('objective', sa.String(length=2048), nullable=True),
        sa.Column('status', sa.String(length=32), nullable=False, server_default='open'),
        sa.Column('priority', sa.String(length=16), nullable=False, server_default='medium'),
        sa.Column('created_by_id', sa.Integer(), nullable=False),
        sa.Column('assignee_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('closed_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['assignee_id'], ['users.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['created_by_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('case_id', name='uq_cases_case_id'),
    )
    op.create_index('ix_cases_status', 'cases', ['status'], unique=False)
    op.create_index('ix_cases_assignee_id', 'cases', ['assignee_id'], unique=False)

    # Evidence table
    op.create_table(
        'evidence',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('evidence_id', sa.String(length=64), nullable=False),
        sa.Column('case_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=256), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('evidence_type', sa.String(length=16), nullable=False, server_default='original'),
        sa.Column('source_path', sa.String(length=1024), nullable=False),
        sa.Column('stored_path', sa.String(length=1024), nullable=True),
        sa.Column('size_bytes', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('mime_type', sa.String(length=128), nullable=True),
        sa.Column('extension', sa.String(length=16), nullable=True),
        sa.Column('status', sa.String(length=32), nullable=False, server_default='registered'),
        sa.Column('registered_by_id', sa.Integer(), nullable=False),
        sa.Column('registered_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.ForeignKeyConstraint(['case_id'], ['cases.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['registered_by_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('case_id', 'evidence_id', name='uq_evidence_case_evidence_id'),
    )
    op.create_index('ix_evidence_case_id', 'evidence', ['case_id'], unique=False)
    op.create_index('ix_evidence_status', 'evidence', ['status'], unique=False)

    # Evidence hashes table
    op.create_table(
        'evidence_hashes',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('evidence_id', sa.Integer(), nullable=False),
        sa.Column('algorithm', sa.String(length=16), nullable=False),
        sa.Column('hash_value', sa.String(length=128), nullable=False),
        sa.Column('is_reference', sa.Boolean(), nullable=False, server_default='0'),
        sa.Column('calculated_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('calculated_by_id', sa.Integer(), nullable=False),
        sa.Column('verified_against_id', sa.Integer(), nullable=True),
        sa.Column('verified_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('verified_by_id', sa.Integer(), nullable=True),
        sa.Column('match_result', sa.Boolean(), nullable=True),
        sa.ForeignKeyConstraint(['calculated_by_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['evidence_id'], ['evidence.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['verified_against_id'], ['evidence_hashes.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['verified_by_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('evidence_id', 'algorithm', 'is_reference', name='uq_evidence_hash_algo_ref'),
    )
    op.create_index('ix_evidence_hash_evidence_id', 'evidence_hashes', ['evidence_id'], unique=False)
    op.create_index('ix_evidence_hash_evidence_algo', 'evidence_hashes', ['evidence_id', 'algorithm'], unique=False)

    # Custody events table
    op.create_table(
        'custody_events',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('evidence_id', sa.Integer(), nullable=False),
        sa.Column('event_type', sa.String(length=64), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('performed_by_id', sa.Integer(), nullable=False),
        sa.Column('performed_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('source_location', sa.String(length=512), nullable=True),
        sa.Column('destination_location', sa.String(length=512), nullable=True),
        sa.Column('tool_used', sa.String(length=128), nullable=True),
        sa.Column('metadata_json', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(['evidence_id'], ['evidence.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['performed_by_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_custody_evidence_time', 'custody_events', ['evidence_id', 'performed_at'], unique=False)

    # Examination jobs table
    op.create_table(
        'examination_jobs',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('job_id', sa.String(length=64), nullable=False),
        sa.Column('case_id', sa.Integer(), nullable=False),
        sa.Column('evidence_id', sa.Integer(), nullable=False),
        sa.Column('operation', sa.String(length=32), nullable=False),
        sa.Column('parameters_json', sa.Text(), nullable=True),
        sa.Column('status', sa.String(length=16), nullable=False, server_default='pending'),
        sa.Column('progress_percent', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('progress_message', sa.String(length=512), nullable=True),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('created_by_id', sa.Integer(), nullable=False),
        sa.Column('worker_pid', sa.Integer(), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(['case_id'], ['cases.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['created_by_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['evidence_id'], ['evidence.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('job_id', name='uq_examination_jobs_job_id'),
    )
    op.create_index('ix_exam_job_case_status', 'examination_jobs', ['case_id', 'status'], unique=False)
    op.create_index('ix_exam_job_evidence_status', 'examination_jobs', ['evidence_id', 'status'], unique=False)

    # Examination results table
    op.create_table(
        'examination_results',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('job_id', sa.Integer(), nullable=False),
        sa.Column('result_type', sa.String(length=64), nullable=False),
        sa.Column('content_json', sa.Text(), nullable=False),
        sa.Column('summary', sa.Text(), nullable=True),
        sa.Column('artifact_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.ForeignKeyConstraint(['job_id'], ['examination_jobs.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_exam_result_job_type', 'examination_results', ['job_id', 'result_type'], unique=False)

    # Artifacts table
    op.create_table(
        'artifacts',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('artifact_id', sa.String(length=64), nullable=False),
        sa.Column('case_id', sa.Integer(), nullable=False),
        sa.Column('evidence_id', sa.Integer(), nullable=False),
        sa.Column('examination_job_id', sa.Integer(), nullable=True),
        sa.Column('artifact_type', sa.String(length=32), nullable=False, server_default='other'),
        sa.Column('name', sa.String(length=256), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('source_path', sa.String(length=1024), nullable=True),
        sa.Column('source_offset', sa.Integer(), nullable=True),
        sa.Column('source_size', sa.Integer(), nullable=True),
        sa.Column('content_text', sa.Text(), nullable=True),
        sa.Column('content_hash', sa.String(length=64), nullable=True),
        sa.Column('mime_type', sa.String(length=128), nullable=True),
        sa.Column('extension', sa.String(length=16), nullable=True),
        sa.Column('created_time', sa.DateTime(timezone=True), nullable=True),
        sa.Column('modified_time', sa.DateTime(timezone=True), nullable=True),
        sa.Column('accessed_time', sa.DateTime(timezone=True), nullable=True),
        sa.Column('metadata_json', sa.Text(), nullable=True),
        sa.Column('index_status', sa.String(length=16), nullable=False, server_default='not_indexed'),
        sa.Column('indexed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('vector_id', sa.String(length=64), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.ForeignKeyConstraint(['case_id'], ['cases.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['evidence_id'], ['evidence.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['examination_job_id'], ['examination_jobs.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('case_id', 'artifact_id', name='uq_artifact_case_artifact_id'),
    )
    op.create_index('ix_artifact_case_type', 'artifacts', ['case_id', 'artifact_type'], unique=False)
    op.create_index('ix_artifact_case_index', 'artifacts', ['case_id', 'index_status'], unique=False)

    # FTS5 virtual table for artifact search
    op.execute("""
        CREATE VIRTUAL TABLE artifacts_fts USING fts5(
            artifact_id, case_id, content_text, name, source_path,
            content='artifacts', content_rowid='id'
        )
    """)

    # Entities table
    op.create_table(
        'entities',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('entity_id', sa.String(length=64), nullable=False),
        sa.Column('case_id', sa.Integer(), nullable=False),
        sa.Column('artifact_id', sa.Integer(), nullable=False),
        sa.Column('entity_type', sa.String(length=32), nullable=False),
        sa.Column('value', sa.String(length=512), nullable=False),
        sa.Column('normalized_value', sa.String(length=512), nullable=True),
        sa.Column('start_offset', sa.Integer(), nullable=True),
        sa.Column('end_offset', sa.Integer(), nullable=True),
        sa.Column('context_snippet', sa.Text(), nullable=True),
        sa.Column('confidence', sa.Float(), nullable=False, server_default='1.0'),
        sa.Column('extractor', sa.String(length=64), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.ForeignKeyConstraint(['artifact_id'], ['artifacts.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['case_id'], ['cases.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('case_id', 'entity_id', name='uq_entity_case_entity_id'),
    )
    op.create_index('ix_entity_case_type_value', 'entities', ['case_id', 'entity_type', 'value'], unique=False)

    # Timeline events table
    op.create_table(
        'timeline_events',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('event_id', sa.String(length=64), nullable=False),
        sa.Column('case_id', sa.Integer(), nullable=False),
        sa.Column('artifact_id', sa.Integer(), nullable=True),
        sa.Column('entity_id', sa.Integer(), nullable=True),
        sa.Column('timestamp', sa.DateTime(timezone=True), nullable=False),
        sa.Column('timestamp_utc', sa.DateTime(timezone=True), nullable=True),
        sa.Column('timezone', sa.String(length=64), nullable=True),
        sa.Column('certainty', sa.String(length=16), nullable=False, server_default='high'),
        sa.Column('event_type', sa.String(length=64), nullable=False),
        sa.Column('title', sa.String(length=256), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('source', sa.String(length=64), nullable=False),
        sa.Column('metadata_json', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.ForeignKeyConstraint(['artifact_id'], ['artifacts.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['case_id'], ['cases.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['entity_id'], ['entities.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('case_id', 'event_id', name='uq_timeline_case_event_id'),
    )
    op.create_index('ix_timeline_case_time', 'timeline_events', ['case_id', 'timestamp'], unique=False)

    # Findings table
    op.create_table(
        'findings',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('finding_id', sa.String(length=64), nullable=False),
        sa.Column('case_id', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(length=256), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('conclusion', sa.Text(), nullable=True),
        sa.Column('status', sa.String(length=16), nullable=False, server_default='draft'),
        sa.Column('origin', sa.String(length=16), nullable=False, server_default='investigator'),
        sa.Column('ai_question', sa.Text(), nullable=True),
        sa.Column('ai_answer', sa.Text(), nullable=True),
        sa.Column('ai_citations_json', sa.Text(), nullable=True),
        sa.Column('ai_model', sa.String(length=64), nullable=True),
        sa.Column('ai_confidence', sa.Float(), nullable=True),
        sa.Column('verified_by_id', sa.Integer(), nullable=True),
        sa.Column('verified_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('verification_notes', sa.Text(), nullable=True),
        sa.Column('created_by_id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.ForeignKeyConstraint(['case_id'], ['cases.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['created_by_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['verified_by_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('case_id', 'finding_id', name='uq_finding_case_finding_id'),
    )
    op.create_index('ix_finding_case_status', 'findings', ['case_id', 'status'], unique=False)

    # Finding artifact links table
    op.create_table(
        'finding_artifact_links',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('finding_id', sa.Integer(), nullable=False),
        sa.Column('artifact_id', sa.Integer(), nullable=False),
        sa.Column('relevance', sa.String(length=32), nullable=False, server_default='supports'),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('cited_in_ai', sa.Boolean(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.ForeignKeyConstraint(['artifact_id'], ['artifacts.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['finding_id'], ['findings.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('finding_id', 'artifact_id', name='uq_finding_artifact_link'),
    )

    # Reports table
    op.create_table(
        'reports',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('report_id', sa.String(length=64), nullable=False),
        sa.Column('case_id', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(length=256), nullable=False),
        sa.Column('format', sa.String(length=8), nullable=False, server_default='pdf'),
        sa.Column('status', sa.String(length=16), nullable=False, server_default='generating'),
        sa.Column('file_path', sa.String(length=1024), nullable=True),
        sa.Column('file_size_bytes', sa.Integer(), nullable=True),
        sa.Column('included_sections_json', sa.Text(), nullable=True),
        sa.Column('finding_ids_json', sa.Text(), nullable=True),
        sa.Column('artifact_ids_json', sa.Text(), nullable=True),
        sa.Column('generated_by_id', sa.Integer(), nullable=False),
        sa.Column('generated_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(['case_id'], ['cases.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['generated_by_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('case_id', 'report_id', name='uq_report_case_report_id'),
    )
    op.create_index('ix_report_case_status', 'reports', ['case_id', 'status'], unique=False)

    # Audit events table
    op.create_table(
        'audit_events',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('event_id', sa.String(length=64), nullable=False),
        sa.Column('case_id', sa.Integer(), nullable=True),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('event_type', sa.String(length=64), nullable=False),
        sa.Column('action', sa.String(length=128), nullable=False),
        sa.Column('result', sa.String(length=16), nullable=False),
        sa.Column('target_type', sa.String(length=64), nullable=True),
        sa.Column('target_id', sa.Integer(), nullable=True),
        sa.Column('ip_address', sa.String(length=45), nullable=True),
        sa.Column('user_agent', sa.String(length=256), nullable=True),
        sa.Column('request_id', sa.String(length=64), nullable=True),
        sa.Column('details_json', sa.Text(), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('timestamp', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.ForeignKeyConstraint(['case_id'], ['cases.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('event_id', name='uq_audit_events_event_id'),
    )
    op.create_index('ix_audit_case_time', 'audit_events', ['case_id', 'timestamp'], unique=False)
    op.create_index('ix_audit_user_time', 'audit_events', ['user_id', 'timestamp'], unique=False)
    op.create_index('ix_audit_type_time', 'audit_events', ['event_type', 'timestamp'], unique=False)


def downgrade() -> None:
    op.drop_table('audit_events')
    op.drop_table('reports')
    op.drop_table('finding_artifact_links')
    op.drop_table('findings')
    op.drop_table('timeline_events')
    op.drop_table('entities')
    op.execute('DROP TABLE IF EXISTS artifacts_fts')
    op.drop_table('artifacts')
    op.drop_table('examination_results')
    op.drop_table('examination_jobs')
    op.drop_table('custody_events')
    op.drop_table('evidence_hashes')
    op.drop_table('evidence')
    op.drop_table('cases')
    op.drop_table('users')