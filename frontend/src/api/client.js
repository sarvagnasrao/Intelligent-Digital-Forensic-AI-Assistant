import axios from 'axios'

const api = axios.create({
  baseURL: '/api',
  headers: { 'Content-Type': 'application/json' }
})

// Attach token to every request
api.interceptors.request.use(config => {
  const token = localStorage.getItem('cfi_token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

// Redirect to login on 401
api.interceptors.response.use(
  response => response,
  error => {
    if (error.response?.status === 401) {
      localStorage.removeItem('cfi_token')
      localStorage.removeItem('cfi_user')
      window.location.href = '/login'
    }
    return Promise.reject(error)
  }
)

// Auth endpoints
export const login = (username, password, totp_code = null) => {
  return axios.post('/api/auth/login-2fa', { username, password, totp_code })
}

export const register = (data) =>
  axios.post('/api/auth/register', data)

export const getMe = () =>
  api.get('/auth/me')

export const getPreferences = () =>
  api.get('/auth/preferences')

export const updatePreferences = (data) =>
  api.put('/auth/preferences', data)

export const getUsers = () =>
  api.get('/auth/users')

export const updateUserRole = (userId, role) =>
  api.patch(`/auth/users/${userId}/role`, { role })

// Cases
export const getCases = (params = {}) =>
  api.get('/cases', { params })

export const createCase = (data) =>
  api.post('/cases', data)

export const getCase = (id) =>
  api.get(`/cases/${id}`)

export const updateCase = (id, data) =>
  api.patch(`/cases/${id}`, data)

export const archiveCase = (id) =>
  api.delete(`/cases/${id}`)

// Evidence
export const getEvidence = (caseId) =>
  api.get(`/cases/${caseId}/evidence`)

export const uploadEvidence = (caseId, formData) =>
  api.post(
    `/cases/${caseId}/evidence/upload`,
    formData,
    { headers: { 'Content-Type': 'multipart/form-data' } }
  )

export const getEvidenceItem = (caseId, evidenceId) =>
  api.get(`/cases/${caseId}/evidence/${evidenceId}`)

export const archiveEvidence = (caseId, evidenceId) =>
  api.delete(`/cases/${caseId}/evidence/${evidenceId}`)

export const verifyEvidence = (caseId, evidenceId) =>
  api.post(`/cases/${caseId}/evidence/${evidenceId}/verify`)

// Queries
export const getQueries = (caseId, params = {}) =>
  api.get(`/cases/${caseId}/queries`, {
    params: { page: 1, page_size: 20, ...params }
  })

export const askQuestion = (caseId, data) =>
  api.post(`/cases/${caseId}/queries/ask`, data)

export const flagQuery = (caseId, queryId) =>
  api.patch(`/cases/${caseId}/queries/${queryId}/flag`)

export const deleteQuery = (caseId, queryId) =>
  api.delete(`/cases/${caseId}/queries/${queryId}`)

// Entities
export const getEntities = (caseId, params = {}) =>
  api.get(`/cases/${caseId}/entities`, {
    params: { page: 1, page_size: 100, ...params }
  })

export const getGraphData = (caseId) =>
  api.get(`/cases/${caseId}/entities/graph`)

export const flagEntity = (caseId, entityId) =>
  api.patch(`/cases/${caseId}/entities/${entityId}/flag`)

export const generateEntityProfile = (caseId, entityId) =>
  api.post(`/cases/${caseId}/entities/${entityId}/profile`)

export const getEntityProfile = (caseId, entityId) =>
  api.get(`/cases/${caseId}/entities/${entityId}/profile`)


// Notes
export const getNotes = (caseId, params = {}) =>
  api.get(`/cases/${caseId}/notes`, { params })

export const createNote = (caseId, data) =>
  api.post(`/cases/${caseId}/notes`, data)

export const deleteNote = (caseId, noteId) =>
  api.delete(`/cases/${caseId}/notes/${noteId}`)

// Audit
export const getAuditLog = (caseId) =>
  api.get(`/cases/${caseId}/audit`)

// System
export const getStatus = () =>
  api.get('/status')

// Forensic Artifacts
export const getAllArtifacts = (caseId, params = {}) =>
  api.get(`/cases/${caseId}/evidence/artifacts/all`, {
    params: { page: 1, page_size: 50, ...params }
  })

export const getArtifact = (caseId, artifactId) =>
  api.get(`/cases/${caseId}/evidence/artifacts/${artifactId}`)

export const flagArtifact = (caseId, artifactId) =>
  api.patch(`/cases/${caseId}/evidence/artifacts/${artifactId}/flag`)

export const getTimeline = (caseId) =>
  api.get(`/cases/${caseId}/evidence/timeline`)

export const getAnomalies = (caseId) =>
  api.get(`/cases/${caseId}/evidence/anomalies`)

// Reports
export const getReports = (caseId) =>
  api.get(`/cases/${caseId}/reports`)

export const createReport = (caseId, data) =>
  api.post(`/cases/${caseId}/reports`, data)

export const getReport = (caseId, reportId) =>
  api.get(`/cases/${caseId}/reports/${reportId}`)

export const deleteReport = (caseId, reportId) =>
  api.delete(`/cases/${caseId}/reports/${reportId}`)

// Global Search
export const globalSearch = (q, caseId = null) => {
  const params = { q }
  if (caseId) params.case_id = caseId
  return api.get('/search', { params })
}

// Watchlist
export const getWatchlist = (caseId) =>
  api.get(`/cases/${caseId}/watchlist`)

export const addKeyword = (caseId, data) =>
  api.post(`/cases/${caseId}/watchlist`, data)

export const removeKeyword = (caseId, keywordId) =>
  api.delete(`/cases/${caseId}/watchlist/${keywordId}`)

export const getWatchlistHits = (caseId) =>
  api.get(`/cases/${caseId}/watchlist/hits`)

// Geographic map
export const getGeoData = (caseId) =>
  api.get(`/cases/${caseId}/geomap`)

// Cross-case entities
export const crossCaseSearch = (name) =>
  api.get(
    '/entities/cross-case-search',
    { params: { name } }
  )

// Ingestion Queue
export const getSystemInfo = () =>
  api.get('/queue/system-info')

// Force an immediate hardware/device re-scan (after plugging in an
// evidence drive or an eGPU). Bypasses the short server-side cache.
export const rescanSystemInfo = () =>
  api.post('/queue/system-info/rescan')

export const estimateTime = (evidenceIds, throttle) =>
  api.post('/queue/estimate', {
    evidence_ids: evidenceIds,
    cpu_throttle_percent: throttle
  })

export const addToQueue = (data) =>
  api.post('/queue/add', data)

export const addBulkToQueue = (jobs) =>
  api.post('/queue/add-bulk', { jobs })

export const getQueue = () =>
  api.get('/queue')

export const getQueueHistory = () =>
  api.get('/queue/history')

export const cancelJob = (jobId) =>
  api.delete(`/queue/${jobId}/cancel`)

export const forceStartJob = (jobId) =>
  api.post(`/queue/${jobId}/force-start`)

export const stopJob = (jobId) =>
  api.post(`/queue/${jobId}/stop`)

export const updateJobSettings = (jobId, settings) =>
  api.patch(`/queue/${jobId}/settings`, settings)

export const getQueueList = () =>
  api.get('/queue/list')

export const deleteQueueJob = (jobId) =>
  api.delete(`/queue/${jobId}`)

// File Viewer
export const viewArtifactFile = (caseId, artifactId) =>
  `/api/cases/${caseId}/artifacts/${artifactId}/view`
// Returns URL — not a promise.
// Used as src= in img/video/audio tags.

export const downloadArtifactFile = (caseId, artifactId) =>
  api.get(
    `/cases/${caseId}/artifacts/${artifactId}/download`,
    { responseType: 'blob' }
  )

export const getStorageStats = (caseId) =>
  api.get(`/cases/${caseId}/storage-stats`)

export const getGlobalActivity = (params = {}) =>
  api.get('/activity', { params })

export const changePassword = (data) =>
  api.post('/auth/change-password', data)

export const setup2FA = () =>
  api.post('/auth/2fa/setup')

export const verify2FA = (code) =>
  api.post('/auth/2fa/verify', { code })

export const disable2FA = (code) =>
  api.post('/auth/2fa/disable', { code })

export const adminResetPassword = (userId, newPassword) =>
  api.patch(`/auth/users/${userId}/reset-password`, { new_password: newPassword })

export const deactivateUser = (userId) =>
  api.patch(`/auth/users/${userId}/deactivate`, {})

export const activateUser = (userId) =>
  api.patch(`/auth/users/${userId}/activate`, {})

export const generateCaseSummary = (caseId) =>
  api.post(`/cases/${caseId}/summary`)

export const getLatestSummary = (caseId) =>
  api.get(`/cases/${caseId}/summary/latest`)

// Case Access Management
export const getCaseAccess = (caseId) =>
  api.get(`/cases/${caseId}/access`)

export const grantCaseAccess = (caseId, data) =>
  api.post(`/cases/${caseId}/access`, data)

export const revokeCaseAccess = (caseId, accessId) =>
  api.delete(`/cases/${caseId}/access/${accessId}`)

export const getCredentials = (caseId, params = {}) =>
  api.get(`/cases/${caseId}/credentials`, { params })

export const confirmCredential = (caseId, findingId) =>
  api.patch(`/cases/${caseId}/credentials/${findingId}/confirm`)

export const markFalsePositive = (caseId, findingId) =>
  api.patch(`/cases/${caseId}/credentials/${findingId}/false-positive`)

export const compareArtifacts = (caseId, id1, id2) =>
  api.post(`/cases/${caseId}/artifacts/compare`, {
    artifact_id_1: id1,
    artifact_id_2: id2,
  })

export const detectContradictions = (caseId) =>
  api.post(`/cases/${caseId}/contradictions`)

export const getLatestContradictions = (caseId) =>
  api.get(`/cases/${caseId}/contradictions/latest`)

export const exportCase = (caseId, includeFiles = false) =>
  api.get(`/cases/${caseId}/export`, {
    params: { include_files: includeFiles },
    responseType: 'blob',
  })


export const importCase = (formData) =>
  api.post('/cases/import', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })

export default api
