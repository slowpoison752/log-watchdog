"""
Synthetic Data Generator — creates realistic log CSV rows and inserts them
into the SQLite database, or optionally appends to CSV files.

Usage:
  python synthetic_data_gen.py --rows 200 --source apache
  python synthetic_data_gen.py --rows 500 --source all --to-csv
"""
import argparse
import csv
import os
import random
import sqlite3
from datetime import datetime, timedelta

DB_PATH   = os.getenv("DB_PATH", "watchdog.db")
DATA_DIR  = os.getenv("DATA_DIR", "data")

# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------

APACHE_TEMPLATES = [
    ("notice", "::1",       "jk2_init() Can't connect to Apache: 13 (Permission denied)"),
    ("notice", "localhost",  "workerEnv in error state 3"),
    ("error",  "::1",       "mod_jk child workerEnv in error state 6"),
    ("error",  "127.0.0.1", "File does not exist: /var/www/html/favicon.ico"),
    ("error",  "::1",       "mod_jk child init 1 -2"),
    ("notice", "localhost",  "Apache/2.0.52 configured — resuming normal operations"),
    ("error",  "10.0.0.1",  "Directory index forbidden by rule: /var/www/html/"),
    ("error",  "192.168.1.5","client denied by server configuration: /etc/httpd/htdocs"),
    ("notice", "::1",       "jk2_init() Found child 1234 in error state"),
    ("error",  "127.0.0.1", "Premature end of script headers: cgi-bin/test.pl"),
]

BGL_TEMPLATES = [
    ("INFO",    "R00-M0-N0", "KERNEL",  "R00-M0-N0-C:J00-U01", "instruction cache parity error corrected"),
    ("INFO",    "R01-M0-N4", "KERNEL",  "R01-M0-N4-C:J05-U11", "data cache parity error corrected"),
    ("FATAL",   "R02-M1-N0", "KERNEL",  "R02-M1-N0-C:J12-U11", "program interrupt"),
    ("FATAL",   "R03-M0-N2", "KERNEL",  "R03-M0-N2-C:J08-U07", "machine check: store operation"),
    ("FATAL",   "R04-M1-N3", "KERNEL",  "R04-M1-N3-C:J14-U09", "floating point unavailable"),
    ("WARNING", "R05-M0-N1", "APPREAD", "R05-M0-N1-C:J02-U03", "ciod: failed to read message prefix"),
    ("FATAL",   "R06-M1-N5", "APP",     "R06-M1-N5-C:J10-U05", "ciod: Error reading message from CIU"),
    ("INFO",    "R07-M0-N7", "KERNEL",  "R07-M0-N7-C:J01-U02", "corrected parity error — ECC recovered"),
    ("WARNING", "R08-M1-N2", "DISC",    "R08-M1-N2-C:J06-U08", "DISCOVERY: node variance threshold exceeded"),
    ("FATAL",   "R09-M0-N6", "KERNEL",  "R09-M0-N6-C:J03-U04", "machine check interrupt: machine check exception"),
]

LINUX_TEMPLATES = [
    ("error", "combo", "sshd",     "19937", "authentication failure; logname= uid=0 euid=0 rhost=220.135.151.1 user=root"),
    ("error", "combo", "sshd",     "19938", "Invalid user admin from 218.188.2.4"),
    ("error", "combo", "sshd",     "19939", "Failed password for illegal user test from 61.177.172.25 port 51813 ssh2"),
    ("info",  "combo", "sshd",     "19940", "Accepted password for root from 192.168.1.10 port 45983 ssh2"),
    ("info",  "combo", "PAM",      "19941", "pam_unix(sshd:session): session opened for user root"),
    ("info",  "combo", "PAM",      "19942", "pam_unix(sshd:session): session closed for user root"),
    ("warn",  "combo", "vsftpd",   "20001", "refused connect from 219.150.161.20 (219.150.161.20)"),
    ("error", "combo", "vsftpd",   "20002", "FAIL LOGIN: Client \"218.188.2.4\""),
    ("warn",  "combo", "xinetd",   "20100", "SENSOR - denial of service from 61.177.172.25"),
    ("error", "combo", "logrotate","20200", "error: failed to open config file /etc/logrotate.d/apache: No such file or directory"),
    ("warn",  "combo", "named",    "20300", "notify from 192.168.1.1#53: zone transfer refused"),
    ("info",  "combo", "cron",     "20400", "CRON pam_unix(crond:session): session opened for user root"),
]


# ---------------------------------------------------------------------------
# Generators with anomaly bursts
# ---------------------------------------------------------------------------

