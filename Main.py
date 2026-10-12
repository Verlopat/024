#!/usr/bin/env python3
"""One-command, dependency-free SAW-DSU reproducibility pilot.

Default run creates output/testN with experiments E1-E6 and explicit evidence limits.
"""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
import logging
import math
import os
from pathlib import Path
import platform
import random
import shutil
import statistics
import subprocess
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone

from verify.check import linearizable
from verify.external import check_external
from verify.tso_litmus import report as tso_report

ROOT = Path(__file__).resolve().parent
METHODS = {"B1", "B2", "B3", "B4", "P1", "A1", "A2", "A3"}
WORKLOADS = {f"W{i}" for i in range(1, 9)}
LOG = logging.getLogger("saw-dsu")


def new_output() -> Path:
    base = ROOT / "output"
    base.mkdir(exist_ok=True)
    for i in range(1, 10000000):
        path = base / f"test{i}"
        try:
            path.mkdir()
            for sub in ["results/raw", "results/derived", "figures", "verify", "manifests", "configs"]:
                (path / sub).mkdir(parents=True, exist_ok=True)
            return path
        except FileExistsError:
            pass
    raise RuntimeError("output test directory limit reached")


def setup_logging(folder: Path) -> None:
    LOG.setLevel(logging.INFO)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    for handler in (logging.StreamHandler(), logging.FileHandler(folder / "run.log", encoding="utf-8")):
        handler.setFormatter(formatter)
        LOG.addHandler(handler)


def configuration(path: Path) -> dict:
    config = json.loads(path.read_text())
    n, ops, repeats = [int(config[k]) for k in ("elements", "operations_per_thread", "repetitions")]
    if not (2 <= n <= 1000000 and 1 <= ops <= 10000000 and 1 <= repeats <= 100):
        raise ValueError("invalid elements, operations_per_thread or repetitions")
    if not config["threads"] or any(not 1 <= int(p) <= 32 for p in config["threads"]):
        raise ValueError("invalid thread counts")
    if not set(config["methods"]).issubset(METHODS) or not set(config["workloads"]).issubset(WORKLOADS):
        raise ValueError("invalid method or workload name")
    if not config["seeds"]:
        raise ValueError("at least one seed is required")
    if any(not 0 <= float(p) <= 1 for p in config["pause_rate"]):
        raise ValueError("invalid pause rates")
    if any(not 0 <= int(p) <= 1000000 for p in config["pause_us"]):
        raise ValueError("invalid pause durations")
    return config


def manifest(folder: Path, conf: dict, config_path: Path) -> None:
    def run(*args):
        try:
            return subprocess.run(args, cwd=ROOT, check=False, capture_output=True, text=True, timeout=4).stdout.strip()
        except (OSError, subprocess.TimeoutExpired):
            return "unavailable"
    detail = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "system": platform.platform(), "python": sys.version, "machine": platform.machine(),
        "cpu": platform.processor(), "logical_cpus": os.cpu_count(),
        "compiler": run("g++", "--version").splitlines()[:1],
        "cmake": run("cmake", "--version").splitlines()[:1],
        "git_commit": run("git", "rev-parse", "HEAD"),
        "git_status": run("git", "status", "--porcelain")[:1000],
        "configuration_sha256": hashlib.sha256(config_path.read_bytes()).hexdigest(),
        "configuration": conf,
        "interpretation": "Native tests and benchmarks are not exhaustive weak-memory model checking",
    }
    write_json(folder / "manifests" / "environment.json", detail)


def write_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_csv(path: Path, data: list[dict]) -> None:
    if not data:
        path.write_text("", encoding="utf-8")
        return
    columns = list(dict.fromkeys(k for item in data for k in item))
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(data)


