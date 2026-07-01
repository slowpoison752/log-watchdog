"""
Log Parser — reads pre-structured CSV files from data/ and normalises them
into a unified schema: {timestamp, severity, source, message, log_source}.
"""
import csv
import os
from datetime import datetime
from typing import Optional

from dotenv import load_dotenv

load_dotenv()

DATA_DIR = os.getenv("DATA_DIR", "data")

# Severity level mappings per source
_SEVERITY_MAP = {
    "apache": {
        "error":  "error",
        "notice": "notice",
        "warn":   "warn",
        "crit":   "error",
        "alert":  "error",
        "emerg":  "error",
        "debug":  "notice",
        "info":   "notice",
    },
    "bgl": {
        "FATAL":   "fatal",
        "WARNING": "warning",
        "INFO":    "info",
        "SEVERE":  "fatal",
        "ERROR":   "error",
    },
    "linux": {
        "error": "error",
        "warn":  "warn",
        "info":  "info",
        "debug": "info",
    },
}

# Keywords that elevate severity to at least "warn" for Linux auth events
_AUTH_KEYWORDS = (
    "authentication failure",
    "invalid user",
    "Failed password",
    "Connection closed by",
    "refused connect",
    "FAILED LOGIN",
)

# Timestamp formats to attempt, in order
_TS_FORMATS = [
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d %H:%M:%S.%f",
    "%d/%b/%Y:%H:%M:%S",
    "%b %d %H:%M:%S",
    "%b  %d %H:%M:%S",
]


def _parse_ts(raw: str) -> Optional[datetime]:
    raw = raw.strip()
    for fmt in _TS_FORMATS:
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    return None


def _normalise_severity(raw: str, log_source: str) -> str:
    return _SEVERITY_MAP.get(log_source, {}).get(raw.strip(), raw.strip().lower())


def _elevate_linux_severity(msg: str, current: str) -> str:
    """Raise severity to at least 'warn' when auth-related keywords appear."""
    for kw in _AUTH_KEYWORDS:
        if kw.lower() in msg.lower():
            if current == "info":
                return "warn"
            return current
    return current


# ---------------------------------------------------------------------------
# Per-source parsers
# ---------------------------------------------------------------------------

def parse_apache(filepath: str) -> list[dict]:
    results: list[dict] = []
    try:
        with open(filepath, newline="", encoding="utf-8", errors="replace") as f:
            reader = csv.DictReader(f)
            for row in reader:
                ts = _parse_ts(row.get("timestamp", ""))
                sev = _normalise_severity(row.get("severity", "notice"), "apache")
                results.append({
                    "timestamp": ts.isoformat() if ts else row.get("timestamp", ""),
                    "severity":  sev,
                    "source":    row.get("source", "apache"),
                    "message":   row.get("message", ""),
                    "log_source": "apache",
                    "_ts": ts or datetime.min,
                })
    except FileNotFoundError:
        pass
    return results


def parse_bgl(filepath: str) -> list[dict]:
    results: list[dict] = []
    try:
        with open(filepath, newline="", encoding="utf-8", errors="replace") as f:
            reader = csv.DictReader(f)
            for row in reader:
                ts = _parse_ts(row.get("timestamp", ""))
                sev = _normalise_severity(row.get("severity", "INFO"), "bgl")
                component = row.get("component", "")
                node = row.get("node", "")
                raw_msg = row.get("message", "")
                # Enrich message with component/node context
                parts = []
                if component:
                    parts.append(f"[{component}]")
                if node:
                    parts.append(f"[{node}]")
                message = " ".join(parts + [raw_msg]).strip()
                results.append({
                    "timestamp": ts.isoformat() if ts else row.get("timestamp", ""),
                    "severity":  sev,
                    "source":    row.get("source", "bgl"),
                    "message":   message,
                    "log_source": "bgl",
                    "_ts": ts or datetime.min,
                })
    except FileNotFoundError:
        pass
    return results


def parse_linux(filepath: str) -> list[dict]:
    results: list[dict] = []
    try:
        with open(filepath, newline="", encoding="utf-8", errors="replace") as f:
            reader = csv.DictReader(f)
            for row in reader:
                ts = _parse_ts(row.get("timestamp", ""))
                sev = _normalise_severity(row.get("severity", "info"), "linux")
                service = row.get("service", "")
                pid = row.get("pid", "")
                msg = row.get("message", "")
                sev = _elevate_linux_severity(msg, sev)
                source_label = f"{service}[{pid}]" if service and pid else service or row.get("source", "linux")
                results.append({
                    "timestamp": ts.isoformat() if ts else row.get("timestamp", ""),
                    "severity":  sev,
                    "source":    source_label,
                    "message":   msg,
                    "log_source": "linux",
                    "_ts": ts or datetime.min,
                })
    except FileNotFoundError:
        pass
    return results


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse_all(source: str = "all") -> list[dict]:
    """
    Parse one or all CSV sources, return records sorted by timestamp ascending.
    source: 'all' | 'apache' | 'bgl' | 'linux'
    """
    _parsers = {
        "apache": (parse_apache, os.path.join(DATA_DIR, "apache_logs.csv")),
        "bgl":    (parse_bgl,    os.path.join(DATA_DIR, "bgl_logs.csv")),
        "linux":  (parse_linux,  os.path.join(DATA_DIR, "linux_logs.csv")),
    }
    targets = list(_parsers.keys()) if source == "all" else [source]
    records: list[dict] = []
    for key in targets:
        fn, path = _parsers[key]
        records.extend(fn(path))

    records.sort(key=lambda r: r["_ts"])
    for r in records:
        r.pop("_ts", None)
    return records


def get_available_sources() -> list[str]:
    """Return list of CSV sources that actually exist on disk."""
    available = []
    for src, fname in [("apache", "apache_logs.csv"), ("bgl", "bgl_logs.csv"), ("linux", "linux_logs.csv")]:
        if os.path.exists(os.path.join(DATA_DIR, fname)):
            available.append(src)
    return available
