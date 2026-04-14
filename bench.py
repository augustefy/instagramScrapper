import time
from contextlib import contextmanager
from dataclasses import dataclass, field


@dataclass
class _Record:
    name: str
    duration: float


class Bench:
    def __init__(self):
        self._records: list[_Record] = []
        self._start = time.perf_counter()

    @contextmanager
    def timer(self, name: str):
        t0 = time.perf_counter()
        try:
            yield
        finally:
            self._records.append(_Record(name, time.perf_counter() - t0))

    def report(self) -> str:
        total = time.perf_counter() - self._start
        col = max((len(r.name) for r in self._records), default=20) + 2
        sep = "─" * (col + 12)

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
