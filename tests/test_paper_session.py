"""A wheel ``Strategy`` subclass drives a ``PaperSession`` (plan 0003, T14.11).

``PaperSession.run`` (``tantra.paper``) mirrors the backtest session loop: the
strategy's ``on_start`` / ``on_bar`` orders are buffered (``_in_callback``) as
compiled ``OrderRequest``s and flushed onto the compiled paper-exchange engine;
the exchange fills them deterministically. The strategy is the wheel
``tantra.Strategy`` (the SDK base the strategies repo inherits from).
"""

from __future__ import annotations

from decimal import Decimal

from tantra.bar import Bar
from tantra.instrument import InstrumentId
from tantra.paper import PaperSession
from tantra.strategy import Strategy

RELIANCE = InstrumentId("RELIANCE", "NSE")


def _bars():
    return [
        Bar(
            RELIANCE,
            1_700_000_000_000_000_000,
            Decimal(100),
            Decimal(100),
            Decimal(95),
            Decimal(95),
            Decimal(1000),
        ),
    ]


class BuyBelowAndSell(Strategy):
    """Rest a limit buy at 100; the first bar's close (95) trades through it."""

    def on_start(self):
        self.buy("NSE:RELIANCE", Decimal(10), limit_price=Decimal(100))


def _run() -> PaperSession:
    session = PaperSession(cash=Decimal("1_000_000"))
    session.set_market_price(RELIANCE, Decimal(100))
    session.run(BuyBelowAndSell(), _bars())
    return session


def test_strategy_buffered_orders_reach_exchange_fills():
    session = _run()
    fills = session.fills()
    assert len(fills) == 1
    fill = fills[0]
    assert str(fill.side) == "BUY"
    assert fill.quantity == Decimal(10)
    # The engine fills the bar-crossed resting limit at the crossing close.
    assert fill.price == Decimal(95)


def test_paper_session_run_is_deterministic():
    first = _run()
    second = _run()
    assert [(str(f.side), f.price, f.quantity) for f in first.fills()] == [
        (str(f.side), f.price, f.quantity) for f in second.fills()
    ]
    assert first.equity() == second.equity()
