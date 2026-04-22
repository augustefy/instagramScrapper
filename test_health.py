import pytest

from app.cli.args import parse_args
from app.core.health import DataSourceHealth, HealthReport, PlatformHealth


# ── Verification du mode health sans positionnels. ──
def test_parse_args_accepts_health_without_positionals():
    args = parse_args(["--health"])

    assert args.health is True
    assert args.url is None
    assert args.n is None


# ── Verification du mode collecte standard. ──
def test_parse_args_accepts_standard_fetch_mode():
    args = parse_args(["https://www.instagram.com/openai/", "5"])

    assert args.health is False
    assert args.url == "https://www.instagram.com/openai/"
    assert args.n == 5


# ── Garde-fou CLI hors mode health. ──
def test_parse_args_requires_positionals_without_health():
    with pytest.raises(SystemExit):
        parse_args([])


# ── Verification de l aggregation degradee. ──
def test_health_report_marks_partial_availability_as_degraded():
    report = HealthReport(
        platforms=[
            PlatformHealth(
                platform="instagram",
                sources=[
                    DataSourceHealth(
                        source="api",
                        status="not_configured",
                        message="Configuration manquante",
                    ),
                    DataSourceHealth(
                        source="scraper",
                        status="healthy",
                        message="Pret",
                    ),
                ],
            ),
            PlatformHealth(
                platform="reddit",
                sources=[
                    DataSourceHealth(
                        source="api",
                        status="healthy",
                        message="Pret",
                    )
                ],
            ),
        ]
    )

    assert report.status == "degraded"
    assert report.summary["platforms"]["degraded"] == 1
    assert report.summary["sources"]["healthy"] == 2
    assert report.summary["sources"]["not_configured"] == 1
