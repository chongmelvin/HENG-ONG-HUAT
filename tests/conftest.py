from datetime import datetime

import pytest

from finbot.clock import FixedClock
from finbot.seed import demo_world
from finbot.storage.base import MemoryRepo


@pytest.fixture
def clock():
    return FixedClock(datetime(2026, 10, 18, 12, 0))


@pytest.fixture
def world(clock):
    repo = MemoryRepo()
    settings, cats, accts, people = demo_world(repo, clock.now())
    return type("W", (), dict(repo=repo, settings=settings, cats=cats, accts=accts, people=people, clock=clock))
