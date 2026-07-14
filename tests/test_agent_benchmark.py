"""Agent offline benchmark suite."""

from backend.eval.agent_benchmark import run_benchmark_suite


def test_benchmark_all_pass():
    report = run_benchmark_suite()
    assert report["total"] >= 5
    assert report["all_passed"] is True, report
