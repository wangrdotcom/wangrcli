from wangr.sparkline import mini_bar, ratio_bar


def test_mini_bar_zero_max():
    assert mini_bar(10, 0, width=5) == "░" * 5


def test_ratio_bar():
    assert ratio_bar(70, 30, width=10) == "█" * 7 + "░" * 3
