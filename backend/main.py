from fastapi import FastAPI, Depends, Request, HTTPException, WebSocket
from fastapi.websockets import WebSocketDisconnect
import asyncio
import json
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from backend.database import init_db, get_db
from backend.dependencies import get_settings
from backend.auth import get_current_user
from backend import models
from sqlalchemy.orm import Session
from sqlalchemy import or_
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
import socket

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    init_db()
    # Move per-case Qdrant indexes onto a fast disk when the cases directory
    # is on a rotating one. The upsert is ~92% of ingestion time and is
    # seek-latency bound, so this is the difference between a job that takes a
    # minute and one that takes eight. Idempotent; a no-op on an all-SSD box.
    try:
        from backend.modules.vector_store import migrate_qdrant_layout
        migrate_qdrant_layout()
    except Exception as e:
        print(f"[STARTUP] Qdrant layout migration skipped: {e}")
    from backend.modules.job_worker import start_worker, set_main_loop
    # The ingestion worker runs in a background thread but must send
    # progress over WebSockets owned by *this* event loop. Hand it the loop
    # so it can schedule sends with run_coroutine_threadsafe instead of
    # spinning up a throwaway loop of its own.
    set_main_loop(asyncio.get_running_loop())
    start_worker()
    print(f"Database initialized")
    print("Ingestion queue worker started")
    print(f"IDF AI Assistant Backend starting on http://localhost:8000")
    yield
    # Shutdown
    from backend.modules.job_worker import stop_worker
    stop_worker()
    print("IDF AI Assistant Backend shutting down")


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="Intelligent Digital Forensic AI Assistant API",
    lifespan=lifespan,
)

# CORS — allows React frontend on port 3000
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Rate limiter — 200 req/min globally
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["200/minute"]
)
app.state.limiter = limiter
app.add_exception_handler(
    RateLimitExceeded,
    _rate_limit_exceeded_handler
)

from backend.routers import (
    cases, evidence, queries, entities,
    notes, audit, reports, watchlist,
    auth_router, credentials, case_access,
)
from backend.routers import queue_router

# Include all routers
app.include_router(auth_router.router)
app.include_router(cases.router)
app.include_router(evidence.router)
app.include_router(queries.router)
app.include_router(entities.router)
app.include_router(notes.router)
app.include_router(audit.router)
app.include_router(queue_router.router, prefix="/api")
app.include_router(reports.router)
app.include_router(watchlist.router)
app.include_router(credentials.router)
app.include_router(case_access.router)


# ── WebSocket connection manager ─────────────────────────────────────────────

class ConnectionManager:
    """
    Tracks all active WebSocket connections.
    Connections are keyed by case_id for case-specific broadcasts,
    or stored in global_connections for app-wide events.
    """
    def __init__(self):
        self.active: dict[str, list] = {}  # case_id → [WebSocket, ...]
        self.global_connections: list = []

    async def connect_case(self, ws: WebSocket, case_id: str):
        await ws.accept()
        self.active.setdefault(case_id, []).append(ws)

    async def connect_global(self, ws: WebSocket):
        await ws.accept()
        self.global_connections.append(ws)

    def disconnect(self, ws: WebSocket, case_id: str = None):
        if case_id and case_id in self.active:
            self.active[case_id] = [c for c in self.active[case_id] if c is not ws]
        if ws in self.global_connections:
            self.global_connections.remove(ws)

    async def broadcast_to_case(self, case_id: str, message: dict):
        dead = []
        for ws in list(self.active.get(case_id, [])):
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)
        for d in dead:
            try:
                self.active[case_id].remove(d)
            except ValueError:
                pass

    async def broadcast_global(self, message: dict):
        dead = []
        for ws in list(self.global_connections):
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)
        for d in dead:
            try:
                self.global_connections.remove(d)
            except ValueError:
                pass


ws_manager = ConnectionManager()


# ── WebSocket endpoints ───────────────────────────────────────────────────────

