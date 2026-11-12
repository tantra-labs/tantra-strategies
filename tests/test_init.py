def test_tantra_strategies_import():
    import tantra_strategies

    assert tantra_strategies.__version__ == "0.1.0"
    assert tantra_strategies.TurtleBreakout is not None
    assert tantra_strategies.RiskParity is not None
