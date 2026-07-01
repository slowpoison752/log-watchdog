"""
Intelligent Observability & Event Watchdog — FastAPI entrypoint.
All routes: GET-only REST + WebSocket /api/stream.
SQLite tables are auto-created on startup; CSVs are auto-ingested if empty.
"""
import asyncio
import json
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

import database
from anomaly_detector import detect_anomalies
from log_parser import parse_all
from webhook_handler import trigger_webhooks

load_dotenv()

# ---------------------------------------------------------------------------
# App lifecycle — init DB + auto-ingest CSVs if logs table is empty
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    os.makedirs("static", exist_ok=True)
    os.makedirs("data",   exist_ok=True)
    database.init_db()

    # Auto-ingest from data/*.csv on cold start (table empty)
    conn = database.get_connection()
    try:
        count = conn.execute("SELECT COUNT(*) FROM logs").fetchone()[0]
    finally:
        conn.close()

    if count == 0:
        logs = parse_all("all")
        if logs:
            conn = database.get_connection()
            try:
                conn.executemany(
                    "INSERT INTO logs (timestamp, severity, source, message, log_source)"
                    " VALUES (?,?,?,?,?)",
                    [
                        (l["timestamp"], l["severity"], l["source"],
                         l["message"],   l["log_source"])
                        for l in logs
                    ],
                )
                conn.commit()
                print(f"[startup] Auto-ingested {len(logs)} log entries from data/")
            finally:
                conn.close()
        else:
            print("[startup] No CSV files found in data/ — skipping auto-ingest")

    yield


app = FastAPI(
    title="Intelligent Observability & Event Watchdog",
    description="Real-time log monitoring, anomaly detection, and alerting.",
    version="1.0.0",
    lifespan=lifespan,
)

app.mount("/static", StaticFiles(directory="static"), name="static")


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

@app.get("/", include_in_schema=False)
async def dashboard():
    return FileResponse("static/index.html")


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@app.get("/health", tags=["system"])
async def health():
    conn = database.get_connection()
    try:
        log_count     = conn.execute("SELECT COUNT(*) FROM logs").fetchone()[0]
        anomaly_count = conn.execute("SELECT COUNT(*) FROM anomalies WHERE is_anomaly=1").fetchone()[0]
        webhook_count = conn.execute("SELECT COUNT(*) FROM webhook_alerts").fetchone()[0]

        critical = conn.execute(
            "SELECT COUNT(*) FROM anomalies WHERE is_anomaly=1 AND z_score>3"
        ).fetchone()[0]

        if critical > 0:
            status = "CRITICAL"
        elif anomaly_count > 0:
            status = "DEGRADED"
        else:
            status = "HEALTHY"
    finally:
        conn.close()

    return {
        "status":        "ok",
        "health":        status,
        "timestamp":     datetime.now(timezone.utc).isoformat(),
        "database":      "sqlite",
        "log_count":     log_count,
        "anomaly_count": anomaly_count,
        "webhook_count": webhook_count,
    }


# ---------------------------------------------------------------------------
# Log Ingest
# ---------------------------------------------------------------------------

@app.get("/api/logs/ingest", tags=["logs"])
async def ingest_logs(source: str = Query("all", description="all | apache | bgl | linux")):
    """Parse CSVs from data/ and reload the logs table (replaces previous data for the source)."""
    loop = asyncio.get_event_loop()
    logs = await loop.run_in_executor(None, lambda: parse_all(source))

    conn = database.get_connection()
    try:
        if source == "all":
            conn.execute("DELETE FROM logs")
        else:
            conn.execute("DELETE FROM logs WHERE log_source=?", (source,))
        conn.executemany(
            "INSERT INTO logs (timestamp, severity, source, message, log_source) VALUES (?,?,?,?,?)",
            [(l["timestamp"], l["severity"], l["source"], l["message"], l["log_source"]) for l in logs],
        )
        conn.commit()
    finally:
        conn.close()

    return {
        "status":   "ok",
        "source":   source,
        "ingested": len(logs),
        "message":  f"Ingested {len(logs)} log entries from source='{source}'",
    }


# ---------------------------------------------------------------------------
# Logs Query
# ---------------------------------------------------------------------------

