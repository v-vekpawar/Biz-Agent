import pytest

from app.domain.enums import Verdict
from app.services import stats


def ev(k, n, **kw):
    base = dict(success_rate=0.10, failure_rate=0.03, min_sample=50, confidence=0.90, finished=False)
    base.update(kw)
    return stats.evaluate_metric(k, n, **base)


def test_wilson_matches_known_value():
    lo, hi = stats.wilson_interval(10, 100, 0.95)
    assert lo == pytest.approx(0.0552, abs=1e-3) and hi == pytest.approx(0.1744, abs=1e-3)


def test_wilson_edges():
    assert stats.wilson_interval(0, 0) == (0.0, 1.0)
    lo, hi = stats.wilson_interval(0, 20)
    assert lo == 0.0 and 0 < hi < 0.2
    lo, hi = stats.wilson_interval(20, 20)
    assert hi == 1.0 and lo > 0.8
    with pytest.raises(ValueError):
        stats.wilson_interval(5, 3)
    with pytest.raises(ValueError):
        stats.wilson_interval(1, 10, 0.5)


def test_below_min_sample_never_decides():
    assert ev(40, 45)["verdict"] == Verdict.KEEP_RUNNING.value  # 89% but only 45 < 50 trials
    assert ev(40, 45, finished=True)["verdict"] == Verdict.INCONCLUSIVE.value


def test_go_stop_pivot():
    assert ev(30, 150)["verdict"] == "go"
    assert ev(2, 300)["verdict"] == "stop"
    assert ev(18, 300)["verdict"] == "pivot"


def test_straddling_interval_keeps_running_then_inconclusive():
    r = ev(6, 60)  # 10% observed; interval straddles the 10% target
    assert r["verdict"] == "keep_running" and r["code"] == "interval_straddles_threshold"
    assert ev(6, 60, finished=True)["verdict"] == "inconclusive"


def test_combine_downgrades_go_when_supporting_metric_fails():
    primary = {"verdict": "go"}
    supporting = [{"verdict": "stop", "label": "Interview commitment"}]
    verdict, notes = stats.combine(primary, supporting)
    assert verdict == Verdict.PIVOT and "Interview commitment" in notes[0]
    assert stats.combine({"verdict": "stop"}, [{"verdict": "go", "label": "x"}])[0] == Verdict.STOP


def test_suggested_min_sample_is_monotonic_in_target():
    assert stats.suggested_min_sample(0.05) > stats.suggested_min_sample(0.10) > stats.suggested_min_sample(0.30)


def test_suggested_sample_actually_clears_target():
    import math
    n = stats.suggested_min_sample(0.10, 0.90)
    lo, _ = stats.wilson_interval(math.ceil(0.15 * n), n, 0.90)
    assert lo >= 0.10
