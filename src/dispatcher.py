import logging
import queue
import threading
import time
from dataclasses import dataclass
from typing import Callable, Optional

logger = logging.getLogger(__name__)

# Sends one complete reply (the radio client chunks it) back to whoever asked.
ReplyFn = Callable[[str], None]
# (question, sender_id, is_dm) -> answer text
AnswerFn = Callable[[str, str, bool], str]

ERROR_REPLY = "Sorry, something went wrong answering that. Please try again."
BUSY_REPLY = "Busy with other questions. Please try again in a few minutes."
PENDING_REPLY = "Still working on your last question. One at a time, please."


@dataclass
class _Job:
    question: str
    sender: str
    is_dm: bool
    reply: ReplyFn


class Dispatcher:
    """Queues questions from all radio backends and answers them one at a time.

    One thread runs the (slow) RAG + LLM pipeline; a second thread transmits replies and
    notices in order, so the next question can be worked on while a long reply is still
    going out over the air. Limits stop one sender, or a burst of senders, from tying the
    node up: each sender may have one question in progress, must wait `sender_cooldown`
    seconds between questions, and at most `max_queue` questions are held at once.
    """

    def __init__(self, answer_fn: AnswerFn, limits, clock: Callable[[], float] = time.monotonic):
        self.answer_fn = answer_fn
        self.limits = limits
        self.clock = clock
        self._lock = threading.Lock()
        self._jobs: "queue.Queue[Optional[_Job]]" = queue.Queue()
        self._outbox: "queue.Queue[Optional[tuple[ReplyFn, str]]]" = queue.Queue()
        self._in_flight = 0                       # accepted, not yet answered
        self._pending: set[str] = set()           # senders with a question in flight
        self._last_accepted: dict[str, float] = {}
        self._last_notice: dict[str, float] = {}
        self._threads: list[threading.Thread] = []

    def start(self):
        self._threads = [
            threading.Thread(target=self._answer_loop, daemon=True, name="mesh-medic-answer"),
            threading.Thread(target=self._send_loop, daemon=True, name="mesh-medic-send"),
        ]
        for t in self._threads:
            t.start()

    def stop(self, timeout: float = 5.0):
        self._jobs.put(None)
        self._outbox.put(None)
        for t in self._threads:
            t.join(timeout=timeout)

    def submit(self, question: str, sender: str, is_dm: bool, reply: ReplyFn) -> bool:
        """Accept a question for answering. Safe to call from any thread; never blocks."""
        now = self.clock()
        with self._lock:
            self._prune(now)
            if sender in self._pending:
                logger.info("Ignoring question from %s: previous one still in progress", sender)
                self._notice_locked(sender, reply, PENDING_REPLY, now)
                return False
            last = self._last_accepted.get(sender)
            if last is not None and now - last < self.limits.sender_cooldown:
                logger.info(
                    "Ignoring question from %s: %.0fs since last (cooldown %.0fs)",
                    sender, now - last, self.limits.sender_cooldown,
                )
                return False
            if self._in_flight >= self.limits.max_queue:
                logger.warning("Queue full (%d); rejecting question from %s", self._in_flight, sender)
                self._notice_locked(sender, reply, BUSY_REPLY, now)
                return False

            ahead = self._in_flight
            self._in_flight += 1
            self._pending.add(sender)
            self._last_accepted[sender] = now

        self._jobs.put(_Job(question, sender, is_dm, reply))
        if ahead and self.limits.queue_notice:
            noun = "question" if ahead == 1 else "questions"
            self._outbox.put((reply, f"Got it. {ahead} {noun} ahead of yours; answer coming."))
        return True

    def _notice_locked(self, sender: str, reply: ReplyFn, text: str, now: float):
        # At most one notice per sender per cooldown, so a spamming node can't use
        # notices to burn airtime.
        last = self._last_notice.get(sender)
        if last is not None and now - last < max(self.limits.sender_cooldown, 1.0):
            return
        self._last_notice[sender] = now
        self._outbox.put((reply, text))

    def _prune(self, now: float):
        if len(self._last_accepted) + len(self._last_notice) < 1000:
            return
        horizon = max(self.limits.sender_cooldown, 1.0)
        for d in (self._last_accepted, self._last_notice):
            for sender in [s for s, t in d.items() if now - t >= horizon]:
                del d[sender]

    def _answer_loop(self):
        while True:
            job = self._jobs.get()
            if job is None:
                return
            try:
                answer = self.answer_fn(job.question, job.sender, job.is_dm)
            except Exception as e:
                logger.error(f"Error answering question from {job.sender}: {e}", exc_info=True)
                answer = ERROR_REPLY
            finally:
                with self._lock:
                    self._in_flight -= 1
                    self._pending.discard(job.sender)
            if answer:
                self._outbox.put((job.reply, answer))

    def _send_loop(self):
        while True:
            item = self._outbox.get()
            if item is None:
                return
            reply, text = item
            try:
                reply(text)
            except Exception as e:
                logger.error(f"Error sending reply: {e}", exc_info=True)