def build() -> Path:
    binpath = ROOT / "build" / "dsu_bench"
    if shutil.which("cmake"):
        subprocess.run(["cmake", "-S", str(ROOT), "-B", str(ROOT / "build"),
                        "-DCMAKE_BUILD_TYPE=RelWithDebInfo"], check=True, capture_output=True, text=True)
        subprocess.run(["cmake", "--build", str(ROOT / "build"), "-j", "2"], check=True)
        subprocess.run(["ctest", "--test-dir", str(ROOT / "build"), "--output-on-failure"], check=True)
    elif shutil.which("g++"):
        binpath.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["g++", "-O2", "-std=c++20", "-pthread", "-Wall", "-Wextra",
                        str(ROOT / "src" / "dsu.cpp"), "-o", str(binpath)], check=True)
    else:
        raise RuntimeError("install a C++20 compiler (g++) and optionally cmake")
    tests = subprocess.run([sys.executable,"-m","unittest","discover","-s","tests","-v"],
                           cwd=ROOT, capture_output=True, text=True, check=False)
    if tests.returncode:
        raise RuntimeError("Python unit tests failed: " + tests.stderr[-1200:])
    return binpath


def trial(binary: Path, *, method="P1", workload="W1", n=40, threads=2,
          ops=200, seed=42, pause_us=0, pause_rate=0., history=False,
          timeout=90) -> tuple[dict, list[dict]]:
    args = [str(binary), "--method", method, "--workload", workload,
            "--n", str(n), "--threads", str(threads), "--ops", str(ops),
            "--seed", str(seed), "--pause-us", str(pause_us),
            "--pause-rate", str(pause_rate), "--history", "1" if history else "0"]
    p = subprocess.run(args, cwd=ROOT, capture_output=True, text=True, timeout=timeout)
    if p.returncode:
        raise RuntimeError(f"native DSU failed ({p.returncode}): {p.stderr[:500]}")
    data = [json.loads(line) for line in p.stdout.splitlines() if line.strip()]
    summary = next(d for d in data if d["kind"] == "summary")
    summaries = [d for d in data if d["kind"] == "operation"]
    if not summary["valid"]:
        raise RuntimeError("DSU monotonic parent invariant failed")
    return summary, summaries


def experiment_e1_e2(binary: Path, folder: Path, conf: dict) -> list[dict]:
    rows = []
    for method in ["B2", "B3", "B4", "P1", "A1", "A2", "A3"]:
        if method not in conf["methods"]:
            continue
        # Native bounded trace observations, not systematic schedule enumeration.
        for seed in (42, 73, 91):
            result, events = trial(binary, method=method, workload="W6", n=5,
                                   threads=2, ops=3, seed=seed, history=True)
            check = linearizable(events, 5)
            row = {"experiment": "E1", "method": method, "memory_model": "native_x86",
                   "verification_type": "observed_history_only", "seed": seed,
                   "n": 5, "threads": 2, "ops_per_thread": 3, "status": check["status"],
                   "model_checked_executions": 0}
            rows.append(row)
            output = folder / "verify" / f"e1_{method}_{seed}.json"
            write_json(output, {"verdict": row, "linearizability": check,
                                "history": events, "summary": result})
    litmus = tso_report()
    write_json(folder / "verify" / "tso_store_buffering_litmus.json", litmus)
    for checker in check_external(ROOT, folder / "verify", timeout=30):
        rows.append({"experiment": "E2", "method": "P1", "memory_model": checker["checker"],
                     "verification_type": "external_checker_attempt", "status": checker["status"],
                     "model_checked_executions": 0})
        write_json(folder / "verify" / f"external_{checker['checker']}.json", checker)
    return rows


