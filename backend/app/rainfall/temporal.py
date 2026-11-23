"""MOSDAC native label inventory and relative-time allocation of derived depth."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from itertools import groupby
import math

from .contracts import RainfallRecord, utc_label

SOURCE = "mosdac_insat3dr"
ASSUMPTION = "mosdac_uniform_intensity_nominal_30min_v1"
CADENCE = 1800
STEP = 300
COUNT = CADENCE // STEP


def instant(label):
    return datetime.fromisoformat(utc_label(label))


def nominal_labels(first, last, cadence=CADENCE):
    start, end = instant(first), instant(last)
    step = timedelta(seconds=cadence)
    if cadence <= 0 or end < start or (end-start) % step:
        raise ValueError("nominal label bounds must align with the observation cadence")
    return [(start + i*step).isoformat().replace("+00:00", "Z")
            for i in range((end-start)//step + 1)]


def group_pixels(records: list[RainfallRecord]):
    """Index the normalized archive by UTC label and native raster row/column."""
    frames = defaultdict(dict)
    for record in records:
        if (record.source != SOURCE or record.measurement_type != "rainfall_rate"
                or record.cadence_seconds != CADENCE or not record.timestamp_utc
                or (record.geometry or {}).get("kind") != "grid_cell"):
            raise ValueError("expected a nominal half-hour MOSDAC rate with native pixel identity")
        key = (record.geometry["row"], record.geometry["column"])
        pixels = frames[record.timestamp_utc]
        if key in pixels:
            raise ValueError(f"duplicate source pixel {key} at {record.timestamp_utc}")
        pixels[key] = record
    return dict(sorted(frames.items(), key=lambda pair: instant(pair[0])))


def inventory(frames, first, last):
    """Recompute gaps from the expected label range, including missing edge slots."""
    expected = nominal_labels(first, last)
    observed = sorted(frames, key=instant)
    present, nominal = set(observed), set(expected)
    gaps, windows = [], []
    for available, labels in groupby(expected, key=present.__contains__):
        run = list(labels)
        if available:
            windows.append({"first_label_utc": run[0], "last_label_utc": run[-1], "count": len(run)})
        else:
            before = next((t for t in reversed(observed) if instant(t) < instant(run[0])), None)
            after = next((t for t in observed if instant(t) > instant(run[-1])), None)
            gaps.append({"status": "missing", "labels": run, "count": len(run),
                         "before_label_utc": before, "after_label_utc": after,
                         "surrounding_elapsed_seconds": (instant(after)-instant(before)).total_seconds()
                         if before and after else None})
    separations = [{"before": a, "after": b, "elapsed_seconds": (instant(b)-instant(a)).total_seconds()}
                   for a, b in zip(observed, observed[1:]) if instant(b)-instant(a) != timedelta(seconds=CADENCE)]
    return {"nominal_cadence_seconds": CADENCE, "first_nominal_label_utc": first, "last_nominal_label_utc": last,
            "nominal_count": len(expected), "present_count": len(present & nominal),
            "missing_count": len(nominal - present), "missing_runs": gaps,
            "longest_missing_run": max((r["count"] for r in gaps), default=0),
            "continuous_nominal_windows": windows, "off_grid_labels": sorted(present-nominal),
            "non_nominal_separations": separations}


def event_labels(frames, first, last, required_pixels):
    """Require complete nominal cadence and both expected native supports before allocation."""
    labels = nominal_labels(first, last)
    actual = [label for label in frames if instant(first) <= instant(label) <= instant(last)]
    if sorted(actual, key=instant) != labels:
        raise ValueError("event contains missing or irregular observation labels")
    for label in labels:
        pixels = frames[label]
        if not required_pixels or pixels.keys() != required_pixels or any(
                r.missing or r.derived_value is None for r in pixels.values()):
            raise ValueError(f"event contains missing source pixels at {label}")
    return labels


def step_depth(half_hour_depth):
    """Equal mm per 300 s, applied to a scalar or Float64 field. NaN stays NaN."""
    return half_hour_depth / COUNT


def native_allocation(record):
    """Check six unrounded allocations against the derived depth and original rate."""
    if record.missing:
        return {"status": "missing", "allocated_step_mm": None}
    if (record.derived_value is None or record.derived_unit != "mm" or record.original_unit != "mm/h"
            or record.measurement_type != "rainfall_rate" or record.source != SOURCE or not record.derivation):
        raise ValueError("expected separately derived MOSDAC depth in mm and native rate in mm/h")
    each = step_depth(record.derived_value)
    residual = abs(math.fsum([each]*COUNT) - record.derived_value)
    if residual > 1e-12 or not math.isclose(each, record.original_value*STEP/3600, rel_tol=1e-12, abs_tol=1e-12):
        raise ValueError("native depth or rate disagrees with the uniform allocation")
    return {"status": "dry" if record.derived_value == 0 else "wet", "allocated_step_mm": each,
            "depth_residual_mm": residual}


def relative_steps(labels):
    """Yield half-open relative intervals for a verified consecutive run of source labels."""
    if not labels or list(labels) != nominal_labels(labels[0], labels[-1]):
        raise ValueError("relative clock requires a consecutive sequence")
    for index, label in enumerate(labels):
        for part in range(COUNT):
            i = index*COUNT + part
            yield {"band": i+1, "source_interval_index": index, "timestamp_utc": label,
                   "relative_start_seconds": i*STEP, "relative_end_seconds": (i+1)*STEP}
