"""
poe.ninja PoE2 builds-list / ladder client (issue #61 revival).

History: the 0.5 Astro migration was declared to have killed the
builds-list API ("NO WORKAROUND", CLAUDE.md CRITICAL #4). It hadn't —
the endpoints moved to protobuf responses, so every JSON-shaped probe
read garbage. Endpoint shapes were recovered from poe.ninja's live JS
bundles (2026-06-13) and the wire format reverse-engineered from
captured payloads (fixture: tests/fixtures/ninja_builds_search_roa.pb).

Endpoint map:
    GET /poe2/api/data/index-state                  -> JSON; snapshotVersions[]
    GET /poe2/api/builds/{version}/search           -> protobuf (columnar)
         params: overview=<snapshotName>, plus optional filters that all
         work as plain query params: name=, class=, sort=, ...
    GET /poe2/api/builds/dictionary                  -> string tables
    GET /poe2/api/builds/{version}/tooltip           -> per-row tooltip

Search response anatomy (decoded, see tests for fixture-locked shape):
    envelope (field 1) {
        1: total result count (varint)        e.g. 124,242 RoA builds
        2-4, 6-10: facet / UI definitions
        5 (repeated): COLUMN data block {
            1: column name (str)              'name', 'level', 'dps', ...
            2 (repeated x100): cell {
                1: display string             'ResurrectGodAura', '143k'
                2: numeric value (varint)     level/life/ES raw numbers
                3: packed dictionary indices  skills/keypassives refs
            }
        }
        11 (repeated): column catalog (incl. per-skill 'dps-*' columns)
    }

The decode is a generic protobuf wire walk — no .proto schema, no
protobuf dependency. Columns pivot to row dicts on extraction.

Policy note: poe.ninja CHARACTER/BUILD data is an allowed source
(player data, not game mechanics).
"""

from __future__ import annotations

import logging
import struct
from typing import Any, Dict, List, Optional, Tuple

import httpx

try:
    from .rate_limiter import RateLimiter
except ImportError:
    from src.api.rate_limiter import RateLimiter

logger = logging.getLogger(__name__)

ParsedField = Tuple[int, Any, Any]  # (field_no, wire_kind, value)


# ---------------------------------------------------------------------------
# Protobuf wire primitives (schema-less)
# ---------------------------------------------------------------------------


def _varint(buf: bytes, i: int, n: int):
    v, shift = 0, 0
    while i < n:
        b = buf[i]
        v |= (b & 0x7F) << shift
        i += 1
        if not b & 0x80:
            return v, i
        shift += 7
    return None, i


def parse_message(buf: bytes, depth: int = 0, max_depth: int = 10) -> Optional[List[ParsedField]]:
    """Parse a protobuf message without a schema.

    Length-delimited chunks are recursively tried as nested messages
    first, then as UTF-8 strings, else kept as raw bytes. Returns None
    when the buffer is not a valid message (the caller's signal to treat
    the chunk as a leaf)."""
    out: List[ParsedField] = []
    i, n = 0, len(buf)
    while i < n:
        tag, i = _varint(buf, i, n)
        if tag is None or tag == 0:
            return None
        field, wire = tag >> 3, tag & 7
        if field == 0 or field > 4000:
            return None
        if wire == 0:
            v, i = _varint(buf, i, n)
            if v is None:
                return None
            out.append((field, "int", v))
        elif wire == 1:
            if i + 8 > n:
                return None
            out.append((field, "f64", struct.unpack_from("<d", buf, i)[0]))
            i += 8
        elif wire == 2:
            ln, i = _varint(buf, i, n)
            if ln is None or i + ln > n:
                return None
            chunk = buf[i : i + ln]
            i += ln
            sub = (
                parse_message(chunk, depth + 1, max_depth)
                if (depth < max_depth and len(chunk) > 1)
                else None
            )
            if sub is not None:
                out.append((field, "msg", sub))
            else:
                try:
                    out.append((field, "str", chunk.decode("utf-8")))
                except UnicodeDecodeError:
                    out.append((field, "bytes", chunk))
        elif wire == 5:
            if i + 4 > n:
                return None
            out.append((field, "f32", struct.unpack_from("<f", buf, i)[0]))
            i += 4
        else:
            return None
    return out


# ---------------------------------------------------------------------------
# Columnar search-response decoding
# ---------------------------------------------------------------------------


