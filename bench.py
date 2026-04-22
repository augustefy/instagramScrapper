import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass


@dataclass
# ── Stockage minimal d une mesure de duree. ──
class _Record:
    name: str
    duration: float


# ── Collecte des timings pour les etapes critiques. ──
class Bench:
    def __init__(self) -> None:
        self._records: list[_Record] = []
        self._start = time.perf_counter()

    @contextmanager
    def timer(self, name: str) -> Iterator[None]:
        t0 = time.perf_counter()
        try:
            yield
        finally:
            self._records.append(_Record(name, time.perf_counter() - t0))

    def report(self) -> str:
        total = time.perf_counter() - self._start
        col = max((len(r.name) for r in self._records), default=20) + 2

        lines = [
            "",
            "╔" + "═" * (col + 12) + "╗",
            f"║  {'BENCHMARK REPORT':<{col + 9}}║",
            "╠" + "═" * (col + 12) + "╣",
        ]

        for r in self._records:
            bar = self._bar(r.duration, total)
            lines.append(f"║  {r.name:<{col}} {r.duration:>5.2f}s  {bar}║")

        lines += [
            "╠" + "═" * (col + 12) + "╣",
            f"║  {'TOTAL':<{col}} {total:>5.2f}s  {'':8}║",
            "╚" + "═" * (col + 12) + "╝",
            "",
        ]
        return "\n".join(lines)

    @staticmethod
    def _bar(duration: float, total: float, width: int = 8) -> str:
        ratio = min(duration / total, 1.0) if total > 0 else 0
        filled = round(ratio * width)
        return f"{'█' * filled}{'░' * (width - filled)} "
