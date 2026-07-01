# Intelligent Observability & Event Watchdog
### A Python/FastAPI AI-Directed SRE Tool

**Aditya Patil**
🔗 *The Connector* — AI Readiness Type · Tagle.ai
*"You bring people together to make AI work for everyone"*

> Built in a single session using AI-directed, human-in-the-loop development.
> Zero cloud dependencies · SQLite · FastAPI · Docker-ready

---

## The Problem

### Modern systems generate too many logs for humans to monitor manually

```
Apache HTTP Server   →  error.log          →  thousands of lines/hour
BGL Supercomputer    →  131,072 processors →  millions of kernel events
Linux syslog         →  SSH attacks, FTP   →  constant low-signal noise
```

**The challenge:**

- 🚨 **Alert fatigue** — ops teams drown in undifferentiated noise
- 🕳️ **Invisible spikes** — real error bursts buried in background chatter
- ⏱️ **Delayed response** — anomalies spotted too late, after impact
- 🧩 **Fragmented tooling** — parse here, detect there, alert somewhere else
- 💸 **Cost** — Datadog, Splunk, New Relic charge thousands per month

**What we built:** A single, self-contained Python service that ingests, detects, alerts, and visualises — with no paid cloud services.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                     Single Process  (FastAPI + gunicorn)                 │
│                                                                          │
│  HTTP (GET)               WebSocket /api/stream                          │
│  ┌─────────────────┐     ┌──────────────────────────────────────────┐   │
│  │  9 REST          │     │  Log Parser  (log_parser.py)             │   │
│  │  Endpoints       │     │  apache_logs.csv  → unified EventCreate  │   │
│  │  /api/logs       │     │  bgl_logs.csv     → unified EventCreate  │   │
│  │  /api/analyze    │     │  linux_logs.csv   → unified EventCreate  │   │
│  │  /api/anomalies  │     └──────────────┬───────────────────────────┘   │
│  │  /api/webhooks   │                    │                               │
│  │  /api/metrics    │     ┌──────────────▼───────────────────────────┐   │
│  └─────────────────┘     │     SQLite  watchdog.db  (WAL mode)       │   │
│                           │  logs · anomalies · webhook_alerts        │   │
│                           └──────────────┬───────────────────────────┘   │
│                                          │                               │
│                    ┌─────────────────────▼──────────────────────────┐    │
│                    │   Anomaly Detector  (anomaly_detector.py)       │    │
│                    │   Z-Score  ·  IQR  ·  Moving Average            │    │
│                    └─────────────────────┬──────────────────────────┘    │
│                                          │ anomaly flagged                │
│                    ┌─────────────────────▼──────────────────────────┐    │
│                    │   Webhook Handler  (webhook_handler.py)         │    │
│                    │   WH-<uuid> payload → SQLite + optional SMTP    │    │
│                    └────────────────────────────────────────────────┘    │
│                                                                           │
│   Dashboard  static/index.html  ·  Chart.js CDN  ·  WebSocket JS         │
└──────────────────────────────────────────────────────────────────────────┘

  Alongside:  synthetic_data_gen.py  →  injects fake anomaly bursts