def collect(binary: Path, experiment: str, combos: list[tuple], conf: dict) -> list[dict]:
    rows = []
    for method, work, threads, repeat, pause_us, pause_rate in combos:
        seed = conf["seeds"][repeat % len(conf["seeds"])]
        try:
            value, _ = trial(binary, method=method, workload=work,
                             n=conf["elements"], threads=threads,
                             ops=conf["operations_per_thread"], seed=seed,
                             pause_us=pause_us, pause_rate=pause_rate)
            row = {"experiment": experiment, "method": method, "workload": work,
                   "threads": threads, "repeat": repeat, "seed": seed,
                   "pause_us": pause_us, "pause_rate": pause_rate,
                   "operations": value["operations"], "elapsed_ns": value["elapsed_ns"],
                   "throughput": value["throughput"],
                   "p50_ns": value["p50_ns"], "p95_ns": value["p95_ns"],
                   "p99_ns": value["p99_ns"],
                   "loads_per_op": value["loads"]/value["operations"],
                   "depth_per_op": value["depth"]/value["operations"],
                   "cas_per_op": value["cas"]/value["operations"],
                   "retries_per_op": value["retries"]/value["operations"],
                   "completion_ratio": 1.0, "status": "completed"}
        except (subprocess.TimeoutExpired, RuntimeError) as exc:
            row = {"experiment": experiment, "method": method, "workload": work,
                   "threads": threads, "repeat": repeat, "seed": seed,
                   "pause_us": pause_us, "pause_rate": pause_rate,
                   "completion_ratio": "", "status": "timeout" if isinstance(exc, subprocess.TimeoutExpired) else "error",
                   "error": str(exc)[:350]}
        rows.append(row)
    return rows


def experiment_combos(conf: dict) -> dict[str, list[tuple]]:
    # Paired workloads and seeds across methods; smoke is deliberately compact.
    methods = [m for m in ("B1", "B2", "B3", "B4", "P1", "A3") if m in conf["methods"]]
    works = [w for w in sorted(WORKLOADS) if w in conf["workloads"] and w != "W6"]
    reps = range(conf["repetitions"])
    threads = conf["threads"]
    e3 = [(m,w,t,r,0,0.) for w in works for t in threads for r in reps for m in methods]
    e4 = [(m,w,max(threads),r,u,rate)
          for w in ("W2", "W5") if w in conf["workloads"]
          for (u,rate) in ((0,0.),(max(conf["pause_us"]), max(conf["pause_rate"])))
          for r in reps for m in ("B2","B3","B4","P1") if m in conf["methods"]]
    e5 = [(m,w,t,r,0,0.) for w in ("W3", "W7") if w in conf["workloads"]
          for t in threads for r in reps for m in ("P1", "A3") if m in conf["methods"]]
    e6 = [(m,w,t,r,0,0.) for w in ("W1", "W2") if w in conf["workloads"]
          for t in threads for r in reps for m in ("B2","P1") if m in conf["methods"]]
    return {"E3":e3,"E4":e4,"E5":e5,"E6":e6}


def derive(rows: list[dict]) -> list[dict]:
    grouped = defaultdict(list)
    for row in rows:
        if row.get("status") == "completed":
            key = (row["experiment"],row["method"],row["workload"],row["threads"],
                   row["pause_us"],row["pause_rate"])
            grouped[key].append(row)
    metrics = ["throughput","p50_ns","p95_ns","p99_ns","loads_per_op",
               "depth_per_op","cas_per_op","retries_per_op","completion_ratio"]
    out = []
    for key, data in sorted(grouped.items()):
        summary = dict(zip(["experiment","method","workload","threads","pause_us","pause_rate"],key))
        summary["trials"] = len(data)
        for name in metrics:
            values = [float(d[name]) for d in data]
            summary[name + "_median"] = statistics.median(values)
            summary[name + "_mean"] = statistics.mean(values)
            summary[name + "_sd"] = statistics.stdev(values) if len(values)>1 else 0
            if name=="throughput":
                mean = statistics.mean(values)
                summary["throughput_cv"] = (statistics.stdev(values)/mean) if len(values)>1 and mean else 0
        out.append(summary)
    return out


