from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from tantra_strategies.sdk import Bar, SimulatedContext
from tantra_strategies.sdk.order import OrderRequest, OrderSide, OrderStatus, OrderType

D = Decimal
T0 = datetime(2026, 1, 1, tzinfo=UTC)
INST = "X"


def bar(i: int, o: int, h: int, low: int, c: int) -> Bar:
    return Bar(INST, T0 + timedelta(days=i), D(o), D(h), D(low), D(c), 100, "1d")


def req(
    side: OrderSide,
    typ: OrderType,
    *,
    stop: int | None = None,
    limit: int | None = None,
    group: str | None = None,
) -> OrderRequest:
    return OrderRequest(
        INST,
        side,
        D(1),
        typ,
        limit_price=None if limit is None else D(limit),
        stop_price=None if stop is None else D(stop),
        oco_group=group,
    )


def long_ctx() -> SimulatedContext:
    ctx = SimulatedContext()
    ctx.feed(bar(0, 100, 101, 99, 100))
    ctx.submit(OrderRequest(INST, OrderSide.BUY, D(1)))
    return ctx


def bracket(ctx: SimulatedContext, side: OrderSide, stop: int, target: int) -> tuple[str, str]:
    s = ctx.submit(req(side, OrderType.STOP_MARKET, stop=stop, group="g"))
    t = ctx.submit(req(side, OrderType.LIMIT, limit=target, group="g"))
    assert s.status is OrderStatus.OPEN and t.status is OrderStatus.OPEN
    return s.order_id, t.order_id


def test_stop_market_requires_stop_price() -> None:
    with pytest.raises(ValueError):
        OrderRequest(INST, OrderSide.SELL, D(1), OrderType.STOP_MARKET)


def test_stop_price_coerced_to_decimal() -> None:
    r = OrderRequest(INST, OrderSide.SELL, D(1), OrderType.STOP_MARKET, stop_price=95)  # type: ignore[arg-type]
    assert r.stop_price == D(95)


def test_stop_fills_at_stop_price() -> None:
    ctx = long_ctx()
    sid, tid = bracket(ctx, OrderSide.SELL, 95, 110)
    ctx.feed(bar(1, 99, 102, 94, 96))
    events = ctx._drain_outbox()
    fills = [e for e in events if e.status is OrderStatus.COMPLETE]
    assert [(e.order_id, e.price) for e in fills] == [(sid, D(95))]
    assert any(e.order_id == tid and e.status is OrderStatus.CANCELLED for e in events)
    assert ctx.position(INST) == D(0)


def test_stop_gap_through_fills_at_open() -> None:
    ctx = long_ctx()
    sid, _ = bracket(ctx, OrderSide.SELL, 95, 110)
    ctx.feed(bar(1, 90, 92, 88, 91))
    fill = next(e for e in ctx._drain_outbox() if e.status is OrderStatus.COMPLETE)
    assert fill.order_id == sid and fill.price == D(90)


def test_target_fills_at_limit_and_gap_at_open() -> None:
    ctx = long_ctx()
    _, tid = bracket(ctx, OrderSide.SELL, 95, 110)
    ctx.feed(bar(1, 105, 112, 104, 111))
    fill = next(e for e in ctx._drain_outbox() if e.status is OrderStatus.COMPLETE)
    assert fill.order_id == tid and fill.price == D(110)

    ctx = long_ctx()
    _, tid = bracket(ctx, OrderSide.SELL, 95, 110)
    ctx.feed(bar(1, 115, 118, 114, 116))
    fill = next(e for e in ctx._drain_outbox() if e.status is OrderStatus.COMPLETE)
    assert fill.order_id == tid and fill.price == D(115)


def test_both_hit_stop_wins_and_target_cancelled() -> None:
    ctx = long_ctx()
    sid, tid = bracket(ctx, OrderSide.SELL, 95, 110)
    ctx.feed(bar(1, 100, 112, 94, 100))
    events = ctx._drain_outbox()
    complete = [e for e in events if e.status is OrderStatus.COMPLETE]
    cancelled = [e for e in events if e.status is OrderStatus.CANCELLED]
    assert [e.order_id for e in complete] == [sid]
    assert [e.order_id for e in cancelled] == [tid]
    assert cancelled[0].filled_quantity == D(0)
    assert ctx.position(INST) == D(0)


