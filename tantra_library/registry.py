"""Registry of library entries: lookup, search, validation, evaluation."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from itertools import pairwise

from tantra_library.errors import (
    DependencyError,
    DuplicateEntry,
    InputQualityError,
    InvalidParam,
    LimitExceeded,
    NotComputable,
    UnknownEntry,
    UnknownParam,
)
from tantra_library.model import (
    Entry,
    EntryKind,
    Frame,
    ParamValue,
    StreamingComputation,
    Value,
    VolumeQuality,
)
from tantra_strategies.sdk.bar import Bar


class Registry:
    def __init__(self) -> None:
        self._entries: dict[str, Entry] = {}

    def register(self, entry: Entry) -> None:
        if entry.id in self._entries:
            raise DuplicateEntry(f"entry '{entry.id}' is already registered")
        self._entries[entry.id] = entry

    def get(self, entry_id: str) -> Entry:
        try:
            return self._entries[entry_id]
        except KeyError:
            raise UnknownEntry(f"unknown entry '{entry_id}'") from None

    def entries(self, kind: EntryKind | None = None, family: str | None = None) -> list[Entry]:
        return [
            e
            for _, e in sorted(self._entries.items())
            if (kind is None or e.kind is kind) and (family is None or e.family == family)
        ]

    def search(
        self,
        query: str,
        kind: EntryKind | None = None,
        family: str | None = None,
        limit: int = 20,
    ) -> list[Entry]:
        pool = self.entries(kind, family)
        tokens = query.lower().split()
        if not tokens:
            return pool[:limit]
        scored: list[tuple[int, int, str, Entry]] = []
        for e in pool:
            id_l = e.id.lower()
            # "ind.vidya" -> "vidya": an exact name match outranks ids that merely contain it.
            name_l = id_l.split(".", 1)[-1]
            title_l = " ".join((e.title, *e.aliases)).lower()
            text_l = f"{e.summary} {e.body_md}".lower()
            score = sum(
                (3 if t in id_l else 0) + (2 if t in title_l else 0) + (1 if t in text_l else 0)
                for t in tokens
            )
            if score > 0:
                if "-".join(tokens) == name_l:
                    score += 5
                scored.append((-score, len(e.id), e.id, e))
        # Ties: shorter (more basic) ids first, then alphabetical.
        scored.sort(key=lambda s: (s[0], s[1], s[2]))
        return [e for *_, e in scored[:limit]]

    def validate(self) -> None:
        for e in self._entries.values():
            for ref in (*e.depends_on, *e.concepts, *e.related):
                if ref not in self._entries:
                    raise DependencyError(f"entry '{e.id}' references missing entry '{ref}'")
            if e.family is not None:
                fam = self._entries.get(e.family)
                if fam is None:
                    raise DependencyError(f"entry '{e.id}' references missing family '{e.family}'")
                if fam.kind is not EntryKind.FAMILY:
                    raise DependencyError(f"entry '{e.id}': family '{e.family}' is not a family")
            for c in e.concepts:
                if self._entries[c].kind is not EntryKind.CONCEPT:
                    raise DependencyError(f"entry '{e.id}': '{c}' is not a concept")
        state: dict[str, int] = {}
        stack: list[str] = []

        def visit(node: str) -> None:
            state[node] = 1
            stack.append(node)
            for dep in self._entries[node].depends_on:
                if state.get(dep, 0) == 1:
                    cycle = [*stack[stack.index(dep) :], dep]
                    raise DependencyError("dependency cycle: " + " -> ".join(cycle))
                if state.get(dep, 0) == 0:
                    visit(dep)
            stack.pop()
            state[node] = 2

        for eid in sorted(self._entries):
            if state.get(eid, 0) == 0:
                visit(eid)

    def resolve_params(self, entry_id: str, raw: Mapping[str, object]) -> dict[str, ParamValue]:
        entry = self.get(entry_id)
        specs = {p.name: p for p in entry.params}
        for key in raw:
            if key not in specs:
                raise UnknownParam(f"entry '{entry_id}' has no parameter '{key}'")
        return {
            name: spec.coerce(raw[name]) if name in raw else spec.default
            for name, spec in specs.items()
        }

    def build(self, entry_id: str, raw_params: Mapping[str, object]) -> StreamingComputation:
        entry = self.get(entry_id)
        if entry.factory is None:
            raise NotComputable(f"entry '{entry_id}' is not computable")
        return entry.factory(self.resolve_params(entry_id, raw_params))

    def evaluate(
        self,
        entry_id: str,
        raw_params: Mapping[str, object],
        bars: Sequence[Bar],
        *,
        source_volume_quality: VolumeQuality = VolumeQuality.REAL,
        max_bars: int = 200_000,
    ) -> Frame:
        entry = self.get(entry_id)
        if len(bars) > max_bars:
            raise LimitExceeded(f"{len(bars)} bars exceeds max_bars={max_bars}")
        if (
            entry.volume_quality is VolumeQuality.REAL
            and source_volume_quality is not VolumeQuality.REAL
        ):
            raise InputQualityError(f"entry '{entry_id}' requires real volume")
        for prev, cur in pairwise(bars):
            if cur.instrument != prev.instrument:
                raise InvalidParam("bars must all belong to the same instrument")
            if cur.ts <= prev.ts:
                raise InvalidParam("bars must be strictly increasing by timestamp")
        params = self.resolve_params(entry_id, raw_params)
        if entry.factory is None:
            raise NotComputable(f"entry '{entry_id}' is not computable")
        comp = entry.factory(params)
        columns: dict[str, list[Value]] = {o.name: [] for o in entry.outputs}
        for bar in bars:
            out = comp.update(bar)
            for name, col in columns.items():
                col.append(out.get(name))
        return Frame(entry_id, params, [b.ts for b in bars], columns)

    def describe_markdown(self, entry_id: str) -> str:
        e = self.get(entry_id)
        fam = f"family `{e.family}`" if e.family else "no family"
        lines = [f"# {e.title}", "", f"`{e.id}` · {e.kind.value} · {fam}", ""]
        if e.aliases:
            lines += ["Aliases: " + ", ".join(e.aliases), ""]
        if e.summary:
            lines += [e.summary, ""]
        if e.body_md:
            lines += [e.body_md.strip(), ""]
        if e.params:
            lines += [
                "## Parameters",
                "",
                "| name | type | default | range/choices | description |",
            ]
            lines.append("|---|---|---|---|---|")
            for p in e.params:
                if p.choices:
                    rng = ", ".join(p.choices)
                else:
                    lo = "" if p.minimum is None else str(p.minimum)
                    hi = "" if p.maximum is None else str(p.maximum)
                    rng = f"{lo}..{hi}" if (lo or hi) else ""
                lines.append(
                    f"| {p.name} | {p.type.value} | {p.default} | {rng} | {p.description} |"
                )
            lines.append("")
        if e.outputs:
            lines += ["## Outputs", "", "| name | unit | description |", "|---|---|---|"]
            lines += [f"| {o.name} | {o.unit.value} | {o.description} |" for o in e.outputs]
            lines.append("")
        if e.depends_on:
            lines += ["## Builds on", ""]
            lines += [
                f"- `{d}` {self._entries[d].title}" if d in self._entries else f"- `{d}`"
                for d in e.depends_on
            ]
            lines.append("")
        if e.kind is EntryKind.CONCEPT:
            impls = [x for x in self.entries() if e.id in x.concepts]
            if impls:
                lines += ["## Implementations", ""]
                lines += [f"- `{x.id}` {x.title}" for x in impls]
                lines.append("")
        if e.related:
            lines += ["## Related", ""] + [f"- `{r}`" for r in e.related] + [""]
        if e.provenance is not None:
            lines += ["## Provenance", "", f"Origin: {e.provenance.origin}"]
            if e.provenance.reference_url:
                lines.append(f"Reference: {e.provenance.reference_url}")
            if e.provenance.notes:
                lines.append(e.provenance.notes)
            lines.append("")
        return "\n".join(lines).rstrip() + "\n"
