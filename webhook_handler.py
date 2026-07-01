"""
Webhook Handler — generates structured alert payloads and logs them to SQLite.
No external HTTP POST is made in the scaffold; payloads are stored and queryable.
"""
import json
import os
import uuid
from datetime import datetime, timezone

import database

DEFAULT_WEBHOOK_URL = os.getenv("WEBHOOK_URL", "https://hooks.example.com/sre/alerts")


def generate_payload(
    anomaly: dict,
    source: str,
    webhook_url: str = DEFAULT_WEBHOOK_URL,
) -> dict:
    """Build a structured webhook payload from an anomaly result dict."""
    z     = anomaly.get("z_score", 0.0)
    sev   = "CRITICAL" if z > 3 else "WARNING"
    action = "PAGE_ON_CALL" if sev == "CRITICAL" else "NOTIFY"

    return {
        "id":           f"WH-{uuid.uuid4().hex[:8].upper()}",
        "event":        "anomaly_detected",
        "timestamp":    datetime.now(timezone.utc).isoformat(),
        "source":       source,
        "window_start": anomaly.get("window_start", ""),
        "window_end":   anomaly.get("window_end", ""),
        "error_count":  anomaly.get("error_count", 0),
        "total_events": anomaly.get("total_events", 0),
        "error_rate":   anomaly.get("error_rate", "0.0%"),
        "z_score":      round(z, 4),
        "severity":     sev,
        "method":       anomaly.get("method", "z_score"),
        "webhook_url":  webhook_url,
        "action":       action,
    }


def trigger_webhooks(
    anomalies: list[dict],
    source: str,
    webhook_url: str = DEFAULT_WEBHOOK_URL,
) -> list[dict]:
    """
    For every anomaly flagged as is_anomaly=True, generate a payload,
    persist it to webhook_alerts, and return the list of triggered payloads.
    """
    triggered: list[dict] = []
    conn = database.get_connection()
    try:
        for anomaly in anomalies:
            if not anomaly.get("is_anomaly"):
                continue
            payload = generate_payload(anomaly, source, webhook_url)
            try:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO webhook_alerts
                        (alert_id, event_type, created_at, source,
                         window_start, window_end, error_count, total_events,
                         error_rate, z_score, severity, method,
                         webhook_url, action, payload)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        payload["id"],        payload["event"],
                        payload["timestamp"], payload["source"],
                        payload["window_start"], payload["window_end"],
                        payload["error_count"],  payload["total_events"],
                        payload["error_rate"],   payload["z_score"],
                        payload["severity"],     payload["method"],
                        payload["webhook_url"],  payload["action"],
                        json.dumps(payload),
                    ),
                )
                triggered.append(payload)
            except Exception:
                pass
        conn.commit()
    finally:
        conn.close()
    return triggered
