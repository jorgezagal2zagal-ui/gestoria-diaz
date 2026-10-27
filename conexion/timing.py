"""Interaction speed is local to each worker; verification remains mandatory."""

from contextlib import contextmanager
import threading
import time

_local = threading.local()


@contextmanager
def accelerated():
    previous = getattr(_local, "fast", False)
    _local.fast = True
    try:
        yield
    finally:
        _local.fast = previous


def interaction_pause(seconds):
    time.sleep(min(seconds, 0.15) if getattr(_local, "fast", False) else seconds)
