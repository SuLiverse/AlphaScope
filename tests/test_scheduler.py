"""DataScheduler 调度器单元测试"""

import time


class TestFetchJob:
    def test_should_run_initially(self):
        from backend.ingestion.scheduler import FetchJob

        job = FetchJob(name="test", func=lambda: None, interval_seconds=60)
        assert job.should_run() is True

    def test_should_not_run_when_disabled(self):
        from backend.ingestion.scheduler import FetchJob

        job = FetchJob(name="test", func=lambda: None, interval_seconds=60, enabled=False)
        assert job.should_run() is False

    def test_execute_success(self):
        from backend.ingestion.scheduler import FetchJob

        results = []
        job = FetchJob(name="test", func=lambda: results.append(1), interval_seconds=60)
        job.execute()
        assert job.last_status == "success"
        assert job.run_count == 1
        assert job.last_run is not None
        assert len(results) == 1

    def test_execute_error(self):
        from backend.ingestion.scheduler import FetchJob

        def fail():
            raise ValueError("boom")

        job = FetchJob(name="test", func=fail, interval_seconds=60)
        job.execute()
        assert job.last_status == "error"
        assert job.error_count == 1

    def test_should_run_after_interval(self):
        from backend.ingestion.scheduler import FetchJob

        job = FetchJob(name="test", func=lambda: None, interval_seconds=1)
        job.last_run = time.time() - 2  # 2秒前运行过
        assert job.should_run() is True


class TestDataScheduler:
    def test_add_and_remove_job(self):
        from backend.ingestion.scheduler import DataScheduler, FetchJob

        s = DataScheduler()
        job = FetchJob(name="j1", func=lambda: None, interval_seconds=60)
        s.add_job(job)
        assert "j1" in [j["name"] for j in s.get_status()]
        s.remove_job("j1")
        assert "j1" not in [j["name"] for j in s.get_status()]

    def test_tick_executes_due_jobs(self):
        from backend.ingestion.scheduler import DataScheduler, FetchJob

        s = DataScheduler()
        results = []
        job = FetchJob(name="j1", func=lambda: results.append(1), interval_seconds=0)
        s.add_job(job)
        executed = s.tick()
        assert "j1" in executed
        assert len(results) == 1

    def test_tick_skips_not_due_jobs(self):
        from backend.ingestion.scheduler import DataScheduler, FetchJob

        s = DataScheduler()
        job = FetchJob(name="j1", func=lambda: None, interval_seconds=9999)
        job.last_run = time.time()  # 刚刚运行过
        s.add_job(job)
        executed = s.tick()
        assert len(executed) == 0

    def test_get_status(self):
        from backend.ingestion.scheduler import DataScheduler, FetchJob

        s = DataScheduler()
        s.add_job(
            FetchJob(
                name="j1",
                func=lambda: None,
                interval_seconds=60,
                description="test job",
            )
        )
        status = s.get_status()
        assert len(status) == 1
        assert status[0]["name"] == "j1"
        assert status[0]["description"] == "test job"
