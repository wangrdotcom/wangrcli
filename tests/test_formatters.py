from wangr.formatters import fmt_num, fmt_pct, fmt_usd, pnl_color


def test_fmt_pct():
    assert fmt_pct(None) == ""
    assert fmt_pct(1.234, decimals=1) == "1.2%"


def test_fmt_usd():
    assert fmt_usd(None) == "$0"
    assert fmt_usd(1234.56) == "$1,235"
    assert fmt_usd(1234.56, decimals=2) == "$1,234.56"


def test_fmt_num():
    assert fmt_num(None) == ""
    assert fmt_num(1500) == "1,500"
    assert fmt_num(12.345, decimals=2) == "12.35"


def test_pnl_color():
    assert pnl_color(1) == "#2dd4bf"
    assert pnl_color(-1) == "#f87171"
    assert pnl_color("nope") == "text"