def _gen_apache(n: int, base_dt: datetime) -> list[dict]:
    rows = []
    for i in range(n):
        # Inject an anomaly burst at 30-40% of the way through
        if int(n * 0.30) <= i <= int(n * 0.40):
            sev, src, msg = "error", "::1", f"mod_jk child workerEnv in error state {random.randint(1,9)}"
        else:
            sev, src, msg = random.choice(APACHE_TEMPLATES)
        ts = base_dt + timedelta(minutes=i * 2, seconds=random.randint(0, 119))
        rows.append({
            "timestamp": ts.strftime("%Y-%m-%d %H:%M:%S"),
            "severity":  sev,
            "source":    src,
            "message":   msg,
        })
    return rows


def _gen_bgl(n: int, base_dt: datetime) -> list[dict]:
    rows = []
    for i in range(n):
        # FATAL burst at 50-65%
        if int(n * 0.50) <= i <= int(n * 0.65):
            tpl = random.choice([t for t in BGL_TEMPLATES if t[0] == "FATAL"])
        else:
            tpl = random.choice(BGL_TEMPLATES)
        sev, node, comp, src, msg = tpl
        ts = base_dt + timedelta(minutes=i * 3, seconds=random.randint(0, 179))
        rows.append({
            "timestamp": ts.strftime("%Y-%m-%d %H:%M:%S"),
            "severity":  sev,
            "source":    src,
            "component": comp,
            "node":      node,
            "message":   msg,
        })
    return rows


def _gen_linux(n: int, base_dt: datetime) -> list[dict]:
    rows = []
    for i in range(n):
        # Auth failure storm at 60-75%
        if int(n * 0.60) <= i <= int(n * 0.75):
            tpl = random.choice([t for t in LINUX_TEMPLATES if "authentication" in t[4] or "Invalid user" in t[4] or "Failed password" in t[4]])
        else:
            tpl = random.choice(LINUX_TEMPLATES)
        sev, host, svc, pid, msg = tpl
        ts = base_dt + timedelta(minutes=i * 2, seconds=random.randint(0, 119))
        rows.append({
            "timestamp": ts.strftime("%Y-%m-%d %H:%M:%S"),
            "severity":  sev,
            "source":    host,
            "service":   svc,
            "pid":       str(int(pid) + random.randint(0, 9)),
            "message":   msg,
        })
    return rows


# ---------------------------------------------------------------------------
# Write helpers
# ---------------------------------------------------------------------------

def write_to_csv(rows: list[dict], filepath: str, fieldnames: list[str]) -> None:
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    print(f"  Wrote {len(rows)} rows → {filepath}")


def insert_to_db(rows: list[dict], log_source: str) -> None:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        conn.executemany(
            "INSERT INTO logs (timestamp, severity, source, message, log_source) VALUES (?,?,?,?,?)",
            [(r.get("timestamp",""), r.get("severity",""), r.get("source",""),
              r.get("message",""),   log_source) for r in rows],
        )
        conn.commit()
        print(f"  Inserted {len(rows)} rows (source={log_source}) → {DB_PATH}")
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Synthetic log data generator")
    parser.add_argument("--rows",   type=int, default=200,   help="Rows per source (default 200)")
    parser.add_argument("--source", type=str, default="all", help="all | apache | bgl | linux")
    parser.add_argument("--to-csv", action="store_true",     help="Write CSVs instead of inserting into DB")
    args = parser.parse_args()

    base_apache = datetime(2005, 12, 4, 0, 0, 0)
    base_bgl    = datetime(2005, 6,  3, 0, 0, 0)
    base_linux  = datetime(2005, 6,  9, 0, 0, 0)

    targets = ["apache", "bgl", "linux"] if args.source == "all" else [args.source]

    for src in targets:
        print(f"Generating {args.rows} rows for source={src} ...")
        if src == "apache":
            rows = _gen_apache(args.rows, base_apache)
            if args.to_csv:
                write_to_csv(rows, os.path.join(DATA_DIR, "apache_logs.csv"),
                             ["timestamp", "severity", "source", "message"])
            else:
                insert_to_db(rows, "apache")

        elif src == "bgl":
            rows = _gen_bgl(args.rows, base_bgl)
            if args.to_csv:
                write_to_csv(rows, os.path.join(DATA_DIR, "bgl_logs.csv"),
                             ["timestamp", "severity", "source", "component", "node", "message"])
            else:
                insert_to_db(rows, "bgl")

        elif src == "linux":
            rows = _gen_linux(args.rows, base_linux)
            if args.to_csv:
                write_to_csv(rows, os.path.join(DATA_DIR, "linux_logs.csv"),
                             ["timestamp", "severity", "source", "service", "pid", "message"])
            else:
                insert_to_db(rows, "linux")

    print("Done.")


if __name__ == "__main__":
    main()