@app.get("/api/logs", tags=["logs"])
async def get_logs(
    source:   str           = Query("all"),
    limit:    int           = Query(500, ge=1, le=10_000),
    severity: Optional[str] = Query(None),
    search:   Optional[str] = Query(None),
    offset:   int           = Query(0, ge=0),
):
    conn = database.get_connection()
    try:
        sql, params = "SELECT * FROM logs WHERE 1=1", []
        if source != "all":
            sql += " AND log_source=?";   params.append(source)
        if severity:
            sql += " AND severity=?";     params.append(severity)
        if search:
            sql += " AND message LIKE ?"; params.append(f"%{search}%")
        sql += " ORDER BY timestamp ASC LIMIT ? OFFSET ?"
        params += [limit, offset]

        rows  = conn.execute(sql, params).fetchall()
        logs  = [dict(r) for r in rows]
        total_q = "SELECT COUNT(*) FROM logs" + (" WHERE log_source=?" if source != "all" else "")
        total = conn.execute(total_q, [source] if source != "all" else []).fetchone()[0]
    finally:
        conn.close()

    return {"source": source, "total": total, "returned": len(logs), "logs": logs}


# ---------------------------------------------------------------------------
# Anomaly Analysis
# ---------------------------------------------------------------------------

@app.get("/api/analyze", tags=["analysis"])
async def analyze(
    source:      str   = Query("all"),
    window:      int   = Query(15,  ge=1,   le=1440),
    z_threshold: float = Query(2.0, ge=0.1, le=10.0),
    method:      str   = Query("zscore", pattern="^(zscore|iqr|moving_average)$"),
):
    """Run anomaly detection on ingested logs. Stores results and triggers webhooks."""
    conn = database.get_connection()
    try:
        sql, params = "SELECT * FROM logs WHERE 1=1", []
        if source != "all":
            sql += " AND log_source=?"; params.append(source)
        sql += " ORDER BY timestamp ASC"
        rows = conn.execute(sql, params).fetchall()
        logs = [dict(r) for r in rows]
    finally:
        conn.close()

    if not logs:
        return JSONResponse(
            status_code=422,
            content={"error": "No logs in database. Call /api/logs/ingest first.", "anomalies": []},
        )

    results   = detect_anomalies(logs, window_minutes=window, z_threshold=z_threshold, method=method)
    anomalies = [r for r in results if r["is_anomaly"]]

    now = datetime.now(timezone.utc).isoformat()
    conn = database.get_connection()
    try:
        conn.execute("DELETE FROM anomalies")
        conn.executemany(
            """INSERT INTO anomalies
               (window_start, window_end, error_count, total_events, error_rate,
                z_score, method, source, is_anomaly, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            [(r["window_start"], r["window_end"], r["error_count"], r["total_events"],
              r["error_rate"], r["z_score"], r["method"], source,
              1 if r["is_anomaly"] else 0, now) for r in results],
        )
        conn.commit()
    finally:
        conn.close()

    triggered = trigger_webhooks(anomalies, source)

    return {
        "source":             source,
        "window_minutes":     window,
        "z_threshold":        z_threshold,
        "method":             method,
        "total_windows":      len(results),
        "anomaly_count":      len(anomalies),
        "webhooks_triggered": len(triggered),
        "results":            results,
    }


# ---------------------------------------------------------------------------
# Anomalies Store
# ---------------------------------------------------------------------------

@app.get("/api/anomalies", tags=["analysis"])
async def get_anomalies(source: str = Query("all")):
    conn = database.get_connection()
    try:
        sql, params = "SELECT * FROM anomalies WHERE is_anomaly=1", []
        if source != "all":
            sql += " AND source=?"; params.append(source)
        sql += " ORDER BY window_start ASC"
        rows = conn.execute(sql, params).fetchall()
        anomalies = [dict(r) for r in rows]
    finally:
        conn.close()
    return {"source": source, "count": len(anomalies), "anomalies": anomalies}


# ---------------------------------------------------------------------------
# Webhook Alert Log
# ---------------------------------------------------------------------------

@app.get("/api/webhooks", tags=["webhooks"])
async def get_webhooks(limit: int = Query(100, ge=1, le=1000)):
    conn = database.get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM webhook_alerts ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
        webhooks = []
        for r in rows:
            d = dict(r)
            try:
                d["payload_json"] = json.loads(d.get("payload", "{}"))
            except Exception:
                d["payload_json"] = {}
            webhooks.append(d)
    finally:
        conn.close()
    return {"count": len(webhooks), "webhooks": webhooks}


# ---------------------------------------------------------------------------
# Metrics Summary
# ---------------------------------------------------------------------------

@app.get("/api/metrics", tags=["metrics"])
async def get_metrics():
    conn = database.get_connection()
    try:
        total       = conn.execute("SELECT COUNT(*) FROM logs").fetchone()[0]
        error_count = conn.execute(
            "SELECT COUNT(*) FROM logs WHERE severity IN ('error','fatal','warning','warn')"
        ).fetchone()[0]
        anomaly_count = conn.execute("SELECT COUNT(*) FROM anomalies WHERE is_anomaly=1").fetchone()[0]
        webhook_count = conn.execute("SELECT COUNT(*) FROM webhook_alerts").fetchone()[0]

        src_rows = conn.execute(
            "SELECT log_source, COUNT(*) as cnt FROM logs GROUP BY log_source"
        ).fetchall()
        sources = {r["log_source"]: r["cnt"] for r in src_rows}

        critical = conn.execute(
            "SELECT COUNT(*) FROM anomalies WHERE is_anomaly=1 AND z_score>3"
        ).fetchone()[0]

        if critical > 0:
            health = "CRITICAL"
        elif anomaly_count > 0:
            health = "DEGRADED"
        else:
            health = "HEALTHY"
    finally:
        conn.close()

    return {
        "total_logs":    total,
        "error_count":   error_count,
        "error_rate":    round(error_count / total * 100, 1) if total > 0 else 0.0,
        "anomaly_count": anomaly_count,
        "webhook_count": webhook_count,
        "health_status": health,
        "sources":       sources,
    }


# ---------------------------------------------------------------------------
# Severity Distribution
# ---------------------------------------------------------------------------

@app.get("/api/severity-distribution", tags=["metrics"])
async def severity_distribution(source: str = Query("all")):
    conn = database.get_connection()
    try:
        sql, params = "SELECT severity, COUNT(*) as cnt FROM logs WHERE 1=1", []
        if source != "all":
            sql += " AND log_source=?"; params.append(source)
        sql += " GROUP BY severity ORDER BY cnt DESC"
        rows = conn.execute(sql, params).fetchall()
        distribution = {r["severity"]: r["cnt"] for r in rows}
    finally:
        conn.close()
    return {"source": source, "distribution": distribution}


# ---------------------------------------------------------------------------
# Source Breakdown
# ---------------------------------------------------------------------------

@app.get("/api/source-breakdown", tags=["metrics"])
async def source_breakdown():
    conn = database.get_connection()
    try:
        breakdown = {}
        for src in ("apache", "bgl", "linux"):
            total = conn.execute(
                "SELECT COUNT(*) FROM logs WHERE log_source=?", (src,)
            ).fetchone()[0]
            errors = conn.execute(
                "SELECT COUNT(*) FROM logs WHERE log_source=?"
                " AND severity IN ('error','fatal','warning','warn')",
                (src,),
            ).fetchone()[0]
            breakdown[src] = {
                "count":      total,
                "error_count": errors,
                "error_rate": round(errors / total * 100, 1) if total > 0 else 0.0,
            }
    finally:
        conn.close()
    return {"breakdown": breakdown}


# ---------------------------------------------------------------------------
# WebSocket — Simulated Live Feed
# ---------------------------------------------------------------------------

@app.websocket("/api/stream")
async def stream_logs(websocket: WebSocket, source: str = "all"):
    """Stream all ingested logs one-by-one at 300 ms intervals."""
    await websocket.accept()
    try:
        conn = database.get_connection()
        try:
            sql, params = "SELECT * FROM logs WHERE 1=1", []
            if source != "all":
                sql += " AND log_source=?"; params.append(source)
            sql += " ORDER BY timestamp ASC"
            rows = conn.execute(sql, params).fetchall()
            logs = [dict(r) for r in rows]
        finally:
            conn.close()

        if not logs:
            await websocket.send_json(
                {"_error": "No logs in database. Call /api/logs/ingest first.", "_done": True}
            )
            return

        total = len(logs)
        for i, log in enumerate(logs):
            try:
                await websocket.send_json({**log, "_index": i, "_total": total})
                await asyncio.sleep(0.3)
            except (WebSocketDisconnect, RuntimeError):
                return

        try:
            await websocket.send_json({"_done": True, "_total": total})
        except Exception:
            pass

    except WebSocketDisconnect:
        pass
