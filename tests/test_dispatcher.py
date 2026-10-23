import threading

import pytest

from src.config import LimitsConfig
from src.dispatcher import BUSY_REPLY, ERROR_REPLY, PENDING_REPLY, Dispatcher


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class Recorder:
    def __init__(self):
        self.sent = []
        self.cond = threading.Condition()

    def reply_for(self, sender):
        def reply(text):
            with self.cond:
                self.sent.append((sender, text))
                self.cond.notify_all()

        return reply

    def wait_for(self, count, timeout=2.0):
        with self.cond:
            assert self.cond.wait_for(lambda: len(self.sent) >= count, timeout), self.sent


@pytest.fixture
def gate():
    return threading.Event()


def make(answer_fn, clock=None, **limits):
    d = Dispatcher(answer_fn, LimitsConfig(**limits), clock=clock or Clock())
    d.start()
    return d


def test_answers_question():
    rec = Recorder()
    d = make(lambda q, s, dm: f"answer to {q}")
    try:
        assert d.submit("water?", "a", True, rec.reply_for("a"))
        rec.wait_for(1)
        assert rec.sent == [("a", "answer to water?")]
    finally:
        d.stop()


def test_queue_notice_when_others_ahead(gate):
    rec = Recorder()
    d = make(lambda q, s, dm: gate.wait() and "done")
    try:
        d.submit("q1", "a", True, rec.reply_for("a"))
        d.submit("q2", "b", True, rec.reply_for("b"))
        rec.wait_for(1)
        assert rec.sent[0][0] == "b"
        assert "1 question ahead" in rec.sent[0][1]
        gate.set()
        rec.wait_for(3)
    finally:
        gate.set()
        d.stop()


def test_one_question_in_flight_per_sender_with_single_notice(gate):
    rec = Recorder()
    d = make(lambda q, s, dm: gate.wait() and "done", sender_cooldown=0)
    try:
        assert d.submit("q1", "a", True, rec.reply_for("a"))
        assert not d.submit("q2", "a", True, rec.reply_for("a"))
        assert not d.submit("q3", "a", True, rec.reply_for("a"))
        rec.wait_for(1)
        gate.set()
        rec.wait_for(2)
        assert rec.sent == [("a", PENDING_REPLY), ("a", "done")]
    finally:
        gate.set()
        d.stop()


def test_cooldown_drops_silently():
    rec = Recorder()
    clock = Clock()
    d = make(lambda q, s, dm: "done", clock=clock, sender_cooldown=30)
    try:
        assert d.submit("q1", "a", True, rec.reply_for("a"))
        rec.wait_for(1)
        clock.now += 10
        assert not d.submit("q2", "a", True, rec.reply_for("a"))
        clock.now += 30
        assert d.submit("q3", "a", True, rec.reply_for("a"))
        rec.wait_for(2)
        assert rec.sent == [("a", "done"), ("a", "done")]
    finally:
        d.stop()


def test_busy_when_queue_full(gate):
    rec = Recorder()
    d = make(lambda q, s, dm: gate.wait() and "done", max_queue=1, queue_notice=False)
    try:
        assert d.submit("q1", "a", True, rec.reply_for("a"))
        assert not d.submit("q2", "b", True, rec.reply_for("b"))
        rec.wait_for(1)
        assert rec.sent == [("b", BUSY_REPLY)]
    finally:
        gate.set()
        d.stop()


def test_handler_error_sends_apology_and_frees_sender():
    rec = Recorder()

    def boom(q, s, dm):
        raise RuntimeError("ollama down")

    d = make(boom, sender_cooldown=0)
    try:
        d.submit("q1", "a", True, rec.reply_for("a"))
        rec.wait_for(1)
        assert rec.sent == [("a", ERROR_REPLY)]
        assert d.submit("q2", "a", True, rec.reply_for("a"))
    finally:
        d.stop()