def paired_bootstrap(rows: list[dict], first="P1", second="B2", samples=1000):
    index = defaultdict(dict)
    for row in rows:
        if row.get("status") != "completed":
            continue
        key = (row["experiment"],row["workload"],row["threads"],row["repeat"],row["pause_us"],row["pause_rate"])
        index[key][row["method"]] = row["throughput"]
    diffs = [d[first]-d[second] for d in index.values() if first in d and second in d]
    if not diffs:
        return {"pairs": 0, "median_difference": None, "ci95": None}
    rng = random.Random(20261012)
    boots = [statistics.median(rng.choices(diffs,k=len(diffs))) for _ in range(samples)]
    boots.sort()
    return {"pairs":len(diffs), "median_difference":statistics.median(diffs),
            "ci95": [boots[int(.025*(samples-1))],boots[int(.975*(samples-1))]],
            "interpretation": "exploratory pilot CI, not a preregistered full-power comparison"}


def figure_svg(path: Path, title: str, rows: list[dict], metric: str):
    selected = [r for r in rows if metric in r and isinstance(r.get(metric), (int,float))][:18]
    width, height = 920, max(220, 95 + 29 * len(selected))
    max_value = max((float(r[metric]) for r in selected), default=1) or 1
    def esc(s):
        return str(s).replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")
    svg = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
           '<rect width="100%" height="100%" fill="white"/>',
           f'<text x="22" y="34" font-size="19" font-family="sans-serif">{esc(title)}</text>']
    if not selected:
        svg.append('<text x="22" y="100" font-family="sans-serif">No completed trial available</text>')
    for i, row in enumerate(selected):
        y = 70 + 29*i
        label = f'{row.get("method", "")} {row.get("workload", "")} p={row.get("threads", "")}'
        v = float(row[metric]);scale = max(0, v / max_value)
        svg += [f'<text x="20" y="{y+11}" font-size="12" font-family="monospace">{esc(label)}</text>',
                f'<rect x="235" y="{y}" width="{600*scale:.1f}" height="16" fill="#4a6385"/>',
                f'<text x="{min(845,245+600*scale):.0f}" y="{y+12}" font-size="11" font-family="monospace">{v:.3g}</text>']
    svg.append('</svg>')
    path.write_text('\n'.join(svg), encoding='utf-8')


def verification_svg(path: Path, verification: list[dict]):
    """Categorical evidence plot; tool-unavailable is not mistaken for pass."""
    width, height = 880, 100 + 27 * len(verification)
    color = {"pass":"#357962", "fail":"#b04040",
             "not_run_tool_unavailable":"#999999", "timeout":"#bd873a"}
    svg = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{width}" height="{height}">',
           '<rect width="100%" height="100%" fill="white"/>',
           '<text x="20" y="33" font-family="sans-serif" font-size="19">F1 — bounded native history checks and external-tool status</text>',
           '<text x="20" y="52" font-family="sans-serif" font-size="12">Green is observed-history serializability, not exhaustive SC/TSO checking</text>']
    for i, r in enumerate(verification):
        y = 73 + i*27
        label = f'{r.get("experiment", "")} {r.get("method", "")} {r.get("memory_model", "")} seed={r.get("seed", "-")}'
        status = r.get("status", "unknown")
        svg += [f'<text x="20" y="{y+12}" font-family="monospace" font-size="12">{label}</text>',
                f'<rect x="540" y="{y}" width="20" height="16" fill="{color.get(status,"#bd873a")}"/>',
                f'<text x="570" y="{y+12}" font-family="monospace" font-size="12">{status}</text>']
    path.write_text('\n'.join(svg+["</svg>"]), encoding="utf8")


