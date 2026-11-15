"""T017: rate limiting, bounded retries, fallback on error / empty search / low coverage."""
import pytest

from analogfinder.errors import SourceError
from analogfinder.sources.base import (EmptyResult, ProbeResult, RateLimiter, Source, TransientError,
                                       fetch_with_fallback, with_retries)


class FakeClock:
    def __init__(self):
        self.t = 0.0
        self.sleeps = []

    def clock(self):
        return self.t

    def sleep(self, s):
        self.sleeps.append(s)
        self.t += s


def test_rate_limiter_waits_after_bucket_empty():
    c = FakeClock()
    rl = RateLimiter(2, 1.0, clock=c.clock, sleep=c.sleep)
    for _ in range(4):
        rl.acquire()
    assert len(c.sleeps) == 2 and all(abs(s - 0.5) < 1e-9 for s in c.sleeps)


def test_retries_bounded_with_backoff():
    sleeps, calls = [], []

    def fn():
        calls.append(1)
        raise TransientError("503")

    with pytest.raises(TransientError):
        with_retries(fn, 3, sleep=sleeps.append)
    assert len(calls) == 4 and sleeps == [1, 2, 4]


def test_retries_do_not_retry_other_errors():
    calls = []

    def fn():
        calls.append(1)
        raise ValueError

    with pytest.raises(ValueError):
        with_retries(fn, 3, sleep=lambda s: None)
    assert len(calls) == 1


def entry(sid, fallback=None):
    return {"source_id": sid, "dataset_version": "1", "rate_limit": {"requests": 100, "per_seconds": 1},
            "retries": 1, "fallback": fallback}


class Fake(Source):
    def __init__(self, e, data_dir, behaviour):
        super().__init__(e, data_dir, sleep=lambda s: None)
        self.behaviour, self.calls = behaviour, 0

    def probe(self):
        return ProbeResult(True, True)

    def _download(self, request, target):
        self.calls += 1
        if self.behaviour == "error":
            raise TransientError("timeout")
        if self.behaviour == "empty":
            raise EmptyResult("none")
        (target / "data.txt").write_text(self.source_id)


@pytest.mark.parametrize("behaviour", ["error", "empty"])
def test_fallback_on_error_and_empty(tmp_path, behaviour):
    srcs = {"a": Fake(entry("a", "b"), tmp_path, behaviour), "b": Fake(entry("b"), tmp_path, "ok")}
    r = fetch_with_fallback(srcs, "a", {"x": 1})
    assert r.source_id == "b" and r.used_fallback and (r.path / "data.txt").read_text() == "b"
    if behaviour == "error":
        assert srcs["a"].calls == 2  # 1 + retries


def test_fallback_on_low_coverage(tmp_path):
    srcs = {"a": Fake(entry("a", "b"), tmp_path, "ok"), "b": Fake(entry("b"), tmp_path, "ok")}
    cov = {"a": 0.1, "b": 0.9}
    r = fetch_with_fallback(srcs, "a", {"x": 1}, coverage=lambda p: cov[(p / "data.txt").read_text()],
                            min_coverage=0.5)
    assert r.source_id == "b"


def test_complete_cache_is_reused(tmp_path):
    s = Fake(entry("a"), tmp_path, "ok")
    p1, p2 = s.fetch({"x": 1}), s.fetch({"x": 1})
    assert p1 == p2 and s.calls == 1


def test_all_fail_raises(tmp_path):
    srcs = {"a": Fake(entry("a"), tmp_path, "empty")}
    with pytest.raises(SourceError, match="no items"):
        fetch_with_fallback(srcs, "a", {"x": 1})
