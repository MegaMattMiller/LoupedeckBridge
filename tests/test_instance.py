from __future__ import annotations

from bridge.instance import acquire


def test_second_instance_refuses(tmp_path):
    lock = tmp_path / "state" / "bridge.lock"
    first = acquire(lock)
    assert first is not None
    assert acquire(lock) is None       # a second bridge must not start
    first.close()                      # the first one exits…
    again = acquire(lock)              # …and a new one may start
    assert again is not None
    again.close()
