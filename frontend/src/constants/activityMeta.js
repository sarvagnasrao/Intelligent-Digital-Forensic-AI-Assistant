export const ACTION_META = {
  CASE_CREATED:       { color: '#34d399', label: 'Case created' },
  CASE_UPDATED:       { color: '#60a5fa', label: 'Case updated' },
  CASE_CLOSED:        { color: '#94a3b8', label: 'Case closed' },
  FILE_UPLOADED:      { color: '#818cf8', label: 'File uploaded' },
  FILE_INGESTED:      { color: '#34d399', label: 'File ingested' },
  // An incomplete acquisition that still produced files. Amber, not green:
  // the job completed and the evidence is Indexed, so this is the only signal
  // that files were never copied -- and files that were never copied are
  // indistinguishable from files that were never on the drive.
  FILE_INGEST_PARTIAL:{ color: '#fbbf24', label: 'Ingest partial (image truncated)' },
  EVIDENCE_ARCHIVED:  { color: '#94a3b8', label: 'Evidence archived' },
  QUERY_MADE:         { color: '#a78bfa', label: 'Query made' },
  QUERY_FLAGGED:      { color: '#fb923c', label: 'Query flagged' },
  QUERY_DELETED:      { color: '#f87171', label: 'Query deleted' },
  REPORT_GENERATED:   { color: '#fbbf24', label: 'Report generated' },
  NOTE_ADDED:         { color: '#fde68a', label: 'Note added' },
  ENTITY_FLAGGED:     { color: '#fb923c', label: 'Entity flagged' },
  PROFILE_GENERATED:  { color: '#f472b6', label: 'Profile generated' },
  INTEGRITY_VERIFIED: { color: '#34d399', label: 'Integrity verified' },
  FILE_VIEWED:        { color: '#67e8f9', label: 'File viewed' },
  ACCOUNT_CREATED:    { color: '#34d399', label: 'Account created' },
  LOGIN_SUCCESS:      { color: '#34d399', label: 'Login success' },
  LOGIN_FAILED:       { color: '#f87171', label: 'Login failed' },
  ACCOUNT_LOCKED:     { color: '#f87171', label: 'Account locked' },
}