def main() -> int:
    parser = argparse.ArgumentParser(description="SAW-DSU end-to-end reproducibility runner")
    parser.add_argument("--config", default="configs/smoke.json")
    args = parser.parse_args()
    config_path = (ROOT / args.config).resolve()
    conf = configuration(config_path)
    folder = new_output()
    setup_logging(folder)
    (folder / "configs" / "run.json").write_bytes(config_path.read_bytes())
    manifest(folder, conf, config_path)
    LOG.info("Run folder: %s", folder)
    LOG.info("Building C++20 DSU")
    binary = build()
    LOG.info("Running bounded native histories, TSO litmus, external checker detection")
    verification = experiment_e1_e2(binary, folder, conf)
    write_csv(folder / "results" / "raw" / "e1_e2_verification.csv", verification)
    all_data = []
    for exp, combos in experiment_combos(conf).items():
        LOG.info("Running %s: %d trials",exp,len(combos))
        data = collect(binary,exp,combos,conf)
        all_data.extend(data)
        write_csv(folder / "results" / "raw" / f"{exp.lower()}.csv",data)
    summaries = derive(all_data)
    write_csv(folder / "results" / "derived" / "all_summary.csv",summaries)
    write_csv(folder / "results" / "derived" / "T1_model_assumptions.csv",[
        {"property":"scheduler stalls", "assumption":"arbitrary interleavings in theory; cooperative delay in native pilot"},
        {"property":"atomic primitive", "assumption":"single-word atomic CAS"},
        {"property":"memory semantics", "assumption":"C++20 acquire/acq_rel, x86 host; TSO litmus separate"},
        {"property":"progress target", "assumption":"lock-freedom target; not proved by this suite"},
        {"property":"version", "assumption":"32-bit bounded counter; wrap excluded for small trials"},
    ])
    write_csv(folder / "results" / "derived" / "T2_verification.csv",verification)
    for exp, name in [("E3","T3_performance"),("E3","T4_work"),
                      ("E4","T5_pause"),("E6","T6_stability")]:
        write_csv(folder / "results" / "derived" / (name+".csv"),
                  [r for r in summaries if r["experiment"] == exp])
    specs = [("F1_bounded_verification","Native observed-history outcomes", verification,"model_checked_executions"),
             ("F2_throughput","Throughput, E3",[r for r in summaries if r["experiment"]=="E3"],"throughput_median"),
             ("F3_latency","P99 latency, E3",[r for r in summaries if r["experiment"]=="E3"],"p99_ns_median"),
             ("F4_retries","CAS retries per operation, E4",[r for r in summaries if r["experiment"]=="E4"],"retries_per_op_median"),
             ("F5_path_splitting","Parent loads, E5",[r for r in summaries if r["experiment"]=="E5"],"loads_per_op_median"),
             ("F6_completion","Completion ratio, E4",[r for r in summaries if r["experiment"]=="E4"],"completion_ratio_median")]
    for filename, title, data, metric in specs:
        if filename.startswith("F1"):
            verification_svg(folder / "figures" / (filename + ".svg"), verification)
        else:
            figure_svg(folder / "figures" / (filename + ".svg"),title,data,metric)
    failed = [r for r in verification if r["status"] == "fail"]
    failures = [r for r in all_data if r.get("status") != "completed"]
    result = {"run_folder":str(folder),"config":str(config_path),
              "native_history_checks":len([r for r in verification if r["experiment"]=="E1"]),
              "native_history_failures":len(failed),"experimental_trials":len(all_data),
              "trial_failures":len(failures),
              "model_checking":"not asserted; see verify/external_*.json",
              "paired_throughput":paired_bootstrap(all_data),
              "warnings":["Native history checks are not exhaustive SC/TSO model checking.",
                          "Cooperative sleeps do not prove lock-freedom.",
                          "Versioned CAS superiority is an open hypothesis, not a demonstrated result."]}
    write_json(folder / "summary.json",result)
    LOG.info("Finished: %s; native failures=%d; trial failures=%d",folder,len(failed),len(failures))
    print(json.dumps(result,indent=2))
    return 1 if failed or failures else 0

if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError,RuntimeError,subprocess.CalledProcessError) as exc:
        LOG.exception("Experiment failed: %s",exc)
        raise SystemExit(1)
