from wangr.arbitrage import ArbitrageScreen


def test_normalize_dex_pairs_basic():
    pairs = [
        {
            "token": "ABC",
            "spread_pct": 1.5,
            "spread": 12.0,
            "arbitrage": True,
            "uni_price": 100.0,
            "sushi_price": 102.0,
        }
    ]
    rows = ArbitrageScreen._normalize_dex_pairs(pairs, "USDC")
    assert rows[0]["symbol"] == "ABC/USDC"
    assert rows[0]["buy_exchange"] == "Uni"
    assert rows[0]["sell_exchange"] == "Sushi"
    assert rows[0]["net_spread_pct"] == 1.5
