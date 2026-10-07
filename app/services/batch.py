import logging
import threading
import uuid
from collections import Counter
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime

from app.db.base import utcnow
from app.db.models import CheckStatus

log = logging.getLogger(__name__)

FAILED = "failed"  # the check itself crashed, so nothing was stored

# Verifies one channel and returns the stored status. Runs in a worker thread.
CheckWork = Callable[[int], CheckStatus]


@dataclass
class Batch:
    """Progress of the checks running in the background."""

    id: str
    started_at: datetime
    total: int = 0
    done: int = 0
    counts: Counter = field(default_factory=Counter)  # status value or FAILED -> channels
    finished_at: datetime | None = None
    pending: set[int] = field(default_factory=set)
    finished_event: threading.Event = field(default_factory=threading.Event, repr=False)

    @property
    def finished(self) -> bool:
        return self.finished_at is not None


class CheckRunner:
    """Runs channel checks in a thread pool, a few at a time.

    Checks requested while a batch runs join that batch, so its progress always
    covers everything pending. A channel already pending is not queued twice, and
    a check that crashes is counted as failed without stopping the others.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._batch: Batch | None = None
        self._executor: ThreadPoolExecutor | None = None

    def submit(
        self, channel_ids: Iterable[int], work: CheckWork, *, max_workers: int
    ) -> Batch | None:
        """Queues the channels; returns the batch, or None if there was nothing to check."""
        ids = list(dict.fromkeys(channel_ids))
        with self._lock:
            if self._batch is None or self._batch.finished:
                if not ids:
                    return None
                self._batch = Batch(id=uuid.uuid4().hex[:12], started_at=utcnow())
                self._executor = ThreadPoolExecutor(max_workers, thread_name_prefix="check")
            batch = self._batch
            new = [channel_id for channel_id in ids if channel_id not in batch.pending]
            batch.total += len(new)
            batch.pending.update(new)
            for channel_id in new:
                self._executor.submit(self._run, batch, channel_id, work)
            return batch

    def current(self) -> Batch | None:
        """The running batch, or the last finished one until it is dismissed."""
        return self._batch

    def dismiss(self) -> None:
        """Forgets a finished batch; a running one keeps going."""
        with self._lock:
            if self._batch is not None and self._batch.finished:
                self._batch = None

    def shutdown(self) -> None:
        """Drops queued checks and lets running ones finish (on app shutdown)."""
        with self._lock:
            if self._executor is not None:
                self._executor.shutdown(wait=False, cancel_futures=True)

    def _run(self, batch: Batch, channel_id: int, work: CheckWork) -> None:
        try:
            outcome = CheckStatus(work(channel_id)).value
        except Exception:
            # One broken check must not stop the batch.
            log.exception("check of channel %s failed", channel_id)
            outcome = FAILED
        with self._lock:
            batch.pending.discard(channel_id)
            batch.done += 1
            batch.counts[outcome] += 1
            if batch.done == batch.total:
                batch.finished_at = utcnow()
                if self._batch is batch and self._executor is not None:
                    self._executor.shutdown(wait=False)
                batch.finished_event.set()
