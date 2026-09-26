import uuid
import json
from datetime import datetime

# Map action types to severity
SEVERITY_MAP = {
    # Info — normal operations
    "CASE_CREATED":       "info",
    "CASE_UPDATED":       "info",
    "FILE_UPLOADED":      "info",
    "FILE_INGESTED":      "info",
    "QUERY_MADE":         "info",
    "NOTE_ADDED":         "info",
    "REPORT_GENERATED":   "info",
    "PROFILE_GENERATED":  "info",
    "SUMMARY_GENERATED":  "info",
    "FILE_VIEWED":        "info",
    "CASE_EXPORTED":      "info",
    "CASE_IMPORTED":      "info",
    "ACCOUNT_CREATED":    "info",
    "LOGIN_SUCCESS":      "info",
    "INTEGRITY_VERIFIED": "info",
    "CASE_ACCESS_GRANTED":"info",
    "2FA_ENABLED":        "info",

    # Warning — needs attention
    "LOGIN_FAILED":        "warning",
    "PASSWORD_CHANGED":    "warning",
    "PASSWORD_RESET_BY_ADMIN": "warning",
    "EVIDENCE_ARCHIVED":   "warning",
    "CASE_CLOSED":         "warning",
    "ENTITY_FLAGGED":      "warning",
    "QUERY_FLAGGED":       "warning",
    "WATCHLIST_HIT":       "warning",

    # Error / Critical — security events
    "ACCOUNT_LOCKED":      "error",
    "LOGIN_LOCKED":        "error",
    "INTEGRITY_FAILED":    "critical",
    "2FA_DISABLED":        "warning",
    "CONTRADICTION_ANALYSIS": "warning",
    "FILE_INGEST_FAILED":  "error",
}

def write_audit(
    db, case_id, action_type,
    performed_by, details: dict = None
):
    """
    Helper to write audit log with
    automatic severity classification.
    """
    from backend import models
    severity = SEVERITY_MAP.get(
        action_type, "info")
    entry = models.AuditLog(
        id=str(uuid.uuid4()),
        case_id=case_id,
        action_type=action_type,
        performed_by=performed_by,
        performed_at=datetime.utcnow(),
        details=json.dumps(
            details or {}),
        severity=severity
    )
    db.add(entry)
    return entry
