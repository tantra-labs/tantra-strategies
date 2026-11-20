"""Adapters turning streaming classes into ``StreamingComputation`` dict producers."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any, Protocol

from tantra_library.model import StreamingComputation, Value
from tantra_library.primitives import source_value
from tantra_strategies.sdk.bar import Bar


class _Resettable(Protocol):
    def reset(self) -> None: ...


Extract = Callable[[Any, Bar], Mapping[str, Value]]


class StreamAdapter:
    """Wraps a streaming object and an extractor producing one value per output."""

    def __init__(self, inner: _Resettable, extract: Extract) -> None:
        self._inner = inner
        self._extract = extract

    def update(self, bar: Bar) -> Mapping[str, Value]:
        return self._extract(self._inner, bar)

    def reset(self) -> None:
        self._inner.reset()


def from_bar(inner: _Resettable, name: str) -> StreamingComputation:
    """``inner.update(bar) -> value`` exposed as a single output."""
    return StreamAdapter(inner, lambda o, bar: {name: o.update(bar)})


def from_source(inner: _Resettable, name: str, source: str) -> StreamingComputation:
    """``inner.update(Decimal) -> value`` fed from the chosen price source."""
    return StreamAdapter(inner, lambda o, bar: {name: o.update(source_value(bar, source))})


def from_dataclass(inner: _Resettable, names: Sequence[str]) -> StreamingComputation:
    """``inner.update(bar) -> dataclass``; each declared output is read by attribute."""

    def extract(o: Any, bar: Bar) -> Mapping[str, Value]:
        value = o.update(bar)
        return {n: None if value is None else getattr(value, n) for n in names}

    return StreamAdapter(inner, extract)


def from_tuple(
    inner: _Resettable, names: Sequence[str], source: str | None = None
) -> StreamingComputation:
    """``inner.update(x) -> tuple | None`` (x is the bar, or a source value if given)."""

    def extract(o: Any, bar: Bar) -> Mapping[str, Value]:
        x = bar if source is None else source_value(bar, source)
        out = o.update(x)
        if out is None:
            return {n: None for n in names}
        return dict(zip(names, out, strict=True))

    return StreamAdapter(inner, extract)
