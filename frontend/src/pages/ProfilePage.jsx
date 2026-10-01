import React, { useState, useEffect } from 'react'
import { useParams, useSearchParams, useNavigate } from 'react-router-dom'
import {
  User, MapPin, Building2, Wifi, FileText, Network,
  ArrowLeft, RefreshCw, Flag, Sparkles, AlertTriangle,
  CheckCircle
} from 'lucide-react'
import { getEntities, generateEntityProfile, crossCaseSearch, getEntityProfile, apiErrorMessage } from '../api/client'
import Badge from '../components/Badge'
import PageLayout from '../components/PageLayout'
import toast from 'react-hot-toast'
import { formatDistanceToNow } from 'date-fns'
import { fromUtc } from '../utils/time'

const TYPE_ICON = {
  Person:       User,
  Location:     MapPin,
  Organization: Building2,
  IP:           Wifi,
  File:         FileText
}

export default function ProfilePage() {
  const { caseId } = useParams()
  const [searchParams] = useSearchParams()
  const navigate = useNavigate()
  const entityId = searchParams.get('entity')
  const entityName = searchParams.get('name')
  const entityTypeParam = searchParams.get('type')

  const [entities, setEntities] = useState([])
  const [selected, setSelected] = useState(null)
  const [profile, setProfile] = useState(null)
  const [generating, setGenerating] = useState(false)
  const [filterType, setFilterType] = useState(entityTypeParam || 'Person')
  const [profileMeta, setProfileMeta] = useState(null)
  // Stores metadata about when the profile was generated
  // `null` means "the server says there is no profile". A failed check is a
  // separate state so the two cannot render the same message.
  const [profileLoadError, setProfileLoadError] = useState(null)

  const [crossCaseResults, setCrossCaseResults] = useState(null)
  const [searchingCross, setSearchingCross] = useState(false)

  // Sync filterType with URL type if it changes
  useEffect(() => {
    if (entityTypeParam && filterType !== entityTypeParam) {
      setFilterType(entityTypeParam)
    }
  }, [entityTypeParam])

  useEffect(() => {
    loadEntities()
  }, [caseId, filterType])

  useEffect(() => {
    if ((entityId || entityName) && entities.length > 0) {
      const found = entities.find(e => e.id === entityId || e.name === entityName)
      if (found) {
        setSelected(found)
        if (filterType !== found.entity_type) {
          setFilterType(found.entity_type)
        }
        loadExistingProfile(found)
      }
    }
  }, [entityId, entityName, entities])

  const loadEntities = async () => {
    try {
      const res = await getEntities(caseId, { entity_type: filterType, page_size: 100 })
      const items = res.data.items || res.data
      setEntities(items)
    } catch {
      toast.error('Failed to load entities')
    }
  }

  const loadExistingProfile = async (entity) => {
    setProfileLoadError(null)
    try {
      const res = await getEntityProfile(caseId, entity.id)
      if (res.data.has_profile) {
        setProfile(res.data)
        setProfileMeta({
          generated_at: res.data.generated_at,
          generated_by: res.data.generated_by
        })
      } else {
        setProfile(null)
        setProfileMeta(null)
      }
    } catch (e) {
      /* This used to clear the profile and its metadata, which is
         indistinguishable from the server having answered "there is no
         profile" - the message rendered just below reads "No saved profile
         found. Click Generate Profile to create one." A failed request was
         therefore shown as the absence of a finding, and clicking Generate
         would appear to be the fix for a problem that was a network error. */
      setProfile(null)
      setProfileMeta(null)
      setProfileLoadError(
        apiErrorMessage(e, 'Could not check for a saved profile'))
    }
  }

  const handleGenerateProfile = async () => {
    if (!selected) return
    setGenerating(true)
    try {
      const res = await generateEntityProfile(caseId, selected.id)
      setProfile(res.data)
      setProfileMeta({
        generated_at: new Date().toISOString(),
        generated_by: 'current session'
      })
      toast.success('Profile generated')
    } catch (e) {
      toast.error(
        e.response?.data?.detail ||
        'Profile generation failed'
      )
    } finally {
      setGenerating(false)
    }
  }

  const handleCrossCase = async () => {
    if (!selected) return
    setSearchingCross(true)
    try {
      const res = await crossCaseSearch(selected.name)
      setCrossCaseResults(res.data)
    } catch {
      toast.error('Cross-case search failed')
    } finally {
      setSearchingCross(false)
    }
  }

  const TYPES = ['Person', 'Location', 'Organization', 'IP']

  return (
    <PageLayout
      title="Entity Profiler"
      subtitle="Select an entity to generate an AI-powered forensic profile. The AI will cross-reference all mentions of this entity across your evidence to build a comprehensive summary of their activities and connections."
      actions={
        <button
          onClick={() => navigate(`/cases/${caseId}`)}
          className="flex items-center gap-2 px-3 py-1.5 rounded-lg border border-line hover:bg-surface-4 text-ink-1 hover:text-ink-0 transition-colors text-sm"
        >
          <ArrowLeft size={16} />
          Back
        </button>
      }
    >
      <div className="grid grid-cols-3 gap-4">
        {/* Left — Entity selector */}
        <div className="col-span-1">
          {/* Type filter tabs */}
          <div className="flex gap-1 mb-3 flex-wrap">
            {TYPES.map(t => {
              const Icon = TYPE_ICON[t] || User
              return (
                <button
                  key={t}
                  onClick={() => setFilterType(t)}
                  className={`flex items-center gap-1 px-2 py-1 rounded-lg text-xs transition-colors
                    ${filterType === t ? 'bg-accent/20 text-accent' : 'text-ink-2 hover:bg-surface-4'}`}
                >
                  <Icon size={11} />
                  {t}
                </button>
              )
            })}
          </div>

          {/* Entity list */}
          <div className="space-y-1 max-h-[calc(100vh-280px)] overflow-y-auto">
            {entities.map(entity => {
              const Icon = TYPE_ICON[entity.entity_type] || User
              return (
                <button
                  key={entity.id}
                  onClick={() => {
                    setSelected(entity)
                    setProfile(null)
                    setProfileMeta(null)
                    setCrossCaseResults(null)
                    loadExistingProfile(entity)
                  }}
                  className={`w-full flex items-center gap-2 p-2.5 rounded-xl text-left transition-all border
                    ${selected?.id === entity.id
                      ? 'bg-accent/10 border-accent/40'
                      : 'bg-surface-2 border-line hover:border-accent/30'
                    }`}
                >
                  <Icon size={14} className="text-ink-2 shrink-0" />
                  <div className="flex-1 min-w-0">
                    <p className="text-xs font-medium text-ink-0 truncate">{entity.name}</p>
                    <p className="text-xs text-ink-2">
                      Seen {entity.frequency}×
                      {entity.is_flagged && ' · ⚑ flagged'}
                    </p>
                  </div>
                </button>
              )
            })}
            {entities.length === 0 && (
              <p className="text-xs text-ink-2 text-center py-8">
                No {filterType} entities found. Upload and index evidence first.
              </p>
            )}
          </div>
        </div>

        {/* Right — Profile panel */}
        <div className="col-span-2">
          {!selected ? (
            <div className="bg-surface-2 border border-line rounded-xl p-8 text-center text-ink-2 h-full flex flex-col items-center justify-center">
              <Network size={48} className="mb-4 opacity-20"/>
              <p className="text-sm">Select an entity from the left to generate their forensic profile</p>
            </div>
          ) : (
            <div className="bg-surface-2 border border-line rounded-xl p-5">
              {/* Entity header */}
              <div className="flex items-start justify-between mb-4">
                <div className="flex items-center gap-3">
                  <div className="w-12 h-12 rounded-xl bg-accent/20 flex items-center justify-center">
                    {React.createElement(
                      TYPE_ICON[selected.entity_type] || User,
                      { size: 24, className: "text-accent" }
                    )}
                  </div>
                  <div>
                    <h2 className="text-xl font-bold text-ink-0">{selected.name}</h2>
                    <div className="flex items-center gap-2 mt-1">
                      <Badge label={selected.entity_type} />
                      <span className="text-xs text-ink-2">
                        Mentioned {selected.frequency} time(s)
                      </span>
                      {selected.is_flagged && (
                        <span className="text-xs text-warning">⚑ Flagged</span>
                      )}
                    </div>
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <button
                    onClick={handleCrossCase}
                    disabled={searchingCross}
                    className="flex items-center gap-2 bg-surface-4 border border-line hover:border-accent/50 text-ink-0 px-4 py-2 rounded-xl text-sm font-medium transition-colors"
                  >
                    {searchingCross
                      ? <RefreshCw size={14} className="animate-spin" />
                      : <Network size={14} />}
                    Cross-Case
                  </button>
                  <button
                    onClick={handleGenerateProfile}
                    disabled={generating}
                    className="flex items-center gap-2 bg-accent hover:bg-accent-hover disabled:opacity-50 text-white px-4 py-2 rounded-xl text-sm font-medium transition-colors"
                  >
                    {generating ? (
                      <>
                        <RefreshCw size={14} className="animate-spin"/>
                        Generating...
                      </>
                    ) : (
                      <>
                        <Sparkles size={14} />
                        Generate Profile
                      </>
                    )}
                  </button>
                </div>
              </div>

              {/* Generating indicator */}
              {generating && (
                <div className="bg-surface-1 rounded-xl p-6 text-center mb-4">
                  <RefreshCw size={24} className="mx-auto mb-3 text-accent animate-spin" />
                  <p className="text-sm text-ink-1">Searching all evidence for {selected.name}...</p>
                  <p className="text-xs text-ink-2 mt-1">Retrieving from vector database, graph, and artifacts</p>
                </div>
              )}

              {/* Profile result */}
              {profile && (
                <div>
                  {/* Previously generated indicator + Regenerate button */}
                  {profileMeta && (
                    <div className="flex items-center justify-between mb-3">
                      <div className="flex items-center gap-2 text-xs text-ink-2">
                        <CheckCircle size={12} className="text-success" />
                        <span>
                          Profile generated{' '}
                          {profileMeta.generated_at && (() => {
                            try {
                              return formatDistanceToNow(
                                fromUtc(profileMeta.generated_at),
                                { addSuffix: true }
                              )
                            } catch {
                              return ''
                            }
                          })()}
                          {' '}by {profileMeta.generated_by}
                        </span>
                      </div>
                      <button
                        onClick={handleGenerateProfile}
                        disabled={generating}
                        className="text-xs text-ink-2 hover:text-accent flex items-center gap-1 transition-colors"
                      >
                        <RefreshCw size={11} className={generating ? 'animate-spin' : ''} />
                        Regenerate
                      </button>
                    </div>
                  )}

                  <div className="flex items-center justify-between mb-3">
                    <h3 className="text-sm font-semibold text-ink-2 uppercase tracking-wider">
                      Forensic Profile
                    </h3>
                    <div className="flex items-center gap-3">
                      <span
                          className="text-xs text-success"
                          title="How many distinct evidence files were linked to this profile. A count of files, not a measure of how well grounded the text is."
                        >
                          {profile.cited_sentence_count}
                          {profile.cited_sentence_count === 1
                           ? ' source'
                           : ' sources'}
                        </span>
                      <span className="text-xs text-ink-2">
                        {profile.related_artifact_count} related files
                      </span>
                      {/* "Auto-flagged in query history" used to render here
                          unconditionally, inside the block that only draws
                          when a profile exists. There was no condition, no
                          data behind it and no way for it to become true:
                          the profile response carries no flag field, and
                          `flagQuery` in client.js is exported but called by
                          no page. So every profile claimed to be flagged and
                          none were. Removed rather than given a fabricated
                          condition - an investigator who trusts that badge
                          would be trusting a warning that never fires. */}
                    </div>
                  </div>

                  <div className="bg-surface-1 rounded-xl p-4 mb-4 max-h-96 overflow-y-auto">
                    <p className="text-sm text-ink-1 whitespace-pre-wrap leading-relaxed">
                      {profile.profile}
                    </p>
                  </div>

                  {profile.graph_context && (
                    <div>
                      <h3 className="text-xs font-semibold text-ink-2 uppercase tracking-wider mb-2">
                        Known Relationships
                      </h3>
                      <div className="bg-surface-1 rounded-xl p-3">
                        <p className="text-xs font-mono text-ink-2 whitespace-pre-wrap">
                          {profile.graph_context}
                        </p>
                      </div>
                    </div>
                  )}
                </div>
              )}

              {/* Cross-Case Results */}
              {crossCaseResults && (
                <div className="mt-4 border-t border-line pt-4">
                  <h3 className="text-sm font-semibold text-ink-2 uppercase tracking-wider mb-3 flex items-center gap-2">
                    <Network size={14} className="text-accent" />
                    Cross-Case Appearances ({crossCaseResults.total_cases} case(s))
                  </h3>
                  {crossCaseResults.total_cases === 0 ? (
                    <p className="text-xs text-success">
                      ✅ This entity only appears in this case
                    </p>
                  ) : (
                    <div className="space-y-2">
                      {crossCaseResults.results.map(r => (
                        <div key={r.case_id}
                          className={`p-3 rounded-xl border ${
                            r.case_id === caseId
                              ? 'bg-accent/10 border-accent/30'
                              : 'bg-surface-1 border-line'
                          }`}
                        >
                          <div className="flex items-center justify-between">
                            <div>
                              <p className="text-xs font-semibold text-ink-0">
                                {r.case_name}
                                {r.case_id === caseId && ' (current)'}
                              </p>
                              <p className="text-xs text-ink-2">
                                {r.entities.length} match(es) · {r.case_status}
                              </p>
                            </div>
                            {r.case_id !== caseId && (
                              <button
                                onClick={() => navigate(`/cases/${r.case_id}`)}
                                className="text-xs text-accent hover:underline"
                              >
                                Open case →
                              </button>
                            )}
                          </div>
                        </div>
                      ))}
                      {crossCaseResults.total_cases > 1 && (
                        <p className="text-xs text-warning mt-2 flex items-center gap-1">
                          <AlertTriangle size={11} />
                          This entity appears in multiple cases — possible link between investigations
                        </p>
                      )}
                    </div>
                  )}
                </div>
              )}

              {/* Empty state — no profile yet */}
              {!generating && !profile && (
                <div className="bg-surface-1 rounded-xl p-6 text-center text-ink-2">
                  <Sparkles size={24} className="mx-auto mb-3 opacity-30"/>
                  <p className="text-sm">
                    {profileLoadError
                      /* Third state. "No saved profile found" is a real
                         answer from the server and means there is nothing
                         there; this means we never got to ask. They are
                         different facts and used to render identically. */
                      ? `Could not check for a saved profile: ${profileLoadError}`
                      : profileMeta === null
                      ? 'No saved profile found. Click "Generate Profile" to create one.'
                      : 'Loading saved profile...'}
                  </p>
                  {profileLoadError && (
                    <button
                      onClick={() => loadExistingProfile(selected)}
                      className="mt-2 text-xs font-semibold text-accent hover:underline"
                      style={{ background: 'none', border: 'none', cursor: 'pointer', padding: 0 }}
                    >
                      Try again
                    </button>
                  )}
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </PageLayout>
  )
}
