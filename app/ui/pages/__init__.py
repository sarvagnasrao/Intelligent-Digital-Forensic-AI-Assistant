"""UI pages package."""
from __future__ import annotations

# Import all pages for easy access
from app.ui.pages.case_management_page import CaseManagementPage
from app.ui.pages.global_audit_page import GlobalAuditPage
from app.ui.pages.tools_page import ToolsPage
from app.ui.pages.settings_page import SettingsPage
from app.ui.pages.user_management_page import UserManagementPage
from app.ui.pages.overview_page import OverviewPage
from app.ui.pages.evidence_page import EvidencePage
from app.ui.pages.examination_page import ExaminationPage
from app.ui.pages.artifacts_search_page import ArtifactsSearchPage
from app.ui.pages.ai_analysis_page import AIAnalysisPage
from app.ui.pages.entities_timeline_page import EntitiesTimelinePage
from app.ui.pages.findings_page import FindingsPage
from app.ui.pages.reports_page import ReportsPage
from app.ui.pages.audit_page import AuditPage

__all__ = [
    "CaseManagementPage",
    "GlobalAuditPage",
    "ToolsPage",
    "SettingsPage",
    "UserManagementPage",
    "OverviewPage",
    "EvidencePage",
    "ExaminationPage",
    "ArtifactsSearchPage",
    "AIAnalysisPage",
    "EntitiesTimelinePage",
    "FindingsPage",
    "ReportsPage",
    "AuditPage",
]