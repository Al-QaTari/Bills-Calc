from streamlit.testing.v1 import AppTest

_OK = """
import pandas as pd
from state_manager import StateManager
from ui.historical_data_view import render_historical_data_view

StateManager.set(
    "historical_df",
    pd.DataFrame(
        {
            "tenor": [91, 91, 182, 273, 364],
            "yield": [27.0, 27.5, 28.0, 26.0, 25.0],
            "session_date": ["01/11/2026", "15/11/2026", "01/11/2026", "15/11/2026", "15/11/2026"],
            "scrape_date": pd.to_datetime(
                ["2026-11-01", "2026-11-15", "2026-11-01", "2026-11-15", "2026-11-15"]
            ),
        }
    ),
)
render_historical_data_view()
"""

_EMPTY = """
import pandas as pd
from state_manager import StateManager
from ui.historical_data_view import render_historical_data_view

StateManager.set("historical_df", pd.DataFrame())
render_historical_data_view()
"""


def test_history_renders_with_collapsed_market_expander():
    at = AppTest.from_string(_OK).run(timeout=30)
    assert not at.exception
    mk = [e for e in at.expander if "افهم السوق" in e.label]
    assert len(mk) == 1
    assert mk[0].proto.expanded is False


def test_history_empty_shows_error_not_crash():
    at = AppTest.from_string(_EMPTY).run(timeout=30)
    assert not at.exception
    assert len(at.error) == 1
