from datetime import date

import pandas as pd

import market_compare as mc


def _df():
    return pd.DataFrame(
        {
            "tenor": [91, 91, 182, 364, 357],
            "yield": [27.0, 27.5, 28.0, 26.0, 26.4],
            "session_date": [
                "01/11/2026",
                "15/11/2026",
                "15/11/2026",
                "10/10/2026",
                "20/11/2026",
            ],
        }
    )


def test_prepare_parses_dayfirst_and_sorts():
    s = mc.prepare_sessions(_df())
    assert s["session"].is_monotonic_increasing
    assert s["session"].iloc[0] == pd.Timestamp(2026, 10, 10)


def test_prepare_bad_input_is_empty():
    assert mc.prepare_sessions(None).empty
    assert mc.prepare_sessions(pd.DataFrame({"a": [1]})).empty


def test_latest_on_or_before_issue_and_better():
    s = mc.prepare_sessions(_df())
    c = mc.compare_bill(s, 91, 28.0, date(2026, 11, 16))
    assert c["status"] == "better" and c["market_yield"] == 27.5
    assert c["diff"] == 0.5 and c["session"] == date(2026, 11, 15)


def test_same_day_session_counts_and_future_session_does_not():
    s = mc.prepare_sessions(_df())
    assert mc.compare_bill(s, 91, 27.5, date(2026, 11, 15))["status"] == "same"
    c = mc.compare_bill(s, 91, 27.0, date(2026, 11, 10))
    assert c["market_yield"] == 27.0  # عطاء 1/11 مش 15/11


def test_weaker():
    s = mc.prepare_sessions(_df())
    assert mc.compare_bill(s, 91, 27.0, date(2026, 11, 16))["status"] == "weaker"


def test_gap_over_21_days_is_none():
    s = mc.prepare_sessions(_df())
    assert mc.compare_bill(s, 182, 28.0, date(2026, 12, 7))["status"] == "none"
    assert mc.compare_bill(s, 182, 28.0, date(2026, 12, 6))["status"] != "none"
    assert mc.bill_line({"status": "none"}) == "مفيش عطاء مقارن"


def test_no_prior_auction_or_tenor_is_none():
    s = mc.prepare_sessions(_df())
    assert mc.compare_bill(s, 91, 27.0, date(2026, 10, 1))["status"] == "none"
    assert mc.compare_bill(s, 273, 27.0, date(2026, 11, 16))["status"] == "none"
    assert (
        mc.compare_bill(mc.prepare_sessions(None), 91, 1, date.today())["status"]
        == "none"
    )


def test_odd_tenor_matches_nominal():
    s = mc.prepare_sessions(_df())
    s["tenor"] = s["tenor"].map(lambda t: 364 if t == 357 else t)
    c = mc.compare_bill(s, 357, 27.0, date(2026, 11, 21))
    assert c["status"] == "better" and c["market_yield"] == 26.4


def test_lines_are_labelled_estimate():
    s = mc.prepare_sessions(_df())
    assert "تقدير" in mc.bill_line(mc.compare_bill(s, 91, 28.0, date(2026, 11, 16)))


def test_takeaways():
    s = mc.prepare_sessions(_df())
    latest = mc.latest_by_tenor(s)
    assert set(latest["tenor"]) == {91, 182, 364, 357}
    assert "العائد الأعلى حاليًا في أجل 182 يوم" in mc.curve_takeaway(latest)
    assert "26.29" not in mc.curve_takeaway(latest)
    st_ = mc.period_stats(s[s["tenor"] == 91])
    assert st_.iloc[0]["avg"] == 27.25 and st_.iloc[0]["n"] == 2
    assert "91" in mc.stats_takeaway(st_)
    assert mc.curve_takeaway(None) and mc.stats_takeaway(None)


def test_csv_export_neutralizes_formula_notes():
    import ledger

    row = {c: None for c in ledger._LEDGER_COLS}
    row["id"] = 1
    row["note"] = "=HYPERLINK(1)"
    out = ledger.rows_to_csv([row])
    assert "'=HYPERLINK(1)" in out