```

**One command to start:** `uvicorn main:app --reload --port 8000`

---

## Key Features

### 1. Multi-Source Log Ingest
| Source | Format | Severities |
|--------|--------|-----------|
| Apache HTTP | `timestamp, severity, source, message` | `notice`, `error` |
| BGL Supercomputer | `timestamp, severity, source, component, node, message` | `FATAL`, `WARNING`, `INFO` |
| Linux syslog | `timestamp, severity, source, service, pid, message` | `error`, `warn`, `info` |

Auto-normalised → unified `{timestamp, severity, source, message, log_source}` schema.

---

### 2. Three Anomaly Detection Algorithms

| Method | Logic | Best for |
|--------|-------|---------|
| **Z-Score** *(primary)* | Flag windows where `(error_count − mean) / std > threshold` | Symmetric distributions, sustained baselines |
| **IQR** | Flag windows where `error_count > Q3 + 1.5 × IQR` | Skewed data, outlier-heavy sources |
| **Moving Average** | Flag when `count > rolling_mean(N) × sensitivity` | Trend-following, gradual drift |

- Configurable window (5 / 15 / 30 / 60 min)
- Configurable Z-threshold (default 2.0)
- Each result: `{window_start, window_end, error_count, error_rate, z_score, method, is_anomaly}`

---

### 3. Structured Webhook Alerting

Every anomaly fires a `WH-<uuid>` payload:

```json
{
  "id":           "WH-A3F9C21B",
  "event":        "anomaly_detected",
  "timestamp":    "2026-07-01T09:15:30Z",
  "source":       "linux",
  "window_start": "2026-07-01T06:00:00",
  "error_count":  19,
  "total_events": 20,
  "error_rate":   "95.0%",
  "z_score":      3.84,
  "severity":     "CRITICAL",
  "method":       "z_score",
  "action":       "PAGE_ON_CALL"
}
```

`CRITICAL` (z > 3) → `PAGE_ON_CALL` · `WARNING` (z ≤ 3) → `NOTIFY`

All payloads stored in SQLite and queryable via `GET /api/webhooks`.

---

### 4. Live Dashboard

- **Health pill** — `HEALTHY` / `DEGRADED` / `CRITICAL` in real time
- **4 metric cards** — Total Logs · Error Rate (with HIGH/NORMAL threshold label) · Anomalies · Webhooks
- **Error Rate Over Time** — filled red line (errors) + dashed blue line (total) + red triangle anomaly markers
- **Severity Distribution** — horizontal bar chart
- **Source Breakdown** — doughnut chart
- **Live Log Stream** — WebSocket feed, 300 ms/log, auto-scroll
- **Webhook Alert Log** — expandable JSON per alert, SPIKE / THRESHOLD badges

---

### 5. Production-Ready Docker Setup

```bash
docker compose -f docker-compose.yml up -d --build
```

- Multi-stage Dockerfile (builder → slim runtime, ~200 MB image)
- Non-root user `watchdog` — container breakout mitigation
- Named volume `watchdog_db` — SQLite survives restarts
- CSV data bind-mount — swap datasets without rebuilding
- Structured JSON log rotation (5 × 10 MB)
- `docker-compose.override.yml` for dev hot-reload

---

## Live Demo Flow

### Step-by-step walkthrough

**Step 1 — Start the server**
```bash
uvicorn main:app --reload --port 8000
# Output: [startup] Auto-ingested 160 log entries from data/
```
Open **http://localhost:8000** — charts render immediately, no clicks needed.

---

**Step 2 — Observe pre-loaded anomalies**
- Health pill shows **DEGRADED** or **CRITICAL**
- Error Rate chart shows red triangles on the anomaly windows:
  - Apache spike at `05:14–05:22` (mod_jk cascade failure)
  - BGL FATAL burst at `05:32–05:42` (kernel machine-check errors)
  - Linux SSH storm at `06:02–06:12` (brute-force authentication failures)

---

**Step 3 — Change detection method**
- Set `Method` → `IQR` → click **Run Analysis** → compare anomaly count
- Set `Z-Score Threshold` to `1.5` → more alerts flagged
- Set `Z-Score Threshold` to `3.5` → only the biggest spikes survive

---

**Step 4 — Simulate live data feed**
- Click **Simulate Live Feed** → all 160 logs stream at 300 ms each
- Watch the Error Rate chart grow window-by-window in real time
- Click **Stop** at any point

---

**Step 5 — Inject synthetic data**
```bash
# second terminal
python synthetic_data_gen.py --rows 500 --source all
```
Click **Ingest Logs** → **Run Analysis** → observe larger anomaly windows.

---

**Step 6 — Inspect webhook alerts**
- Expand a `SPIKE` badge in the Webhook Alert Log panel
- See the full `WH-<uuid>` JSON payload with `action: PAGE_ON_CALL`
- Or via API: `curl http://localhost:8000/api/webhooks | python3 -m json.tool`

---

**Step 7 — Download & share**
- Click **↓ All Combined** → downloads a merged CSV of all ingested logs
- Open **http://localhost:8000/docs** → explore the full OpenAPI UI

---

## Tech Stack & Why AI-Directed Development

### Stack

