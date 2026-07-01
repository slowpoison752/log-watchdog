import sqlite3
import os
from dotenv import load_dotenv

load_dotenv()

DB_PATH = os.getenv("DB_PATH", "watchdog.db")


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db() -> None:
    conn = get_connection()
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS logs (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp   TEXT,
                severity    TEXT,
                source      TEXT,
                message     TEXT,
                log_source  TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_logs_source    ON logs(log_source);
            CREATE INDEX IF NOT EXISTS idx_logs_severity  ON logs(severity);
            CREATE INDEX IF NOT EXISTS idx_logs_timestamp ON logs(timestamp);

            CREATE TABLE IF NOT EXISTS anomalies (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                window_start TEXT,
                window_end   TEXT,
                error_count  INTEGER,
                total_events INTEGER,
                error_rate   TEXT,
                z_score      REAL,
                method       TEXT,
                source       TEXT,
                is_anomaly   INTEGER DEFAULT 0,
                created_at   TEXT
            );

            CREATE TABLE IF NOT EXISTS webhook_alerts (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                alert_id    TEXT UNIQUE,
                event_type  TEXT,
                created_at  TEXT,
                source      TEXT,
                window_start TEXT,
                window_end   TEXT,
                error_count  INTEGER,
                total_events INTEGER,
                error_rate   TEXT,
                z_score      REAL,
                severity     TEXT,
                method       TEXT,
                webhook_url  TEXT,
                action       TEXT,
                payload      TEXT
            );
        """)
        conn.commit()
    finally:
        conn.close()
