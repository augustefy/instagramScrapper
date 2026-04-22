"""
Benchmark du délai aléatoire TikTok.

Cherche la valeur minimale de y (borne sup. du délai aléatoire) qui conserve
un taux de succès acceptable sur un environnement de test *autorisé*.

Usage (exemples) :
    python bench_tiktok_delay.py --phase wide --runs 3
    python bench_tiktok_delay.py --y-values 1.4 1.0 0.75 --runs 5
    python bench_tiktok_delay.py --phase validate --y 1.0 --runs 10

Critère de succès d'un run :
    - exit code 0
    - exactement --expect éléments extraits du JSON final (défaut: 10)

Sortie :
    - résumé lisible en fin d'exécution
    - export CSV et JSON (--output-dir)

IMPORTANT : environnement de test autorisé uniquement. Ce script ne cherche
pas à contourner une protection anti-bot — il mesure le comportement sous
différentes valeurs du délai humain déjà en place.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import statistics
import subprocess
import sys
import time
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path


PHASE_WIDE = [5.0, 4.0, 3.0, 2.5, 2.0, 1.5, 1.0, 0.75, 0.5, 0.25]
DEFAULT_URL = "https://www.tiktok.com/@gotaga"
DEFAULT_EXPECT = 10


@dataclass
class RunResult:
    y: float
    iteration: int
    success: bool
    posts_count: int
    duration_s: float
    exit_code: int
    failure_reason: str = ""


# ── Extraction du nombre de posts depuis la sortie CLI ─────────────────
_JSON_BLOCK_RE = re.compile(r"OUTPUT JSON.*?\n=+\n(.*?)\n=+", re.DOTALL)


def _count_posts_in_output(stdout: str) -> int:
    """Parse le bloc JSON imprimé par main.py et compte posts."""
    m = _JSON_BLOCK_RE.search(stdout)
    if not m:
        return 0
    try:
        payload = json.loads(m.group(1))
    except Exception:
        return 0
    posts = payload.get("posts")
    return len(posts) if isinstance(posts, list) else 0


def _failure_reason(exit_code: int, posts: int, expect: int, stderr: str) -> str:
    if exit_code != 0:
        tail = stderr.strip().splitlines()[-1] if stderr.strip() else ""
        return f"exit={exit_code} {tail[:120]}"
    if posts != expect:
        return f"posts={posts} (attendu {expect})"
    return ""


# ── Exécution d'un run unique ─────────────────────────────────────────
def run_once(
    y: float,
    iteration: int,
    url: str,
    n: int,
    expect: int,
    timeout: int,
    python_bin: str,
    extra_env: dict | None = None,
) -> RunResult:
    env = os.environ.copy()
    env["TIKTOK_DELAY_MAX"] = str(y)
    # Keep min < max; cap at 0 so [0, y] range is respected as user specified
    env["TIKTOK_DELAY_MIN"] = "0"
    if extra_env:
        env.update(extra_env)

    cmd = [python_bin, "main.py", url, str(n), "--debug"]
    start = time.monotonic()
    try:
        proc = subprocess.run(
            cmd,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        duration = time.monotonic() - start
        posts = _count_posts_in_output(proc.stdout)
        success = proc.returncode == 0 and posts == expect
        reason = _failure_reason(proc.returncode, posts, expect, proc.stderr)
        return RunResult(
            y=y,
            iteration=iteration,
            success=success,
            posts_count=posts,
            duration_s=round(duration, 2),
            exit_code=proc.returncode,
            failure_reason=reason,
        )
    except subprocess.TimeoutExpired:
        duration = time.monotonic() - start
        return RunResult(
            y=y,
            iteration=iteration,
            success=False,
            posts_count=0,
            duration_s=round(duration, 2),
            exit_code=-1,
            failure_reason=f"timeout>{timeout}s",
        )


# ── Agrégation par y ──────────────────────────────────────────────────
@dataclass
class YSummary:
    y: float
    runs: int
    successes: int
    success_rate: float
    avg_duration_s: float
    avg_posts: float
    failure_patterns: dict


def summarize(results: list[RunResult]) -> list[YSummary]:
    by_y: dict[float, list[RunResult]] = {}
    for r in results:
        by_y.setdefault(r.y, []).append(r)

    out = []
    for y, rs in sorted(by_y.items(), reverse=True):
        successes = sum(1 for r in rs if r.success)
        durations = [r.duration_s for r in rs]
        posts = [r.posts_count for r in rs]
        patterns: dict[str, int] = {}
        for r in rs:
            if r.failure_reason:
                patterns[r.failure_reason] = patterns.get(r.failure_reason, 0) + 1
        out.append(YSummary(
            y=y,
            runs=len(rs),
            successes=successes,
            success_rate=round(successes / len(rs), 3),
            avg_duration_s=round(statistics.mean(durations), 2),
            avg_posts=round(statistics.mean(posts), 2),
            failure_patterns=patterns,
        ))
    return out


def pick_minimum_stable_y(summaries: list[YSummary], threshold: float) -> float | None:
    """Plus petite valeur de y dont success_rate >= threshold."""
    acceptable = [s for s in summaries if s.success_rate >= threshold]
    if not acceptable:
        return None
    return min(s.y for s in acceptable)


# ── Affichage ─────────────────────────────────────────────────────────
def print_table(summaries: list[YSummary]) -> None:
    print()
    print(f"{'y':>6} | {'runs':>4} | {'ok':>3} | {'rate':>6} | {'avg_dur':>8} | {'avg_posts':>9} | patterns")
    print("-" * 90)
    for s in summaries:
        pat = ", ".join(f"{k} x{v}" for k, v in s.failure_patterns.items()) or "-"
        print(
            f"{s.y:>6.2f} | {s.runs:>4} | {s.successes:>3} | "
            f"{s.success_rate:>6.1%} | {s.avg_duration_s:>7.1f}s | "
            f"{s.avg_posts:>9.1f} | {pat}"
        )


# ── Export ────────────────────────────────────────────────────────────
def export_results(
    results: list[RunResult],
    summaries: list[YSummary],
    output_dir: Path,
    stamp: str,
) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / f"bench_runs_{stamp}.csv"
    json_path = output_dir / f"bench_summary_{stamp}.json"

    with csv_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["y", "iteration", "success", "posts_count",
                    "duration_s", "exit_code", "failure_reason"])
        for r in results:
            w.writerow([r.y, r.iteration, int(r.success), r.posts_count,
                        r.duration_s, r.exit_code, r.failure_reason])

    with json_path.open("w", encoding="utf-8") as f:
        json.dump({
            "timestamp": stamp,
            "summaries": [asdict(s) for s in summaries],
            "runs": [asdict(r) for r in results],
        }, f, indent=2, ensure_ascii=False)

    return csv_path, json_path


# ── CLI ───────────────────────────────────────────────────────────────
def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Benchmark du délai aléatoire TikTok.")
    p.add_argument("--phase", choices=["wide", "refine", "validate", "custom"],
                   default="custom",
                   help="wide=balayage large, refine=affinage local, validate=rejeu, custom=--y-values")
    p.add_argument("--y-values", nargs="+", type=float,
                   help="Liste explicite de valeurs de y à tester")
    p.add_argument("--y", type=float,
                   help="Valeur unique (utile avec --phase validate)")
    p.add_argument("--refine-center", type=float, default=1.0,
                   help="Centre du raffinage (phase refine). Défaut: 1.0")
    p.add_argument("--runs", type=int, default=3,
                   help="Nombre d'itérations par valeur de y")
    p.add_argument("--url", default=DEFAULT_URL)
    p.add_argument("--n", type=int, default=DEFAULT_EXPECT,
                   help="Nombre de posts demandés à main.py")
    p.add_argument("--expect", type=int, default=None,
                   help="Nombre de posts attendus pour considérer un run réussi (défaut=--n)")
    p.add_argument("--timeout", type=int, default=300,
                   help="Timeout par run (secondes)")
    p.add_argument("--python-bin", default=sys.executable)
    p.add_argument("--output-dir", type=Path, default=Path("bench_results"))
    p.add_argument("--threshold", type=float, default=0.9,
                   help="Seuil de success_rate pour valeur acceptable (défaut 0.9)")
    p.add_argument("--cooldown", type=float, default=2.0,
                   help="Pause entre runs (s)")
    return p.parse_args()


def resolve_y_values(args: argparse.Namespace) -> list[float]:
    if args.y_values:
        return list(args.y_values)
    if args.phase == "wide":
        return list(PHASE_WIDE)
    if args.phase == "refine":
        c = args.refine_center
        return sorted({round(max(0.05, c + d), 2)
                       for d in (-0.4, -0.25, -0.1, 0.0, 0.1, 0.25)},
                      reverse=True)
    if args.phase == "validate":
        if args.y is None:
            raise SystemExit("--phase validate nécessite --y <valeur>")
        return [args.y]
    raise SystemExit("Spécifie --y-values, --phase wide|refine|validate")


def main() -> int:
    args = parse_args()
    expect = args.expect if args.expect is not None else args.n
    y_values = resolve_y_values(args)

    print(f"Benchmark TikTok delay")
    print(f"  URL       : {args.url}")
    print(f"  n/expect  : {args.n} / {expect}")
    print(f"  runs      : {args.runs}")
    print(f"  y values  : {y_values}")
    print(f"  timeout   : {args.timeout}s")
    print(f"  threshold : {args.threshold:.0%}")
    print()

    results: list[RunResult] = []
    total = len(y_values) * args.runs
    done = 0
    t0 = time.monotonic()

    for y in y_values:
        for i in range(1, args.runs + 1):
            done += 1
            print(f"[{done}/{total}] y={y} iter={i} ...", end=" ", flush=True)
            r = run_once(
                y=y, iteration=i, url=args.url, n=args.n,
                expect=expect, timeout=args.timeout,
                python_bin=args.python_bin,
            )
            results.append(r)
            tag = "OK" if r.success else "KO"
            extra = f" {r.failure_reason}" if r.failure_reason else ""
            print(f"{tag} posts={r.posts_count} dur={r.duration_s}s{extra}")
            if args.cooldown > 0 and done < total:
                time.sleep(args.cooldown)

    summaries = summarize(results)
    print_table(summaries)

    best = pick_minimum_stable_y(summaries, args.threshold)
    print()
    if best is not None:
        print(f"=> y_min stable (rate >= {args.threshold:.0%}) : {best}")
    else:
        print(f"=> Aucun y >= seuil {args.threshold:.0%}.")

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path, json_path = export_results(results, summaries, args.output_dir, stamp)
    print(f"CSV : {csv_path}")
    print(f"JSON: {json_path}")
    print(f"Temps total: {time.monotonic() - t0:.0f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