def decode_search_response(payload: bytes) -> Dict[str, Any]:
    """Decode a /builds/{version}/search response into rows.

    Returns {"total": int, "columns": [names], "rows": [dicts]}.
    Cell semantics per column: display string when present, else the
    numeric value; multi-value dictionary-index cells are surfaced as
    raw index bytes under '<col>_refs' (resolution via the dictionary
    endpoint is a follow-up; names/levels/defences/dps displays are
    fully usable without it)."""
    msg = parse_message(payload)
    if not msg or msg[0][1] != "msg":
        raise ValueError("unrecognized search response shape")
    env = msg[0][2]

    total = next((v for f, k, v in env if f == 1 and k == "int"), None)
    columns: Dict[str, List[Any]] = {}
    order: List[str] = []

    for f, kind, value in env:
        if f != 5 or kind != "msg":
            continue
        col_name = next((v for ff, kk, v in value if ff == 1 and kk == "str"), None)
        if not col_name:
            continue
        # 'ehp' appears twice (ehp + tooltip variant) — keep first
        if col_name in columns:
            col_name = f"{col_name}_2"
        cells: List[Any] = []
        refs: List[Any] = []
        for ff, kk, cell in value:
            if ff != 2:
                continue
            if kk == "msg":
                display = next((v for g, w, v in cell if g == 1 and w == "str"), None)
                number = next((v for g, w, v in cell if g == 2 and w == "int"), None)
                ref = next((v for g, w, v in cell if g == 3 and w in ("str", "bytes")), None)
                cells.append(display if display is not None else number)
                refs.append(ref)
            else:
                # bare str/empty cell
                cells.append(cell if kk == "str" else None)
                refs.append(None)
        columns[col_name] = cells
        order.append(col_name)
        if any(r is not None for r in refs):
            columns[col_name + "_refs"] = refs

    row_count = max((len(v) for k, v in columns.items() if not k.endswith("_refs")), default=0)
    rows: List[Dict[str, Any]] = []
    for idx in range(row_count):
        row = {}
        for name in order:
            vals = columns.get(name, [])
            row[name] = vals[idx] if idx < len(vals) else None
        rows.append(row)

    return {"total": total, "columns": order, "rows": rows}


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class LadderClient:
    """Builds-list / ladder access over the recovered protobuf API."""

    def __init__(
        self, rate_limiter: Optional[RateLimiter] = None, client: Optional[httpx.AsyncClient] = None
    ):
        self.base_url = "https://poe.ninja"
        self.rate_limiter = rate_limiter or RateLimiter(rate_limit=20)
        self._client = client
        self._owns_client = client is None
        self._snapshots: Optional[List[Dict[str, Any]]] = None

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=30.0,
                follow_redirects=True,
                headers={"User-Agent": "PoE2-MCP-Server/1.0"},
            )
        return self._client

    async def close(self):
        if self._owns_client and self._client is not None:
            await self._client.aclose()

    async def get_snapshot(self, league_slug: str) -> Optional[Dict[str, Any]]:
        """Resolve a league slug to its current snapshot (version + name)."""
        if self._snapshots is None:
            await self.rate_limiter.acquire()
            r = await self.client.get(f"{self.base_url}/poe2/api/data/index-state")
            if r.status_code != 200:
                logger.warning(f"index-state returned {r.status_code}")
                return None
            self._snapshots = r.json().get("snapshotVersions", [])
        slug = league_slug.lower()
        return next((s for s in self._snapshots if s.get("url") == slug), None)

    async def search(self, league_slug: str, **filters: str) -> Optional[Dict[str, Any]]:
        """Search the builds list. Filters pass through as query params
        (verified working: name=, class=, sort=). Returns the decoded
        {"total", "columns", "rows"} dict, or None on failure."""
        snap = await self.get_snapshot(league_slug)
        if not snap:
            logger.warning(f"no snapshot for league slug '{league_slug}'")
            return None
        params = {"overview": snap.get("snapshotName"), **filters}
        await self.rate_limiter.acquire()
        url = f"{self.base_url}/poe2/api/builds/{snap['version']}/search"
        r = await self.client.get(url, params=params)
        if r.status_code != 200:
            logger.warning(f"builds search returned {r.status_code} for {params}")
            return None
        try:
            return decode_search_response(r.content)
        except ValueError as e:
            logger.error(f"search decode failed: {e}")
            return None

    async def top_builds(
        self, league_slug: str, class_name: Optional[str] = None, sort: str = "level"
    ) -> List[Dict[str, Any]]:
        """First ladder page (100 rows), optionally class-filtered."""
        filters: Dict[str, str] = {"sort": sort}
        if class_name:
            filters["class"] = class_name
        result = await self.search(league_slug, **filters)
        return result["rows"] if result else []
