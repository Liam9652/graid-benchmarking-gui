"""Eager fio-plot PNG renderer for baseline (PD) vs RAID (VD/MD) comparison.

Called from fio_parser.py:__main__ after collect_bench_fio_results.
Walks the bench-fio result tree, aggregates per-group JSONs into a single
synthetic JSON per (mode, qd, nj), invokes the fio-plot CLI with -C, and
writes PNGs to <results_root>/<NVME>-result/result/charts/ with the
_report_view filename suffix so collect_result_images picks them up.

Aggregation semantics mirror ComparisonDashboard.jsx SUM_METRICS:
  - SUM iops/bw across all jobs in all per-PD JSON files
  - AVG lat_ns.mean / clat_ns.mean (and stddev) across all jobs

fio-plot's bargraph -C mode renders one bar per input directory, so we
collapse N PD files into a single aggregated JSON in <staging>/PD/ to get
the desired one-PD-bar vs one-RAID-bar layout.
"""

import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
from copy import deepcopy
from pathlib import Path
from statistics import mean

logger = logging.getLogger(__name__)

DEVICE_NAME_RE = re.compile(r"^(nvme\d+n\d+|gdg\d+n\d+|md\d+|sd[a-z]+\d*)$")

SUM_LEAF_KEYS = {"iops", "bw", "bw_bytes", "io_bytes", "io_kbytes", "total_ios"}


def _is_device_dir(p: Path) -> bool:
    return p.is_dir() and bool(DEVICE_NAME_RE.match(p.name))


def _list_devices(group_root: Path) -> list[Path]:
    if not group_root.is_dir():
        return []
    return sorted(d for d in group_root.iterdir() if _is_device_dir(d))


def _list_blocksizes(device_dir: Path) -> list[str]:
    return sorted(d.name for d in device_dir.iterdir() if d.is_dir())


def _enumerate_combos(device_dir: Path, bs: str) -> set[tuple[str, str, str]]:
    """Return {(mode, iodepth, numjobs)} present under device_dir/<bs>."""
    combos: set[tuple[str, str, str]] = set()
    bs_dir = device_dir / bs
    if not bs_dir.is_dir():
        return combos
    for f in bs_dir.glob("*.json"):
        m = re.match(r"^([A-Za-z]+)-(\d+)-(\d+)\.json$", f.name)
        if m:
            combos.add((m.group(1), m.group(2), m.group(3)))
    return combos


def _merge_numeric(values: list, agg: str):
    nums = [v for v in values if isinstance(v, (int, float))]
    if not nums:
        return 0
    if agg == "sum":
        return sum(nums)
    return mean(nums)


def _merge_dict(dicts: list[dict], agg_for_key) -> dict:
    """Recursively merge a list of dicts. agg_for_key(path) -> 'sum' | 'mean'."""
    if not dicts:
        return {}
    out = deepcopy(dicts[0])

    def _walk(node, path):
        if isinstance(node, dict):
            for k in list(node.keys()):
                child_paths = [d.get(k) for d in dicts if isinstance(d, dict)]
                if isinstance(node[k], dict):
                    nested = [d for d in child_paths if isinstance(d, dict)]
                    if nested:
                        node[k] = _merge_dict(nested, agg_for_key)
                elif isinstance(node[k], (int, float)):
                    vals = [v for v in child_paths if isinstance(v, (int, float))]
                    node[k] = _merge_numeric(vals, agg_for_key(path + (k,)))
        return node

    return _walk(out, ())


def _agg_for_key(path: tuple) -> str:
    leaf = path[-1] if path else ""
    return "sum" if leaf in SUM_LEAF_KEYS else "mean"


def aggregate_jsons(json_paths: list[Path], dest: Path) -> Path | None:
    """Merge many bench-fio JSON files into a single synthetic JSON at dest.

    SUM iops/bw/io_bytes leaves; AVG everything else (latency, percentiles).
    Resulting JSON has a single job entry whose values represent the union
    of all per-job records across all source files. job options preserved
    from the first source so fio-plot's filter (rw/iodepth/numjobs) matches.
    """
    sources: list[dict] = []
    for jp in json_paths:
        try:
            with open(jp) as fh:
                sources.append(json.load(fh))
        except Exception as exc:
            logger.warning("aggregate_jsons: skip %s: %s", jp, exc)
    if not sources:
        return None

    # Flatten all per-job records across all source files
    all_jobs: list[dict] = []
    for src in sources:
        for job in src.get("jobs", []):
            all_jobs.append(job)
    if not all_jobs:
        return None

    merged_job = _merge_dict(all_jobs, _agg_for_key)

    out = deepcopy(sources[0])
    out["jobs"] = [merged_job]
    if "disk_util" in out:
        out["disk_util"] = []

    dest.parent.mkdir(parents=True, exist_ok=True)
    with open(dest, "w") as fh:
        json.dump(out, fh)
    return dest