| Layer | Technology | Why |
|-------|-----------|-----|
| API | FastAPI 0.115 | Async, auto-docs, WebSocket native |
| Database | SQLite + WAL | Zero-config, zero cost, ACID compliant |
| Process manager | Gunicorn + uvicorn worker | Production lifecycle management |
| Frontend | Vanilla JS + Chart.js CDN | No build step, single HTML file |
| Live feed | WebSocket (native FastAPI) | True streaming, no polling |
| Detection | Pure Python (stdlib math) | No NumPy dependency, fully portable |
| Containers | Docker + Compose | Reproducible production deploys |

---

### Why AI-Directed / Human-in-the-Loop

This project was built in a **single session** using a Lead Architect model where:

```
Human (Aditya)               AI (Agent)
─────────────────            ──────────────────────────────
Defines requirements    →    Translates to architecture
Specifies data schemas  →    Writes complete implementation
Reviews screenshots     →    Diagnoses bugs, rewrites files
Approves each phase     →    Executes with zero manual edits
Asks for Docker         →    Delivers prod-grade multi-stage build
```

**Benefits demonstrated:**
- ⚡ **Speed** — Full MVP (13 files, ~1 800 lines) in under 3 hours
- 🎯 **Precision** — Exact file names, pinned versions, working code first try (except one diagnosed bug)
- 🔄 **Iteration** — Bug found in screenshot → root cause diagnosed → fix applied → verified in 2 minutes
- 📋 **Audit trail** — `prompts.md` logs every human decision with ISO timestamps

**Human-in-the-loop checkpoints:**
1. Architecture approval (ASCII diagram reviewed before any code)
2. Data schema confirmation (CSV column mapping verified)
3. Bug report via screenshot (human spotted empty dashboard)
4. Docker review (human triggered Docker build and watched logs)

> *"The Connector builds bridges between people and technology — this session was exactly that: human intent, AI execution, shared result."*
> — Tagle.ai Connector archetype, score: Relatedness 75 · Competence 72 · Innovation 69

---

## Future Improvements

### Near-term (next sprint)

| # | Feature | Value |
|---|---------|-------|
| 1 | **ML-based anomaly detection** | Replace Z-score with Isolation Forest or LSTM for non-stationary series |
| 2 | **Real-time webhook delivery** | Actually POST to Slack / PagerDuty; retry queue with exponential back-off |
| 3 | **Alert deduplication** | Suppress repeat alerts for the same anomaly window |
| 4 | **Rule engine** | User-defined threshold rules (e.g. "alert if error_rate > 60% for 10 min") |
| 5 | **Authentication** | JWT or API-key gating for all endpoints |

---

### Medium-term

| # | Feature | Value |
|---|---------|-------|
| 6 | **PostgreSQL backend** | Swap SQLite for Postgres for multi-worker horizontal scaling |
| 7 | **Log agent / tail mode** | Watch live log files via `inotify` instead of CSV batch ingest |
| 8 | **Grafana integration** | Expose `/metrics` in Prometheus format for rich Grafana dashboards |
| 9 | **Email digest** | Daily summary of anomalies and top error sources via SMTP |
| 10 | **Multi-tenant support** | Separate DB schemas per team/project |

---

### Longer-term vision

```
Current                          Future
───────────────────              ────────────────────────────────
3 CSV sources           →        Any log format (auto-detected)
Statistical detection   →        LLM-assisted root cause analysis
Manual demo             →        Continuous ingestion pipeline
Single server           →        Kubernetes with HPA autoscaling
SQLite                  →        TimescaleDB for time-series queries
```

> **The system already captures the hard part — a clean, typed event store 
> with a queryable API. Every improvement above is additive, not a rewrite.**

---

## Summary

| Metric | Value |
|--------|-------|
| Lines of code | ~1 800 (Python + HTML + YAML) |
| Files delivered | 22 |
| Build time | < 3 hours (AI-directed session) |
| External paid services | **0** |
| Cloud dependencies | **0** |
| Manual edits by human | **0** |
| Bugs fixed | 1 (empty dashboard — auto-ingest on startup) |
| Anomaly detection methods | 3 (Z-Score, IQR, Moving Average) |
| Docker image size | ~200 MB (multi-stage slim) |

---

*Built by Aditya Patil · The Connector (Tagle.ai) · July 2026*
*Repository: `github.com/<you>/log-watchdog`*
