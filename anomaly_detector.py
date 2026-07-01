"""
Anomaly Detection Engine — three methods applied to time-bucketed log counts.

Each detected window returns:
{window_start, window_end, error_count, total_events, error_rate, z_score, method, is_anomaly}
"""
import math
from collections import defaultdict
from datetime import datetime, timedelta

# Severity labels treated as "error" for counting purposes
ERROR_SEVERITIES = {"error", "fatal", "warning", "warn"}


# ---------------------------------------------------------------------------
# Bucketing helpers
# ---------------------------------------------------------------------------

def _bucket_logs(logs: list[dict], window_minutes: int) -> dict[str, dict]:
    """
    Group logs into fixed-width time buckets.
    Returns an ordered dict keyed by bucket ISO start time.
    """
    window_sec = window_minutes * 60
    buckets: dict[str, dict] = {}

    for log in logs:
        try:
            ts = datetime.fromisoformat(log["timestamp"])
        except (ValueError, KeyError, TypeError):
            continue
        epoch = ts.timestamp()
        bucket_epoch = (epoch // window_sec) * window_sec
        bucket_start = datetime.fromtimestamp(bucket_epoch)
        bucket_end   = bucket_start + timedelta(minutes=window_minutes)
        key = bucket_start.isoformat()

        if key not in buckets:
            buckets[key] = {
                "window_start": bucket_start.isoformat(),
                "window_end":   bucket_end.isoformat(),
                "errors":       0,
                "total":        0,
            }
        buckets[key]["total"] += 1
        if log.get("severity", "").lower() in ERROR_SEVERITIES:
            buckets[key]["errors"] += 1

    return dict(sorted(buckets.items()))


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _std(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    m = _mean(values)
    variance = sum((x - m) ** 2 for x in values) / (len(values) - 1)
    return math.sqrt(variance)


def _percentile(sorted_values: list[float], p: float) -> float:
    """Linear interpolation percentile on a sorted list."""
    if not sorted_values:
        return 0.0
    n = len(sorted_values)
    idx = p / 100 * (n - 1)
    lo, hi = int(idx), min(int(idx) + 1, n - 1)
    return sorted_values[lo] + (idx - lo) * (sorted_values[hi] - sorted_values[lo])


def _make_result(b: dict, z: float, method: str, is_anomaly: bool) -> dict:
    ec = b["errors"]
    total = b["total"]
    rate = f"{ec / total * 100:.1f}%" if total > 0 else "0.0%"
    return {
        "window_start": b["window_start"],
        "window_end":   b["window_end"],
        "error_count":  ec,
        "total_events": total,
        "error_rate":   rate,
        "z_score":      round(z, 4),
        "method":       method,
        "is_anomaly":   is_anomaly,
    }


# ---------------------------------------------------------------------------
# Method A: Z-Score
# ---------------------------------------------------------------------------

def detect_zscore(
    logs: list[dict],
    window_minutes: int = 15,
    z_threshold: float = 2.0,
) -> list[dict]:
    """
    Bucket logs → compute per-bucket error counts → flag buckets where
    (error_count − mean) / std > z_threshold.
    """
    buckets = _bucket_logs(logs, window_minutes)
    if not buckets:
        return []

    counts = [b["errors"] for b in buckets.values()]
    mean   = _mean(counts)
    std    = _std(counts)

    results = []
    for b in buckets.values():
        ec = b["errors"]
        z  = (ec - mean) / std if std > 0 else 0.0
        results.append(_make_result(b, z, "z_score", z > z_threshold))
    return results


# ---------------------------------------------------------------------------
# Method B: IQR
# ---------------------------------------------------------------------------

def detect_iqr(
    logs: list[dict],
    window_minutes: int = 15,
) -> list[dict]:
    """
    Bucket logs → compute Q1, Q3, IQR → flag buckets where
    error_count > Q3 + 1.5 * IQR.
    """
    buckets = _bucket_logs(logs, window_minutes)
    if not buckets:
        return []

    counts = sorted(b["errors"] for b in buckets.values())
    q1     = _percentile(counts, 25)
    q3     = _percentile(counts, 75)
    iqr    = q3 - q1
    fence  = q3 + 1.5 * iqr

    results = []
    for b in buckets.values():
        ec = b["errors"]
        # Represent IQR distance as pseudo z_score for display consistency
        pseudo_z = (ec - q3) / iqr if iqr > 0 else 0.0
        results.append(_make_result(b, pseudo_z, "iqr", ec > fence))
    return results


# ---------------------------------------------------------------------------
# Method C: Moving Average
# ---------------------------------------------------------------------------

def detect_moving_average(
    logs: list[dict],
    window_minutes: int = 15,
    n_windows: int = 5,
    sensitivity: float = 1.5,
) -> list[dict]:
    """
    Bucket logs → compute rolling mean over previous N buckets → flag when
    current error_count > rolling_mean * sensitivity_multiplier.
    """
    buckets = _bucket_logs(logs, window_minutes)
    if not buckets:
        return []

    keys    = list(buckets.keys())
    results = []

    for i, key in enumerate(keys):
        b  = buckets[key]
        ec = b["errors"]

        # Rolling mean over the N buckets *before* this one
        prev_counts = [buckets[keys[j]]["errors"] for j in range(max(0, i - n_windows), i)]
        rolling_mean = _mean(prev_counts) if prev_counts else ec
        is_anomaly   = (ec > rolling_mean * sensitivity) if rolling_mean > 0 else False

        # Express ratio as pseudo z_score
        pseudo_z = ec / rolling_mean if rolling_mean > 0 else 0.0
        results.append(_make_result(b, pseudo_z, "moving_average", is_anomaly))

    return results


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

def detect_anomalies(
    logs: list[dict],
    window_minutes: int = 15,
    z_threshold: float = 2.0,
    method: str = "zscore",
) -> list[dict]:
    """
    Route to the chosen detection method.
    method: 'zscore' | 'iqr' | 'moving_average'
    """
    if method == "iqr":
        return detect_iqr(logs, window_minutes)
    if method == "moving_average":
        return detect_moving_average(logs, window_minutes)
    return detect_zscore(logs, window_minutes, z_threshold)