@app.websocket("/ws/cases/{case_id}")
async def case_websocket(
    websocket: WebSocket,
    case_id: str,
    token: str = None,
):
    """Case-specific WebSocket — clients subscribe to events for one case."""
    await ws_manager.connect_case(websocket, case_id)
    try:
        while True:
            await websocket.receive_text()   # keep connection alive
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket, case_id)


@app.websocket("/ws/global")
async def global_websocket(
    websocket: WebSocket,
    token: str = None,
):
    """Global WebSocket — receives all events across all cases."""
    await ws_manager.connect_global(websocket)
    try:
        while True:
            await websocket.receive_text()   # keep connection alive
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)


# ── Notification helper (called from background threads) ─────────────────────

async def _notify_case(case_id: str, event_type: str, data: dict):
    """
    Broadcasts an event to all WebSocket clients subscribed to a case
    AND to all global subscribers.
    Safe to await from any async context.
    """
    payload = {"type": event_type, **data}
    global_payload = {"type": event_type, "case_id": case_id, **data}
    try:
        await ws_manager.broadcast_to_case(case_id, payload)
        await ws_manager.broadcast_global(global_payload)
    except Exception as e:
        print(f"[WS] Notify error: {e}")


@app.get("/api/health")
def health_check():
    return {
        "status": "healthy",
        "app": settings.app_name,
        "version": settings.app_version,
        "machine": socket.gethostname(),
    }


@app.get("/api/status")
def system_status():
    """
    Returns the MEASURED status of every backend service.

    This used to answer with three values, two of them fictional:
    "database" was os.path.exists() on a hardcoded path reported as
    "connected" (existence is not connectivity - a corrupt, locked or
    read-only database file exists perfectly happily), and "ollama" was
    "running" whenever /api/tags answered 200, which it also does with an
    EMPTY model list, so a machine with zero models installed reported a
    healthy AI (AGENTS.md §6 B5, §15).

    The probes live in backend/modules/service_health.py. They follow one
    invariant (AGENTS.md §16): a metric that cannot be measured is None
    plus a reason, never a fabricated 0, False or "ok", and a probe that
    fails degrades to state "unavailable" for that one service rather
    than taking the whole response down with it.

    The legacy top-level keys (database / ollama / models / cases_dir)
    are preserved for the existing consumers. They are lossy, and they
    collapse towards not-fabricating: "ollama" is "running" only when a
    model is actually ready to answer.
    """
    from backend.modules.service_health import collect_status
    return collect_status(settings.cases_dir)



@app.get("/api/media/capabilities")
def media_capabilities():
    """
    Returns which media extraction features
    are available based on installed system
    libraries (Tesseract, Whisper, ffmpeg).
    """
    from backend.modules.media_extractor \
        import get_media_capabilities
    caps = get_media_capabilities()
    return {
        "capabilities": caps,
        "install_notes": {
            "ocr": (
                "Requires tesseract: "
                "brew install tesseract"
            ),
            "audio": (
                "Requires whisper + ffmpeg: "
                "pip install openai-whisper && "
                "brew install ffmpeg"
            ),
            "video": (
                "Requires ffmpeg + whisper: "
                "brew install ffmpeg && "
                "pip install openai-whisper"
            ),
            "email_msg": (
                "pip install extract-msg"
            )
        }
    }


