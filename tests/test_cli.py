from rhd.models import Observation
from rhd.render import render
from rhd.store import SqliteStore


def test_store_roundtrip_and_render(tmp_path):
    store = SqliteStore(str(tmp_path / "t.db"))
    import time

    now = int(time.time())
    for i, val in enumerate([3, 5, 4]):
        store.write(now - (2 - i) * 3600, [Observation("rosdistro", "open_prs", val)])
    store.write(now, [Observation("jenkins", "failed", 2, {"job": "nightly_linux"})])
    page = render(store, str(tmp_path / "site"))
    text = page.read_text()
    assert "rosdistro" in text and "open_prs" in text and "nightly_linux" in text
    assert "<polyline" in text
