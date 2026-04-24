"""
Benchmark multi-services.

Mesure la latence et le taux de reussite de chaque voie de collecte
supportee par le projet :

    || Api       || Facebook  ||
    || Api       || Instagram ||
    || Scraper   || Instagram ||
    || Api       || Reddit    ||
    || Scraper   || Tiktok    ||
    || Guest_api || Twitter   ||

Pour chaque service on execute --runs iterations et on mesure :
    - duree totale (perf_counter)
    - nombre de posts retournes
    - succes (posts_count >= --expect et pas d'exception)

Usage :
    python bench_services.py
    python bench_services.py --runs 3 --limit 5
    python bench_services.py --only instagram_api,reddit_api
    python bench_services.py --skip tiktok_scraper
    python bench_services.py --ig-username cristiano --tt-username gotaga

Les runners et la liste de services sont partages avec `app/services/bench.py`,
qui alimente egalement `python main.py --health [N]`.

IMPORTANT : environnement de test autorise uniquement. Ce script ne cherche
pas a contourner une protection anti-bot : il mesure la performance des
voies de collecte deja en place.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import statistics
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

# Autoriser l execution directe depuis la racine du depot.
_REPO_ROOT = Path(__file__).resolve().parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from app.services.bench import (  # noqa: E402
    DEFAULT_BENCH_LIMIT,
    DEFAULT_USERNAMES,
    SERVICE_SPECS,
    ServiceBenchResult,
    ServiceContext,
    ServiceSpec,
    resolve_specs,
    run_service,
)


DEFAULT_RUNS = 1
DEFAULT_COOLDOWN = 2.0


# ── Mesure unitaire d un run (tracee pour l export). ──────────────────
@dataclass
class RunRecord:
    service: str
    source_label: str
    platform_label: str
    iteration: int
    success: bool
    posts_count: int
    duration_s: float
    source_returned: str = ""
    failure_reason: str = ""

    @classmethod
    def from_bench_result(
        cls, result: ServiceBenchResult, iteration: int
    ) -> "RunRecord":
        return cls(
            service=result.key,
            source_label=result.source_label,
            platform_label=result.platform_label,
            iteration=iteration,
            success=result.ok,
            posts_count=result.posts_count,
            duration_s=result.duration_s,
            source_returned=result.returned_source,
            failure_reason=result.message,
        )


# ── Agregation par service. ───────────────────────────────────────────
@dataclass
class ServiceSummary:
    service: str
    source_label: str
    platform_label: str
    runs: int
    successes: int
    success_rate: float
    avg_duration_s: float
    min_duration_s: float
    max_duration_s: float
    avg_posts: float
    failure_patterns: dict = field(default_factory=dict)


def summarize(records: list[RunRecord]) -> list[ServiceSummary]:
    by_service: dict[str, list[RunRecord]] = {}
    for r in records:
        by_service.setdefault(r.service, []).append(r)

    summaries: list[ServiceSummary] = []
    for spec in SERVICE_SPECS:
        rs = by_service.get(spec.key)
        if not rs:
            continue
        successes = sum(1 for r in rs if r.success)
        durations = [r.duration_s for r in rs]
        posts = [r.posts_count for r in rs]
        patterns: dict[str, int] = {}
        for r in rs:
            if r.failure_reason:
                patterns[r.failure_reason] = patterns.get(r.failure_reason, 0) + 1
        summaries.append(
            ServiceSummary(
                service=spec.key,
                source_label=spec.source_label,
                platform_label=spec.platform_label,
                runs=len(rs),
                successes=successes,
                success_rate=round(successes / len(rs), 3),
                avg_duration_s=round(statistics.mean(durations), 2),
                min_duration_s=round(min(durations), 2),
                max_duration_s=round(max(durations), 2),
                avg_posts=round(statistics.mean(posts), 2),
                failure_patterns=patterns,
            )
        )
    return summaries


# ── Rendu en tableau compact facile a comparer. ───────────────────────
def print_summary_table(summaries: list[ServiceSummary]) -> None:
    print()
    header = (
        f"{'service':<20} | {'src':<9} | {'plat':<10} | "
        f"{'runs':>4} | {'ok':>3} | {'rate':>6} | "
        f"{'avg':>7} | {'min':>7} | {'max':>7} | {'posts':>5}"
    )
    print(header)
    print("-" * len(header))
    for s in summaries:
        print(
            f"{s.service:<20} | {s.source_label:<9} | {s.platform_label:<10} | "
            f"{s.runs:>4} | {s.successes:>3} | {s.success_rate:>6.1%} | "
            f"{s.avg_duration_s:>6.2f}s | {s.min_duration_s:>6.2f}s | "
            f"{s.max_duration_s:>6.2f}s | {s.avg_posts:>5.1f}"
        )

    # Patterns d echec regroupes en fin de table pour diagnostic.
    has_patterns = any(s.failure_patterns for s in summaries)
    if has_patterns:
        print()
        print("Echecs :")
        for s in summaries:
            if not s.failure_patterns:
                continue
            for reason, count in s.failure_patterns.items():
                print(f"  - {s.service:<20} x{count} : {reason}")


# ── Rendu dans le style de la synthese health-check. ──────────────────
def print_synthesis(summaries: list[ServiceSummary]) -> None:
    print()
    print("Synthese :")
    for s in summaries:
        status = "OK" if s.success_rate >= 0.5 else "KO"
        print(
            f"|| {status} || {s.source_label:<9} || {s.platform_label:<10} "
            f"|| avg={s.avg_duration_s:>6.2f}s "
            f"|| rate={s.success_rate:>5.1%} "
            f"|| posts={s.avg_posts:>4.1f} ||"
        )


# ── Export CSV + JSON pour analyse offline. ───────────────────────────
def export_results(
    records: list[RunRecord],
    summaries: list[ServiceSummary],
    output_dir: Path,
    stamp: str,
    context_header: dict,
) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / f"bench_services_runs_{stamp}.csv"
    json_path = output_dir / f"bench_services_summary_{stamp}.json"

    with csv_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "service",
                "source_label",
                "platform_label",
                "iteration",
                "success",
                "posts_count",
                "duration_s",
                "source_returned",
                "failure_reason",
            ]
        )
        for r in records:
            w.writerow(
                [
                    r.service,
                    r.source_label,
                    r.platform_label,
                    r.iteration,
                    int(r.success),
                    r.posts_count,
                    r.duration_s,
                    r.source_returned,
                    r.failure_reason,
                ]
            )

    with json_path.open("w", encoding="utf-8") as f:
        json.dump(
            {
                "timestamp": stamp,
                "context": context_header,
                "summaries": [asdict(s) for s in summaries],
                "runs": [asdict(r) for r in records],
            },
            f,
            indent=2,
            ensure_ascii=False,
        )

    return csv_path, json_path


# ── Resolution des overrides de username. ─────────────────────────────
def resolve_username(spec: ServiceSpec, overrides: dict[str, str]) -> str:
    # Priorite : override explicite > defaut plateforme.
    return overrides.get(spec.platform) or DEFAULT_USERNAMES.get(
        spec.platform, spec.platform
    )


# ── CLI. ──────────────────────────────────────────────────────────────
def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Benchmark multi-services de collecte.")
    p.add_argument(
        "--runs",
        type=int,
        default=DEFAULT_RUNS,
        help=f"Iterations par service (defaut {DEFAULT_RUNS})",
    )
    p.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_BENCH_LIMIT,
        help=f"Nombre de posts demandes par appel (defaut {DEFAULT_BENCH_LIMIT})",
    )
    p.add_argument(
        "--expect",
        type=int,
        default=None,
        help="Nombre minimum de posts pour considerer un run reussi "
             "(defaut = --limit)",
    )
    p.add_argument("--only", help="Liste separee par des virgules de cles a executer")
    p.add_argument("--skip", help="Liste separee par des virgules de cles a ignorer")
    p.add_argument(
        "--cooldown",
        type=float,
        default=DEFAULT_COOLDOWN,
        help="Pause entre runs (secondes)",
    )
    p.add_argument(
        "--no-headless",
        action="store_true",
        help="Desactive le mode headless (scrapers).",
    )
    p.add_argument("--debug", action="store_true", help="Active les logs debug")

    p.add_argument("--fb-username", help="Username/ID Facebook a cibler")
    p.add_argument("--ig-username", help="Username Instagram a cibler")
    p.add_argument("--rd-username", help="Username Reddit a cibler")
    p.add_argument("--tt-username", help="Username TikTok a cibler (sans @)")
    p.add_argument("--tw-username", help="Username Twitter/X a cibler")

    p.add_argument(
        "--output-dir",
        type=Path,
        default=Path("bench_results"),
        help="Repertoire de sortie CSV / JSON",
    )
    return p.parse_args()


def _parse_csv_list(value: str | None) -> list[str] | None:
    if not value:
        return None
    return [v.strip() for v in value.split(",") if v.strip()]


def main() -> int:
    args = parse_args()
    expect = args.expect if args.expect is not None else args.limit

    try:
        specs = resolve_specs(
            only=_parse_csv_list(args.only),
            skip=_parse_csv_list(args.skip),
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    overrides_raw = {
        "facebook": args.fb_username or "",
        "instagram": args.ig_username or "",
        "reddit": args.rd_username or "",
        "tiktok": args.tt_username or "",
        "twitter": args.tw_username or "",
    }
    overrides = {k: v for k, v in overrides_raw.items() if v}

    print("Benchmark multi-services")
    print(f"  services  : {', '.join(s.key for s in specs)}")
    print(f"  runs      : {args.runs}")
    print(f"  limit     : {args.limit} (expect >= {expect})")
    print(f"  headless  : {not args.no_headless}")
    print(f"  cooldown  : {args.cooldown}s")
    for spec in specs:
        print(
            f"  target[{spec.key:<18}] : "
            f"@{resolve_username(spec, overrides)}"
        )
    print()

    records: list[RunRecord] = []
    total = len(specs) * args.runs
    done = 0
    t_global = time.monotonic()

    for spec in specs:
        username = resolve_username(spec, overrides)
        ctx = ServiceContext(
            username=username,
            limit=args.limit,
            headless=not args.no_headless,
            debug=args.debug,
        )
        for i in range(1, args.runs + 1):
            done += 1
            print(
                f"[{done}/{total}] {spec.key:<20} iter={i} "
                f"@{username} ...",
                end=" ",
                flush=True,
            )
            bench_result = run_service(spec=spec, ctx=ctx, expected=expect)
            record = RunRecord.from_bench_result(bench_result, iteration=i)
            records.append(record)
            tag = "OK" if record.success else "KO"
            extra = f" {record.failure_reason}" if record.failure_reason else ""
            print(
                f"{tag} posts={record.posts_count} "
                f"src={record.source_returned or '-'} "
                f"dur={record.duration_s}s{extra}"
            )
            if args.cooldown > 0 and done < total:
                time.sleep(args.cooldown)

    summaries = summarize(records)
    print_summary_table(summaries)
    print_synthesis(summaries)

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    context_header = {
        "limit": args.limit,
        "runs": args.runs,
        "headless": not args.no_headless,
        "debug": args.debug,
        "targets": {
            spec.key: resolve_username(spec, overrides) for spec in specs
        },
    }
    csv_path, json_path = export_results(
        records, summaries, args.output_dir, stamp, context_header
    )
    print()
    print(f"CSV : {csv_path}")
    print(f"JSON: {json_path}")
    print(f"Temps total: {time.monotonic() - t_global:.0f}s")

    any_failed = any(s.success_rate < 1.0 for s in summaries)
    return 1 if any_failed else 0


if __name__ == "__main__":
    os.chdir(_REPO_ROOT)
    sys.exit(main())
