"""File-backed provenance for the existing fixed-path simulation runners."""
from __future__ import annotations

import csv
import hashlib
import json
import os
import platform
import re
import subprocess
import traceback
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from importlib import metadata
from pathlib import Path


def utc():
    return datetime.now(timezone.utc).isoformat()


def checksum(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def git_state(root):
    def git(*args):
        try:
            return subprocess.check_output(["git", "--no-optional-locks", *args], cwd=root,
                                           stderr=subprocess.DEVNULL).decode().rstrip("\n")
        except (OSError, subprocess.CalledProcessError, UnicodeError):
            return None
    status = git("status", "--porcelain", "-z", "--untracked-files=all")
    source_status = git("status", "--porcelain", "--", "scripts", "config", "backend", "frontend", ".github")
    return {"commit_sha": git("rev-parse", "--verify", "HEAD"),
            "branch": git("symbolic-ref", "--short", "-q", "HEAD"),
            "working_tree_clean": None if status is None else not status,
            "uncommitted_source_changes": None if source_status is None else bool(source_status)}


def environment():
    versions = {"python": platform.python_version()}
    for name in ("numpy", "rasterio", "pyproj", "pyswmm", "swmm-toolkit"):
        try:
            versions[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            versions[name] = None
    try:
        from swmm.toolkit.solver import swmm_get_version
        versions["epa_swmm_engine_build"] = swmm_get_version()
    except (ImportError, OSError):
        versions["epa_swmm_engine_build"] = None
    return versions


def safe_config(value):
    if isinstance(value, dict):
        return {k: safe_config(v) for k, v in value.items()
                if not re.search(r"(secret|password|passwd|token|credential|api.?key|authorization|private.?key|connection.?string|dsn)", k, re.I)}
    if isinstance(value, list):
        return [safe_config(v) for v in value]
    if isinstance(value, str) and ("://" in value or re.search(
            r"\b(Bearer|Basic)\s+\S+|\b(password|secret|token|api.?key)\s*[:=]", value, re.I)):
        return "[redacted]"
    return value


def file_record(root, path):
    path = Path(path).resolve()
    name = path.name
    info = dict(name=name, path=os.path.relpath(path, root).replace(os.sep, "/"),
                format=path.suffix.lower().lstrip("."), size_bytes=None, sha256=None,
                spatial=None, temporal_coverage=None, units=None, provider=None, available=path.is_file())
    if not info["available"]:
        return info
    info.update(size_bytes=path.stat().st_size, sha256=checksum(path))
    if path.suffix == ".tif":
        import rasterio
        with rasterio.open(path) as src:
            tags = src.tags()
            info.update(spatial={"crs": str(src.crs) if src.crs else None,
                                 "bounds": list(src.bounds), "affine": list(src.transform)[:6],
                                 "shape": [src.height, src.width], "dtype": src.dtypes[0], "nodata": src.nodata},
                        units=tags.get("UNITS") or src.units[0],
                        provider=tags.get("SOURCE") or tags.get("SOURCE_DEM") or tags.get("SOURCE_FILE"),
                        temporal_coverage=[tags["TIMESTAMP"]]*2 if tags.get("TIMESTAMP") else None)
    elif path.suffix in (".json", ".geojson"):
        doc = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(doc, dict):
            info.update(units=doc.get("units"), provider=doc.get("source") or doc.get("processing_script"))
            crs = doc.get("crs")
            if crs or doc.get("bbox"):
                info["spatial"] = {"crs": crs, "bbox": doc.get("bbox")}
            records = doc.get("records") or doc.get("time_series") or []
            dates = [r["timestamp"] for r in records if isinstance(r, dict) and r.get("timestamp")]
            dates = dates or doc.get("timestamps", [])
            if dates:
                info["temporal_coverage"] = [min(dates), max(dates)]
            elif doc.get("simulation_start") and doc.get("simulation_end"):
                info["temporal_coverage"] = [doc["simulation_start"], doc["simulation_end"]]
            if doc.get("run_id"):
                info["source_run_id"] = doc["run_id"]
    elif path.suffix == ".inp":
        options = {}
        infiltration = {}
        section = ""
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            line = line.partition(";")[0].strip()
            if line.startswith("["):
                section = line.upper()
            elif line:
                parts = line.split()
                if section == "[OPTIONS]" and len(parts) > 1:
                    options[parts[0]] = " ".join(parts[1:])
                if section == "[INFILTRATION]" and len(parts) > 1:
                    parameters = " ".join(parts[1:])
                    infiltration[parameters] = infiltration.get(parameters, 0) + 1
        info["engine_options"] = options
        info["infiltration_rows_by_parameter_set"] = infiltration
        info["units"] = options.get("FLOW_UNITS")
        if all(options.get(k) for k in ("START_DATE", "START_TIME", "END_DATE", "END_TIME")):
            info["temporal_coverage"] = [options[k + "_DATE"] + " " + options[k + "_TIME"]
                                         for k in ("START", "END")]
    elif path.suffix == ".csv":
        with path.open(encoding="utf-8-sig", newline="") as stream:
            rows = csv.DictReader(stream)
            first = last = None
            providers = set()
            for row in rows:
                stamp = row.get("timestamp") or row.get("timestamp_utc")
                if stamp:
                    first, last = min(first or stamp, stamp), max(last or stamp, stamp)
                if row.get("source"):
                    providers.add(row["source"])
            if first:
                info["temporal_coverage"] = [first, last]
            if providers:
                info["provider"] = sorted(providers)
            if "rainfall_mm" in (rows.fieldnames or []):
                info["units"] = "mm"
    return info


def inventory(directories):
    snapshot = {}
    for directory in directories:
        for path in directory.rglob("*"):
            if path.is_file():
                stat = path.stat()
                snapshot[path] = (stat.st_mtime_ns, stat.st_ctime_ns, stat.st_size)
    return snapshot


@contextmanager
def product_lock(directory):
    # Fixed product names are shared by stages. Kernel locks release on process exit.
    with (directory / "products.lock").open("a+b") as handle:
        if os.name == "nt":
            import msvcrt
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield


def write_new(path, record):
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(safe_config(record), stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


@contextmanager
def simulation_run(root, stage, inputs, directories, configs=(), *, run_id=None):
    """Yield the runtime record. Failures propagate and retain their own manifest."""
    base = root / "data" / "runs"
    run_id = run_id or str(uuid.uuid4())
    folder = base / str(uuid.UUID(run_id))
    folder.mkdir(parents=True, exist_ok=False)
    record = dict(run_id=run_id, schema_version=1, stage=stage, created_utc=utc(), status="running",
                  simulation_start=None, simulation_end=None, error=None, inputs=[], outputs=[],
                  configuration={}, software=environment(), git=git_state(root), validations=[])
    write_new(folder / "started.json", record)
    try:
        with product_lock(base):
            directories = directories() if callable(directories) else directories
            before = inventory(directories)
            try:
                source_dir = root / "scripts" / "data"
                record["code_sha256"] = {p.relative_to(root).as_posix(): checksum(p)
                                         for p in sorted(source_dir.glob("*.py")) if not p.name.startswith("test_")}
                paths = inputs() if callable(inputs) else inputs
                for path in [*configs, *paths]:
                    item = file_record(root, path)
                    record["inputs"].append(item)
                    if not item["available"]:
                        raise FileNotFoundError(item["path"])
                    if path in configs:
                        record["configuration"][path.stem] = safe_config(json.loads(path.read_text(encoding="utf-8")))
                yield record
                failures = [v["name"] for v in record["validations"] if not v["passed"]]
                record["status"] = "validation_failed" if failures else "succeeded"
                if failures:
                    record["error"] = {"type": "ValidationFailure", "checks": failures}
            finally:
                for path, stamp in sorted(inventory(directories).items()):
                    if before.get(path) != stamp:
                        record["outputs"].append(dict(path=path.relative_to(root).as_posix(),
                            format=path.suffix.lstrip("."), size_bytes=path.stat().st_size,
                            sha256=checksum(path), output_type=path.stem, run_id=run_id))
    except BaseException as exc:
        # Exceptions from drivers can contain a URL, credentials or raw input.
        frame = traceback.extract_tb(exc.__traceback__)[-1]
        record.update(status="failed", error={"type": type(exc).__name__, "stage": stage,
                                              "function": frame.name, "line": frame.lineno})
        raise
    finally:
        record["finished_utc"] = utc()
        write_new(folder / "manifest.json", record)


def record_period(record, timestamps, last_interval_seconds):
    if timestamps:
        start = datetime.fromisoformat(timestamps[0].replace("Z", "+00:00"))
        end = datetime.fromisoformat(timestamps[-1].replace("Z", "+00:00")) + timedelta(seconds=last_interval_seconds)
        record.update(simulation_start=start.isoformat(), simulation_end=end.isoformat())
        record["configuration"]["duration_seconds"] = (end - start).total_seconds()


def validation_results(record, values, prefix=""):
    for key, value in values.items():
        name = prefix + key
        if isinstance(value, bool):
            record["validations"].append(dict(name=name, passed=value, measured=value,
                                              failure_reason=None if value else "Predicate evaluated to false"))
        elif isinstance(value, dict):
            validation_results(record, value, name + ".")