def _safe_link(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists() or dst.is_symlink():
        dst.unlink()
    try:
        os.symlink(src.resolve(), dst)
    except OSError:
        shutil.copy2(src, dst)


def _stage_group(group_label: str, device_dirs: list[Path], bs: str,
                 combos: set[tuple[str, str, str]], staging_root: Path) -> Path:
    """Build <staging_root>/<group_label>/ containing one aggregated JSON
    per (mode, qd, nj) combo, named <mode>-<qd>-<nj>.json."""
    group_dir = staging_root / group_label
    group_dir.mkdir(parents=True, exist_ok=True)
    for mode, qd, nj in combos:
        sources = []
        for dev in device_dirs:
            jp = dev / bs / f"{mode}-{qd}-{nj}.json"
            if jp.is_file():
                sources.append(jp)
        if not sources:
            continue
        if len(sources) == 1:
            _safe_link(sources[0], group_dir / f"{mode}-{qd}-{nj}.json")
        else:
            aggregate_jsons(sources, group_dir / f"{mode}-{qd}-{nj}.json")
    return group_dir


def render_comparison_png(pd_staging: Path, raid_staging: Path,
                          mode: str, qd: str, nj: str,
                          title: str, out_png: Path) -> bool:
    """Run fio-plot -C and write PNG to out_png. Return True on success."""
    out_png.parent.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "MPLBACKEND": "Agg"}
    cmd = [
        "fio-plot",
        "-i", str(pd_staging), str(raid_staging),
        "-C",
        "-r", mode,
        "-d", str(qd),
        "-n", str(nj),
        "--xlabel-parent", "1",
        "-T", title,
        "-o", str(out_png),
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, check=False, env=env, timeout=60)
    except FileNotFoundError:
        logger.warning("fio-plot CLI not found in PATH; skipping PNG render")
        return False
    except subprocess.TimeoutExpired:
        logger.warning("fio-plot timed out for %s", out_png.name)
        return False

    if proc.returncode != 0 or not out_png.is_file():
        stderr = proc.stderr.decode(errors="replace")[:500] if proc.stderr else ""
        stdout = proc.stdout.decode(errors="replace")[:300] if proc.stdout else ""
        logger.warning("fio-plot failed for %s (rc=%s): %s | %s",
                       out_png.name, proc.returncode, stderr, stdout)
        return False
    return True


def _find_bench_fio_root(results_root: Path) -> Path | None:
    """Locate the <results_root>/<NVME-result>/<NVME>/ directory that holds
    the stage subdirs (afterdiscard, Normal, Rebuild, ...)."""
    if not results_root.is_dir():
        return None
    inner = results_root
    if (results_root / results_root.name.replace("-result", "")).is_dir():
        inner = results_root / results_root.name.replace("-result", "")
    else:
        for child in results_root.iterdir():
            if child.is_dir() and not child.name.startswith(("result", ".", "report_view")):
                inner = child
                break
    return inner


def _list_stages(inner_root: Path) -> list[str]:
    skip = {"result", "report_view", ".", "cmd", "iostat", "cpu_tmp", "gpu_tmp",
            "ssd_tmp", "raid_config"}
    return sorted(d.name for d in inner_root.iterdir()
                  if d.is_dir() and d.name not in skip)


def _list_statuses(stage_dir: Path) -> dict[str, dict[str, list[str]]]:
    """Return {status: {group: [device_names]}} where group ∈ {PD, VD, MD}."""
    out: dict[str, dict[str, list[str]]] = {}
    for group in ("PD", "VD", "MD"):
        gdir = stage_dir / group
        if not gdir.is_dir():
            continue
        for status_dir in gdir.iterdir():
            if not status_dir.is_dir():
                continue
            devs = [d.name for d in _list_devices(status_dir)]
            if devs:
                out.setdefault(status_dir.name, {})[group] = devs
    return out


def render_fioplot_comparisons(results_root: Path) -> int:
    """Walk results_root and render one PNG per (stage, status, bs, mode, qd, nj)
    cell, comparing PD baseline vs RAID (VD or MD).

    Output PNGs land in <results_root>/result/charts/ with filenames matching
    *_report_view.png so the existing collect_result_images picks them up.
    """
    inner = _find_bench_fio_root(results_root)
    if inner is None:
        logger.info("render_fioplot_comparisons: no inner result dir under %s", results_root)
        return 0

    chart_dir = results_root / "result" / "charts"
    chart_dir.mkdir(parents=True, exist_ok=True)

    n_rendered = 0
    with tempfile.TemporaryDirectory(prefix="fioplot_stg_") as tmp:
        staging_root = Path(tmp)
        for stage in _list_stages(inner):
            stage_dir = inner / stage
            statuses = _list_statuses(stage_dir)
            for status, groups in statuses.items():
                pd_devs = [stage_dir / "PD" / status / d for d in groups.get("PD", [])]
                raid_label = "VD" if "VD" in groups else ("MD" if "MD" in groups else None)
                if raid_label is None or not pd_devs:
                    continue
                raid_devs = [stage_dir / raid_label / status / d
                             for d in groups[raid_label]]

                bs_set: set[str] = set()
                for d in pd_devs + raid_devs:
                    bs_set.update(_list_blocksizes(d))

                for bs in sorted(bs_set):
                    pd_combos = set()
                    raid_combos = set()
                    for d in pd_devs:
                        pd_combos |= _enumerate_combos(d, bs)
                    for d in raid_devs:
                        raid_combos |= _enumerate_combos(d, bs)
                    combos = pd_combos & raid_combos
                    if not combos:
                        continue

                    cell_id = f"{stage}_{status}_{bs}"
                    cell_staging = staging_root / cell_id
                    pd_stg = _stage_group("PD", pd_devs, bs, combos, cell_staging)
                    raid_stg = _stage_group(raid_label, raid_devs, bs, combos, cell_staging)

                    for mode, qd, nj in sorted(combos):
                        png = chart_dir / (
                            f"fioplot_{stage}_{status}_{bs}_{mode}_qd{qd}nj{nj}"
                            f"_report_view.png"
                        )
                        title = (f"PD vs {raid_label} | {stage}/{status} | "
                                 f"{bs} {mode} qd={qd} nj={nj}")
                        if render_comparison_png(pd_stg, raid_stg, mode, qd, nj,
                                                 title, png):
                            n_rendered += 1
    return n_rendered


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    if len(sys.argv) < 2:
        print("Usage: fio_plot_renderer.py <results_root>")
        sys.exit(1)
    n = render_fioplot_comparisons(Path(sys.argv[1]))
    print(f"rendered {n} fio-plot comparison PNG(s)")
