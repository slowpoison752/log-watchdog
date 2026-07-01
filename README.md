# Intelligent Observability & Event Watchdog

> A Python/FastAPI real-time log monitoring system with statistical anomaly detection,
> structured webhook alerting, and a live dark-theme dashboard — powered entirely by SQLite,
> zero cloud dependencies.

[![Python 3.11](https://img.shields.io/badge/python-3.11-blue)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-green)](https://fastapi.tiangolo.com/)
[![SQLite](https://img.shields.io/badge/database-SQLite-lightgrey)](https://sqlite.org/)
[![Docker](https://img.shields.io/badge/docker-ready-blue)](https://hub.docker.com/)

---

## Overview

The **Event Watchdog** ingests structured log CSV files from three real-world sources
([Apache](https://github.com/logpai/loghub/tree/master/Apache),
[BGL supercomputer](https://github.com/logpai/loghub/tree/master/BGL),
[Linux syslog](https://github.com/logpai/loghub/tree/master/Linux)),
normalises them into a unified schema, and applies three independent anomaly-detection
algorithms to identify error spikes. Detected anomalies trigger structured webhook payloads
(stored in SQLite and queryable via REST). A live WebSocket-powered dashboard renders all
metrics in real time.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        Single Process (FastAPI)                          │
│                         uvicorn / gunicorn                               │
│                                                                          │
│  HTTP GET                  WebSocket                                     │
│  /api/logs                 /api/stream                                   │
│  /api/analyze         ┌────────────────────────────────┐                │
│  /api/anomalies        │  Log Parser  (log_parser.py)   │                │
│  /api/webhooks         │  apache.csv → EventCreate      │                │
│  /api/metrics          │  bgl.csv    → EventCreate      │                │
│  /api/severity-dist.   │  linux.csv  → EventCreate      │                │
│  /api/source-breakdown └──────────────┬─────────────────┘                │
│  GET /  (dashboard)                   │                                  │
│                                       ▼                                  │
│                      ┌────────────────────────────────┐                  │
│                      │     SQLite  (watchdog.db)       │                 │
│                      │  logs | anomalies | webhook_    │                 │
│                      │        alerts                   │                 │
│                      └──────────────┬──────────────────┘                │
│                                     │                                    │
│              ┌──────────────────────▼───────────────────────┐            │
│              │        Anomaly Detector (anomaly_detector.py) │            │
│              │  Z-Score · IQR · Moving Average               │            │
│              └──────────────────────┬───────────────────────┘            │
│                                     │ anomaly flagged                    │
│              ┌──────────────────────▼───────────────────────┐            │
│              │      Webhook Handler (webhook_handler.py)     │            │
│              │  WH-<uuid> payload → SQLite + (opt.) SMTP     │            │
│              └──────────────────────────────────────────────┘            │
│                                                                           │
│  ┌─────────────────────────────────────────────────────────────────────┐ │
│  │  Dashboard  static/index.html  (Chart.js CDN + vanilla JS + WS)    │ │
│  │  Error Rate Chart · Severity Bar · Source Doughnut                  │ │
│  │  Live Log Stream table · Webhook Alert Log with expandable JSON     │ │
│  └─────────────────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────────────┘

External scripts (run alongside):
  synthetic_data_gen.py  →  generates fake events, inserts into SQLite
```

---

## File Structure

```
.
├── main.py                    # FastAPI app — all endpoints + WebSocket
├── log_parser.py              # CSV readers: Apache / BGL / Linux → unified schema
├── anomaly_detector.py        # Z-Score, IQR, Moving Average detection
├── webhook_handler.py         # Structured WH-<uuid> payload + SQLite logging
├── database.py                # SQLite init (WAL mode, auto-create tables)
├── synthetic_data_gen.py      # Fake log generator (CLI, inserts to DB or CSV)
│
├── data/
│   ├── apache_logs.csv        # columns: timestamp,severity,source,message
│   ├── bgl_logs.csv           # columns: timestamp,severity,source,component,node,message
│   └── linux_logs.csv         # columns: timestamp,severity,source,service,pid,message
│
├── static/
│   └── index.html             # Full single-page dashboard (Chart.js CDN)
│
├── Dockerfile                 # Multi-stage build, non-root user, stdlib health check
├── docker-compose.yml         # Production: named volume, bind-mount data/, log rotation
├── docker-compose.override.yml# Dev: full bind-mount + uvicorn --reload
├── .dockerignore
│
├── requirements.txt           # fastapi, uvicorn, gunicorn, websockets, …
├── .env.example               # All supported environment variables with safe defaults
├── .gitignore
├── prompts.md                 # AI session audit log (every prompt + ISO timestamp)
└── README.md
```

---

## Data Sources

| File | Source | Severities |
|------|--------|-----------|
| `data/apache_logs.csv` | [Apache loghub](https://github.com/logpai/loghub/tree/master/Apache) | `notice`, `error` |
| `data/bgl_logs.csv` | [BGL loghub](https://github.com/logpai/loghub/tree/master/BGL) | `FATAL`, `WARNING`, `INFO` |
| `data/linux_logs.csv` | [Linux loghub](https://github.com/logpai/loghub/tree/master/Linux) | `error`, `warn`, `info` |

Replace the sample CSVs with the full [loghub datasets](https://github.com/logpai/loghub) (2 000–10 000 rows each) for production-grade anomaly research.

---

## Setup & Run

### Option A — Local (Python venv)

```bash
# 1. Clone & enter the directory
git clone https://github.com/<you>/log-watchdog.git
cd log-watchdog

# 2. Create virtual environment
python3 -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure (optional — SMTP / webhook)
cp .env.example .env
# edit .env to add SMTP_* or WEBHOOK_URL if desired

# 5. Start  ← THE ONLY COMMAND after setup
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

Logs are **auto-ingested on startup** if the database is empty.

### Option B — Docker (production)

```bash
cp .env.example .env          # edit secrets
docker compose -f docker-compose.yml up -d --build
docker compose logs -f        # watch startup: "[startup] Auto-ingested …"
```

### Option C — Docker (development, hot-reload)

```bash
docker compose up --build     # override.yml auto-applied; code changes reload
```

Open **http://localhost:8000** — data and charts load automatically.

---

## API Reference

| Method | Endpoint | Query Params | Description |
|--------|----------|-------------|-------------|
| GET | `/health` | — | System status, DB counts, health label |
| GET | `/api/logs/ingest` | `source=all\|apache\|bgl\|linux` | Re-parse CSVs → reload logs table |
| GET | `/api/logs` | `source`, `limit`, `severity`, `search`, `offset` | Query ingested logs |
| GET | `/api/analyze` | `source`, `window` (min), `z_threshold`, `method` | Run anomaly detection, store results, fire webhooks |
| GET | `/api/anomalies` | `source` | List anomalies from last analysis run |
| GET | `/api/webhooks` | `limit` | List all fired webhook alert payloads |
| GET | `/api/metrics` | — | Summary stats + health status (`HEALTHY/DEGRADED/CRITICAL`) |
| GET | `/api/severity-distribution` | `source` | Count per severity label |
| GET | `/api/source-breakdown` | — | Per-source event counts + error rates |
| WS | `/api/stream` | `source` | WebSocket live log feed (300 ms/log) |
| GET | `/docs` | — | Auto-generated OpenAPI docs (Swagger UI) |

**Analysis `method` values:** `zscore` (default) · `iqr` · `moving_average`

---

## Anomaly Detection Methods

| Method | Algorithm |
|--------|-----------|
| **Z-Score** | Bucket logs into fixed time windows → compute per-bucket error counts → flag `(count − mean) / std > threshold`. Default threshold: 2.0 |
| **IQR** | Same bucketing → flag `error_count > Q3 + 1.5 × IQR` |
| **Moving Average** | Same bucketing → flag `error_count > rolling_mean(N_prev_windows) × sensitivity` |

Each result returns `{window_start, window_end, error_count, total_events, error_rate, z_score, method, is_anomaly}`.

---

## System Health Logic

| Status | Condition | Dashboard |
|--------|-----------|-----------|
| **HEALTHY** | No anomalies detected | Green pill |
| **DEGRADED** | Anomalies exist, max z-score ≤ 3 | Amber pill |
| **CRITICAL** | Any anomaly with z-score > 3 | Red pill + glow |

---

## How to Demo

1. **Start the server:**
   ```bash
   uvicorn main:app --reload --port 8000
   ```
   Dashboard auto-opens with 160 pre-loaded logs and runs analysis.

2. **Explore the dashboard** at http://localhost:8000:
   - Observe the **Error Rate Over Time** chart — red triangles mark anomaly windows
   - Check the **Severity Distribution** and **Source Breakdown** charts
   - Read the **Webhook Alert Log** (expandable JSON payloads)

3. **Switch detection methods:**
   - Change `Method` dropdown to `IQR` or `Moving Avg` → click **Run Analysis**
   - Adjust `Z-Score Threshold` (try 1.5 for more alerts, 3.0 for fewer)

4. **Simulate live data ingestion:**
   - Click **Simulate Live Feed** — watch all charts update in real time at 300 ms/log
   - Click **Stop** at any time

5. **Inject synthetic data** (second terminal):
   ```bash
   python synthetic_data_gen.py --rows 500 --source all
   # then click "Ingest Logs" on the dashboard
   ```

6. **Download CSV exports:**
   - Click **↓ Apache CSV**, **↓ BGL CSV**, **↓ Linux CSV**, or **↓ All Combined**

7. **Use the full loghub datasets:**
   - Download `Apache_2k.log_structured.csv`, `BGL_2k.log_structured.csv`, `Linux_2k.log_structured.csv`
   - Rename and reshape to match the column schemas in `data/`
   - Click **Ingest Logs** → **Run Analysis**

8. **Test the REST API directly:**
   ```bash
   curl http://localhost:8000/api/metrics | python3 -m json.tool
   curl "http://localhost:8000/api/analyze?source=linux&window=5&z_threshold=1.5&method=zscore"
   curl http://localhost:8000/api/webhooks
   ```

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DB_PATH` | `watchdog.db` | SQLite file path |
| `DATA_DIR` | `data` | Directory containing the 3 CSV files |
| `LOG_LEVEL` | `INFO` | uvicorn / gunicorn log level |
| `PORT` | `8000` | Server port |
| `WORKERS` | `1` | Gunicorn worker count (keep 1 for SQLite) |
| `WEBHOOK_URL` | _(empty)_ | Outbound webhook endpoint (e.g. Slack) |
| `SMTP_HOST` | _(empty)_ | SMTP server for email alerts |
| `SMTP_PORT` | `587` | SMTP port |
| `SMTP_USER` | _(empty)_ | SMTP username |
| `SMTP_PASSWORD` | _(empty)_ | SMTP password |
| `ALERT_EMAIL_TO` | _(empty)_ | Alert recipient email |

---

## Requirements

- **Python 3.9+** (3.11 recommended, used in Docker)
- No Docker, no cloud, no external database required for local run
- SQLite auto-created as `watchdog.db` on first startup
# log-watchdog
