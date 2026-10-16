"""Tests for the shared helpers (no Home Assistant needed).

    python3 tests/test_common.py
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import fake_christie  # noqa: E402,F401  (registers the package stub)
from dlp_cinema_projector.common import visible_items  # noqa: E402

ITEMS = ["DCI Flat", "DCI Scope", "Reserved PCF Flat", "OPPO 177"]

if __name__ == "__main__":
    assert visible_items(ITEMS, None, "DCI Flat") == ITEMS  # no filter = all
    assert visible_items(ITEMS, [], None) == ITEMS
    # projector order is kept, not the order of the checkboxes
    assert visible_items(ITEMS, ["OPPO 177", "DCI Flat"], "DCI Flat") == ["DCI Flat", "OPPO 177"]
    # hidden but active entry is still shown as the current value
    assert visible_items(ITEMS, ["DCI Flat"], "Reserved PCF Flat") == ["DCI Flat", "Reserved PCF Flat"]
    # new projector entries stay hidden (variant A), stale checked names are ignored
    assert visible_items(ITEMS + ["Neu"], ["DCI Scope", "Weg"], None) == ["DCI Scope"]
    print("all tests passed")
