import threading
import time

import pytest

from app.db.models import CheckStatus
from app.services.batch import FAILED, CheckRunner


class Work:
    """Fake check: optionally waits for `gate`, records concurrency, fails on `broken` ids."""

    def __init__(self, *, gate=None, broken=(), delay=0.0):
        self.gate = gate
        self.broken = set(broken)
        self.delay = delay
        self.ran = []
        self.running = 0
        self.max_running = 0
        self._lock = threading.Lock()

    def __call__(self, channel_id):
        with self._lock:
            self.running += 1
            self.max_running = max(self.max_running, self.running)
        try:
            if self.gate is not None:
                assert self.gate.wait(5)
            time.sleep(self.delay)
            if channel_id in self.broken:
                raise RuntimeError("boom")
            self.ran.append(channel_id)
            return CheckStatus.ALIVE if channel_id % 2 else CheckStatus.NO_PEERS
        finally:
            with self._lock:
                self.running -= 1


@pytest.fixture
def runner():
    r = CheckRunner()
    yield r
    r.shutdown()


def finish(batch):
    assert batch.finished_event.wait(5)
    return batch


def test_checks_every_channel_with_limited_concurrency(runner):
    work = Work(delay=0.02)

    batch = finish(runner.submit(range(1, 9), work, max_workers=2))

    assert sorted(work.ran) == list(range(1, 9))
    assert work.max_running == 2
    assert (batch.done, batch.total) == (8, 8)
    assert batch.counts == {"alive": 4, "no_peers": 4}
    assert batch.finished and batch.pending == set()


def test_a_failing_check_does_not_stop_the_batch(runner):
    batch = finish(runner.submit([1, 2, 3], Work(broken={2}), max_workers=1))

    assert batch.done == 3
    assert batch.counts == {"alive": 2, FAILED: 1}


def test_checks_requested_while_running_join_the_batch_once(runner):
    gate = threading.Event()
    work = Work(gate=gate)

    first = runner.submit([1, 2], work, max_workers=1)
    second = runner.submit([2, 3, 3], work, max_workers=1)
    gate.set()
    finish(first)

    assert second is first
    assert first.total == 3
    assert sorted(work.ran) == [1, 2, 3]


def test_nothing_to_check_starts_no_batch(runner):
    assert runner.submit([], Work(), max_workers=1) is None
    assert runner.current() is None


def test_finished_batch_stays_visible_until_dismissed(runner):
    gate = threading.Event()
    batch = runner.submit([1], Work(gate=gate), max_workers=1)

    runner.dismiss()
    assert runner.current() is batch  # still running: not dismissed

    gate.set()
    finish(batch)
    assert runner.current() is batch
    runner.dismiss()
    assert runner.current() is None


def test_a_new_request_after_a_finished_batch_starts_a_new_one(runner):
    first = finish(runner.submit([1], Work(), max_workers=1))
    second = finish(runner.submit([1], Work(), max_workers=1))

    assert second is not first
    assert second.total == 1


def test_shutdown_drops_queued_checks(runner):
    gate = threading.Event()
    work = Work(gate=gate)
    runner.submit([1, 2, 3], work, max_workers=1)
    time.sleep(0.05)  # let the first check start

    runner.shutdown()
    gate.set()
    time.sleep(0.1)

    assert work.ran == [1]
