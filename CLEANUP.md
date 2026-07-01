# Cleanup & Decommission Guide

## Cloud Resource Audit — Intelligent Observability & Event Watchdog

**Audit date:** 2026-07-01
**Auditor:** AI-directed scan (grep across all source files)

---

## Verdict

> **No cloud resources were provisioned; the application runs entirely locally on SQLite.
> Nothing to decommission.**

---

## Evidence

### Source-file scan results

| Cloud provider / service | SDK / identifier searched | Found in project source? |
|--------------------------|--------------------------|--------------------------|
| AWS (S3, Lambda, DynamoDB, RDS, CloudWatch, SQS, SNS) | `boto3`, `aws_access_key`, `aws_secret`, `S3Client`, `DynamoDB`, `CloudWatch` | **No** |
| Google Cloud / Firebase | `google-cloud`, `firebase_admin`, `GCP_PROJECT` | **No** |
| Microsoft Azure | `azure-`, `DefaultAzureCredential`, `AZURE_` | **No** |
| Supabase / Neon / PlanetScale | `SUPABASE_URL`, `DATABASE_URL=postgres`, `neon.tech` | **No** |
| Redis / Upstash | `REDIS_URL`, `upstash`, `redis.Redis(` | **No** |
| Celery / Kafka / Pub-Sub | `CELERY_BROKER`, `kafka-python`, `KafkaProducer` | **No** |
| Heroku / Fly.io / Render / Railway / Vercel / Netlify | deployment manifests, platform CLI configs | **No** |

> **Note:** `lambda` appears once in `main.py` — this is Python's built-in `lambda` keyword
> inside `run_in_executor(None, lambda: parse_all(source))`, **not** AWS Lambda.

---

## What the project DID create (local only)

| Artefact | Location | How to remove |
|----------|----------|---------------|
| SQLite database | `watchdog.db`, `watchdog.db-shm`, `watchdog.db-wal` | `rm watchdog.db watchdog.db-shm watchdog.db-wal` |
| Python virtual environment | `.venv/` | `rm -rf .venv` |
| Docker image (if built) | `event-watchdog:latest` (local daemon only) | `docker rmi event-watchdog:latest` |
| Docker named volume (if used) | `watchdog_db` (local daemon only) | `docker volume rm andela_vibe_coding_watchdog_db` |
| Docker container (if running) | `event-watchdog` (local only) | `docker compose down` |

---

## Full local teardown (optional)

```bash
# 1. Stop and remove containers + volumes
docker compose down -v

# 2. Remove the Docker image
docker rmi event-watchdog:latest

# 3. Remove the local database files
rm -f watchdog.db watchdog.db-shm watchdog.db-wal

# 4. Remove the Python virtual environment
rm -rf .venv

# 5. Remove the project directory entirely (point of no return)
cd ..
rm -rf Andela_vibe_coding/
```

---

## No further action required

This project made **zero outbound API calls** to any cloud provider during its build or runtime
(excluding optional CDN fetches for Chart.js in the browser, which are stateless and leave no
provisioned resources).

There are **no subscriptions, no pay-as-you-go meters, no IAM roles, no API keys, no databases,
and no compute instances** to decommission on any cloud platform.