def test_sibling_removed_after_fill() -> None:
    ctx = long_ctx()
    bracket(ctx, OrderSide.SELL, 95, 110)
    ctx.feed(bar(1, 100, 101, 94, 96))
    ctx._drain_outbox()
    ctx.feed(bar(2, 100, 120, 99, 118))
    assert ctx._drain_outbox() == []
    assert ctx.position(INST) == D(0)


def test_plain_limit_keeps_close_semantics() -> None:
    ctx = long_ctx()
    ctx.submit(req(OrderSide.SELL, OrderType.LIMIT, limit=110))
    ctx.feed(bar(1, 100, 115, 99, 105))  # high crossed, close did not
    assert ctx._drain_outbox() == []
    ctx.feed(bar(2, 105, 112, 104, 111))  # close crossed
    fill = ctx._drain_outbox()[0]
    assert fill.price == D(110) and fill.status is OrderStatus.COMPLETE


def test_cancel() -> None:
    ctx = long_ctx()
    sid, _ = bracket(ctx, OrderSide.SELL, 95, 110)
    ev = ctx.cancel(sid)
    assert ev is not None and ev.status is OrderStatus.CANCELLED and ev.order_id == sid
    assert ctx.cancel(sid) is None
    assert ctx.cancel("nope") is None


def test_stop_already_triggered_fills_at_current_price() -> None:
    ctx = long_ctx()
    ev = ctx.submit(req(OrderSide.SELL, OrderType.STOP_MARKET, stop=105))
    assert ev.status is OrderStatus.COMPLETE and ev.price == D(100)


def test_short_position_mirror() -> None:
    ctx = SimulatedContext()
    ctx.feed(bar(0, 100, 101, 99, 100))
    ctx.submit(OrderRequest(INST, OrderSide.SELL, D(1)))
    sid, tid = bracket(ctx, OrderSide.BUY, 105, 90)
    ctx.feed(bar(1, 101, 106, 99, 104))
    fill = next(e for e in ctx._drain_outbox() if e.status is OrderStatus.COMPLETE)
    assert fill.order_id == sid and fill.price == D(105)

    ctx = SimulatedContext()
    ctx.feed(bar(0, 100, 101, 99, 100))
    ctx.submit(OrderRequest(INST, OrderSide.SELL, D(1)))
    sid, tid = bracket(ctx, OrderSide.BUY, 105, 90)
    ctx.feed(bar(1, 95, 97, 89, 92))
    fill = next(e for e in ctx._drain_outbox() if e.status is OrderStatus.COMPLETE)
    assert fill.order_id == tid and fill.price == D(90)

    ctx = SimulatedContext()
    ctx.feed(bar(0, 100, 101, 99, 100))
    ctx.submit(OrderRequest(INST, OrderSide.SELL, D(1)))
    sid, tid = bracket(ctx, OrderSide.BUY, 105, 90)
    ctx.feed(bar(1, 108, 109, 107, 108))  # gap up through the buy stop
    fill = next(e for e in ctx._drain_outbox() if e.status is OrderStatus.COMPLETE)
    assert fill.order_id == sid and fill.price == D(108)
    assert ctx.position(INST) == D(0)


def test_stop_triggered_on_submit_never_orphans_the_target() -> None:
    ctx = long_ctx()  # long 1 at close 100
    s = ctx.submit(req(OrderSide.SELL, OrderType.STOP_MARKET, stop=105, group="g"))
    assert s.status is OrderStatus.COMPLETE  # already through the stop
    t = ctx.submit(req(OrderSide.SELL, OrderType.LIMIT, limit=110, group="g"))
    assert t.status is OrderStatus.CANCELLED
    ctx.feed(bar(1, 100, 120, 99, 115))  # would have hit the target
    assert ctx.position(INST) == D(0)
    assert not [e for e in ctx._drain_outbox() if e.status is OrderStatus.COMPLETE]