@app.get("/api/activity")
def get_global_activity(
    q: str = None,
    action_type: str = None,
    performed_by: str = None,
    case_id: str = None,
    date_from: str = None,
    date_to: str = None,
    page: int = 1,
    page_size: int = 50,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Returns all audit log entries across
    all cases with filtering and pagination.
    Accessible to Analyst and above.
    """
    from datetime import datetime
    from sqlalchemy import or_, func

    query = db.query(models.AuditLog)

    # Free text search across performed_by, action_type, details
    if q:
        query = query.filter(
            or_(
                models.AuditLog.performed_by.contains(q),
                models.AuditLog.action_type.contains(q),
                models.AuditLog.details.contains(q)
            )
        )

    if action_type:
        query = query.filter(models.AuditLog.action_type == action_type)

    if performed_by:
        query = query.filter(models.AuditLog.performed_by == performed_by)

    if case_id:
        query = query.filter(models.AuditLog.case_id == case_id)

    if date_from:
        try:
            dt = datetime.fromisoformat(date_from)
            query = query.filter(models.AuditLog.performed_at >= dt)
        except:
            pass

    if date_to:
        try:
            dt = datetime.fromisoformat(date_to)
            query = query.filter(models.AuditLog.performed_at <= dt)
        except:
            pass

    total = query.count()

    logs = query.order_by(
        models.AuditLog.performed_at.desc()
    ).offset((page - 1) * page_size).limit(page_size).all()

    # Get distinct action types for filter dropdown
    all_types = db.query(models.AuditLog.action_type).distinct().all()

    # Get distinct users
    all_users = db.query(models.AuditLog.performed_by).distinct().all()

    # Get cases for filter
    cases = db.query(
        models.Case.id,
        models.Case.case_name
    ).filter(models.Case.status != 'Archived').all()

    return {
        "items": [{
            "id": log.id,
            "case_id": log.case_id,
            "action_type": log.action_type,
            "performed_by": log.performed_by,
            "performed_at": str(log.performed_at),
            "details": __import__('json').loads(log.details or '{}'),
            "severity": log.severity or "info",
            "machine_id": log.machine_id
        } for log in logs],
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": ((total + page_size - 1) // page_size),
        "has_next": page * page_size < total,
        "has_prev": page > 1,
        "filter_options": {
            "action_types": [t[0] for t in all_types if t[0]],
            "users": [u[0] for u in all_users if u[0]],
            "cases": [{"id": c[0], "name": c[1]} for c in cases],
            "severity_counts": dict(
                db.query(
                    models.AuditLog.severity,
                    func.count(models.AuditLog.id)
                ).group_by(
                    models.AuditLog.severity
                ).all()
            )
        }
    }



@app.get("/api/dashboard/stats")
def dashboard_stats(
    current_user: models.User = Depends(
        get_current_user),
    db: Session = Depends(get_db)
):
    """
    Returns aggregate statistics across
    the entire system for the dashboard.
    Safe against empty tables — all counts
    default to 0.
    """
    from collections import defaultdict
    from sqlalchemy import func
    import json

    # Case counts by status / priority
    all_cases = db.query(models.Case).filter(
        models.Case.status != "Archived"
    ).all()

    status_counts = defaultdict(int)
    priority_counts = defaultdict(int)
    for c in all_cases:
        status_counts[c.status] += 1
        priority_counts[c.priority] += 1

    # Evidence stats
    total_evidence = db.query(
        models.Evidence).count()
    indexed_evidence = db.query(
        models.Evidence).filter(
        models.Evidence.status == "Indexed"
    ).count()
    failed_evidence = db.query(
        models.Evidence).filter(
        models.Evidence.status == "Failed"
    ).count()

    # Query stats
    total_queries = db.query(
        models.QueryLog).count()
    flagged_queries = db.query(
        models.QueryLog).filter(
        models.QueryLog.is_flagged == True
    ).count()

    # Entity stats — count by type
    total_entities = db.query(
        models.Entity).count()
    entity_type_counts = dict(
        db.query(
            models.Entity.entity_type,
            func.count(models.Entity.id)
        ).group_by(
            models.Entity.entity_type
        ).all()
    )

    # Artifact / anomaly stats
    total_artifacts = db.query(
        models.ForensicArtifact).count()
    anomaly_count = db.query(
        models.ForensicArtifact).filter(
        models.ForensicArtifact.is_anomaly
            == True
    ).count()

    # Recent audit events (last 10)
    recent_audit = db.query(
        models.AuditLog
    ).order_by(
        models.AuditLog.performed_at.desc()
    ).limit(10).all()

    # User stats — Admin only
    user_stats = None
    if current_user.role == "Admin":
        total_users = db.query(
            models.User).count()
        active_users = db.query(
            models.User).filter(
            models.User.is_active == True
        ).count()
        role_counts = dict(
            db.query(
                models.User.role,
                func.count(models.User.id)
            ).group_by(
                models.User.role
            ).all()
        )
        user_stats = {
            "total": total_users,
            "active": active_users,
            "by_role": role_counts
        }

    # Recent cases (last 5)
    recent_cases = db.query(
        models.Case
    ).filter(
        models.Case.status != "Archived"
    ).order_by(
        models.Case.created_at.desc()
    ).limit(5).all()

    # System alerts
    alerts = []
    
    integrity_failures = db.query(models.AuditLog).filter(
        models.AuditLog.action_type == "INTEGRITY_FAILED"
    ).count()
    if integrity_failures > 0:
        alerts.append({
            "level": "critical",
            "title": "Integrity Failures",
            "message": f"{integrity_failures} file(s) failed integrity check",
            "action": "/activity"
        })
        
    locked = db.query(models.User).filter(
        models.User.locked_until != None
    ).count()
    if locked > 0:
        alerts.append({
            "level": "warning",
            "title": "Locked Accounts",
            "message": f"{locked} account(s) temporarily locked",
            "action": "/admin/users"
        })
        
    failed_jobs = db.query(models.Evidence).filter(
        models.Evidence.status == "Failed"
    ).count()
    if failed_jobs > 0:
        alerts.append({
            "level": "warning",
            "title": "Ingestion Failures",
            "message": f"{failed_jobs} evidence file(s) failed to ingest",
            "action": "/queue"
        })
        
    if not alerts:
        alerts.append({
            "level": "info",
            "title": "All Systems Operational",
            "message": "No active alerts. System running normally.",
            "action": None
        })

    return {
        "cases": {
            "total": len(all_cases),
            "by_status": dict(status_counts),
            "by_priority": dict(priority_counts)
        },
        "evidence": {
            "total": total_evidence,
            "indexed": indexed_evidence,
            "failed": failed_evidence,
            "processing": max(
                0,
                total_evidence
                - indexed_evidence
                - failed_evidence
            )
        },
        "queries": {
            "total": total_queries,
            "flagged": flagged_queries
        },
        "entities": {
            "total": total_entities,
            "by_type": entity_type_counts
        },
        "artifacts": {
            "total": total_artifacts,
            "anomalies": anomaly_count
        },
        "users": user_stats,
        "recent_activity": [{
            "action": a.action_type,
            "by": a.performed_by,
            "at": str(a.performed_at),
            "case_id": a.case_id,
            "details": json.loads(
                a.details or '{}')
        } for a in recent_audit],
        "recent_cases": [{
            "id": c.id,
            "case_name": c.case_name,
            "status": c.status,
            "priority": c.priority,
            "created_at": str(c.created_at)
        } for c in recent_cases],
        "total_activity": db.query(models.AuditLog).count(),
        "alerts": alerts
    }



# Run with: uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000


def _extract_snippet(
        text: str, query: str,
        context: int = 100) -> str:
    """
    Extracts a snippet around the first
    occurrence of query in text.
    """
    if not text:
        return ""
    idx = text.lower().find(query.lower())
    if idx == -1:
        return text[:200] + "..."
    start = max(0, idx - context)
    end = min(len(text), idx + len(query) + context)
    snippet = text[start:end]
    if start > 0:
        snippet = "..." + snippet
    if end < len(text):
        snippet = snippet + "..."
    return snippet


@app.get("/api/search")
def global_search(
    q: str,
    case_id: str = None,
    limit: int = 20,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Searches across cases, entities,
    artifacts, queries, and notes.
    Optionally scoped to one case.
    Returns grouped results.
    """
    if not q or len(q.strip()) < 2:
        raise HTTPException(
            status_code=400,
            detail="Query must be at least 2 characters"
        )

    q = q.strip()
    results = {}

    # ── Cases ─────────────────────────
    if not case_id:
        case_query = db.query(
            models.Case
        ).filter(
            models.Case.status != "Archived",
            or_(
                models.Case.case_name.contains(q),
                models.Case.description.contains(q),
                models.Case.case_number.contains(q)
            )
        ).limit(limit).all()

        results["cases"] = [{
            "id": c.id,
            "case_name": c.case_name,
            "case_number": c.case_number,
            "status": c.status,
            "priority": c.priority,
            "match_field": (
                "case_name"
                if q.lower() in c.case_name.lower()
                else "description"
            )
        } for c in case_query]

    # ── Entities ──────────────────────
    entity_query = db.query(
        models.Entity
    ).filter(
        models.Entity.name.contains(q)
    )
    if case_id:
        entity_query = entity_query.filter(
            models.Entity.case_id == case_id)
    entities_found = entity_query.order_by(
        models.Entity.frequency.desc()
    ).limit(limit).all()

    results["entities"] = [{
        "id": e.id,
        "case_id": e.case_id,
        "name": e.name,
        "entity_type": e.entity_type,
        "frequency": e.frequency,
        "is_flagged": e.is_flagged
    } for e in entities_found]

    # ── Artifacts ─────────────────────
    artifact_query = db.query(
        models.ForensicArtifact
    ).filter(
        or_(
            models.ForensicArtifact.filename.contains(q),
            models.ForensicArtifact.internal_path.contains(q),
            models.ForensicArtifact.extracted_text.contains(q)
        )
    )
    if case_id:
        artifact_query = artifact_query.filter(
            models.ForensicArtifact.case_id == case_id)
    artifacts_found = artifact_query.limit(limit).all()

    results["artifacts"] = [{
        "id": a.id,
        "case_id": a.case_id,
        "evidence_id": a.evidence_id,
        "filename": a.filename,
        "internal_path": a.internal_path,
        "extraction_type": a.extraction_type,
        "modified_at": str(a.modified_at) if a.modified_at else None,
        "is_flagged": a.is_flagged,
        "text_snippet": (
            _extract_snippet(a.extracted_text, q)
            if a.extracted_text else None
        )
    } for a in artifacts_found]

    # ── Queries ───────────────────────
    query_search = db.query(
        models.QueryLog
    ).filter(
        or_(
            models.QueryLog.question_text.contains(q),
            models.QueryLog.processed_response.contains(q)
        )
    )
    if case_id:
        query_search = query_search.filter(
            models.QueryLog.case_id == case_id)
    queries_found = query_search.order_by(
        models.QueryLog.asked_at.desc()
    ).limit(limit).all()

    results["queries"] = [{
        "id": ql.id,
        "case_id": ql.case_id,
        "question_text": ql.question_text,
        "asked_by": ql.asked_by,
        "asked_at": str(ql.asked_at),
        "is_flagged": ql.is_flagged,
        "snippet": _extract_snippet(
            ql.processed_response, q)
    } for ql in queries_found]

    # ── Notes ─────────────────────────
    note_search = db.query(
        models.Note
    ).filter(
        models.Note.content.contains(q)
    )
    if case_id:
        note_search = note_search.filter(
            models.Note.case_id == case_id)
    notes_found = note_search.order_by(
        models.Note.created_at.desc()
    ).limit(limit).all()

    results["notes"] = [{
        "id": n.id,
        "case_id": n.case_id,
        "author": n.author,
        "created_at": str(n.created_at),
        "snippet": _extract_snippet(n.content, q)
    } for n in notes_found]

    # Total across all categories
    results["total"] = sum(
        len(v) for v in results.values()
        if isinstance(v, list)
    )
    results["query"] = q

    return results


# ---------------------------------------------------------------------------
# GET /api/cases/{case_id}/geomap
# Returns GPS data from EXIF + IP geolocation
# ---------------------------------------------------------------------------

@app.get("/api/cases/{case_id}/geomap")
def get_geo_data(
    case_id: str,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Returns geographic data for the case:
    - GPS coordinates from EXIF image metadata
    - IP geolocation via ip-api.com (free, no key)
    """
    import requests as http_requests

    results = {
        "gps_points": [],
        "ip_points": []
    }

    # ── GPS points from artifacts ──────────────────────────
    gps_artifacts = db.query(
        models.ForensicArtifact
    ).filter(
        models.ForensicArtifact.case_id == case_id,
        models.ForensicArtifact.gps_latitude != None,
        models.ForensicArtifact.gps_longitude != None
    ).all()

    for a in gps_artifacts:
        results["gps_points"].append({
            "lat": a.gps_latitude,
            "lon": a.gps_longitude,
            "label": a.filename,
            "path": a.internal_path,
            "modified": a.modified_at,
            "type": "gps"
        })

    # ── IP entities — geolocate up to 20 ───────────────────
    ip_entities = db.query(
        models.Entity
    ).filter(
        models.Entity.case_id == case_id,
        models.Entity.entity_type == "IP"
    ).all()

    for entity in ip_entities[:20]:
        ip = entity.name.strip()

        # Skip private / loopback addresses
        if (ip.startswith("192.168.") or
                ip.startswith("10.") or
                ip.startswith("172.16.") or
                ip.startswith("172.17.") or
                ip.startswith("172.18.") or
                ip.startswith("172.19.") or
                ip.startswith("172.20.") or
                ip.startswith("172.21.") or
                ip.startswith("172.22.") or
                ip.startswith("172.23.") or
                ip.startswith("172.24.") or
                ip.startswith("172.25.") or
                ip.startswith("172.26.") or
                ip.startswith("172.27.") or
                ip.startswith("172.28.") or
                ip.startswith("172.29.") or
                ip.startswith("172.30.") or
                ip.startswith("172.31.") or
                ip == "127.0.0.1" or
                ip == "::1"):
            results["ip_points"].append({
                "ip": ip,
                "label": f"{ip} (private)",
                "lat": None,
                "lon": None,
                "city": "Private Network",
                "country": "N/A",
                "isp": "",
                "type": "ip_private"
            })
            continue

        try:
            geo = http_requests.get(
                f"http://ip-api.com/json/{ip}"
                f"?fields=status,country,city,lat,lon,isp",
                timeout=5
            ).json()

            if geo.get("status") == "success":
                results["ip_points"].append({
                    "ip": ip,
                    "lat": geo["lat"],
                    "lon": geo["lon"],
                    "city": geo.get("city", ""),
                    "country": geo.get("country", ""),
                    "isp": geo.get("isp", ""),
                    "label": (
                        f"{ip} \u2014 "
                        f"{geo.get('city', '')}, "
                        f"{geo.get('country', '')}"
                    ),
                    "type": "ip"
                })
            else:
                results["ip_points"].append({
                    "ip": ip,
                    "lat": None,
                    "lon": None,
                    "city": "",
                    "country": "",
                    "isp": "",
                    "label": ip,
                    "type": "ip_unknown"
                })
        except Exception:
            pass

    results["total_gps"] = len(results["gps_points"])
    results["total_ips"] = len([
        p for p in results["ip_points"]
        if p.get("lat") is not None
    ])
    return results


# ---------------------------------------------------------------------------
# GET /api/entities/cross-case-search
# Searches for an entity name across all cases
# ---------------------------------------------------------------------------

@app.get("/api/entities/cross-case-search")
def cross_case_entity_search(
    name: str,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Searches for an entity name across ALL cases. 
    Returns every case where this entity appears.
    Used to link the same suspect or location across multiple investigations.
    """
    if not name or len(name.strip()) < 2:
        raise HTTPException(
            status_code=400,
            detail="Name too short"
        )

    from sqlalchemy import func
    matches = db.query(
        models.Entity,
        models.Case
    ).join(
        models.Case,
        models.Entity.case_id == models.Case.id
    ).filter(
        models.Entity.name.contains(name.strip()),
        models.Case.status != "Archived"
    ).all()

    # Group by case
    by_case = {}
    for entity, case in matches:
        if case.id not in by_case:
            by_case[case.id] = {
                "case_id": case.id,
                "case_name": case.case_name,
                "case_number": case.case_number,
                "case_status": case.status,
                "entities": []
            }
        by_case[case.id]["entities"].append({
            "id": entity.id,
            "name": entity.name,
            "entity_type": entity.entity_type,
            "frequency": entity.frequency,
            "is_flagged": entity.is_flagged
        })

    return {
        "query": name,
        "total_cases": len(by_case),
        "total_matches": len(matches),
        "results": list(by_case.values())
    }
