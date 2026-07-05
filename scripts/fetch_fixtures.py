"""Dev-time fixture capture (plans/fixtures/01-fixture-capture.md, issue #12).

Run manually by the founder, with OpenSky credentials in the environment
(`.env`: `OPENSKY_CLIENT_ID`, `OPENSKY_CLIENT_SECRET`):

    uv run python scripts/fetch_fixtures.py

Fetches the live OpenSky `/states/all` response and the six whitelisted
Overpass land-class queries (design/specs/overpass.md) for the Hormuz bbox
(config.toml `[[regions]]` "hormuz"), and writes them to
`backend/tests/fixtures/opensky_states_all_hormuz.json` and
`backend/tests/fixtures/overpass_hormuz.json`. These fixtures back the
locked shape test `backend/tests/test_fixtures_shape.py` and the #14/#15
adapter walking skeletons.

This is dev tooling (STRUCTURE.md "scripts/"), not product code: it is never
imported by `backend/` at runtime, and its live-network path is not
CI-tested (the shape test asserts only against the committed fixture files).

Reuses the OAuth2 client-credentials token manager from
`backend.sources.opensky.OpenSkyAdapter` (issue #13) rather than
re-implementing auth: `adapter.start()` opens the shared `httpx.AsyncClient`
and prefetches a token via the adapter's internal single-flight
`_TokenManager`; this script then issues the `/states/all` GET directly
(`OpenSkyAdapter.fetch()` itself is out of scope until opensky-adapter/02).
"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

from backend.config import AppConfig, Secrets, load_config
from backend.sources.opensky import CreditLedger, OpenSkyAdapter, OpenSkyCfg

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "backend" / "tests" / "fixtures"
OPENSKY_FIXTURE = FIXTURES_DIR / "opensky_states_all_hormuz.json"
OVERPASS_FIXTURE = FIXTURES_DIR / "overpass_hormuz.json"

# Six whitelisted land-class query bodies (design/specs/overpass.md §6.3
# whitelist), `{bbox}` substituted as Overpass `(south,west,north,east)`.
OVERPASS_QUERIES: list[tuple[str, str]] = [
    ("border_control", 'node["barrier"="border_control"]({bbox});\nout;'),
    (
        "aerodromes",
        '(\n  node["aeroway"="aerodrome"]({bbox});\n'
        '  way["aeroway"="aerodrome"]({bbox});\n);\nout center;',
    ),
    (
        "ports_harbours",
        '(\n  node["harbour"]({bbox});\n  way["harbour"]({bbox});\n'
        '  way["landuse"="port"]({bbox});\n);\nout center;',
    ),
    (
        "rail_stations_yards",
        '(\n  node["railway"~"^(station|yard)$"]({bbox});\n'
        '  way["railway"~"^(station|yard)$"]({bbox});\n);\nout center;',
    ),
    ("major_roads", 'way["highway"~"^(motorway|trunk|primary)$"]({bbox});\nout geom;'),
    ("mainline_rail", 'way["railway"="rail"]({bbox});\nout geom;'),
]


def _write_json(path: Path, data: dict[str, Any]) -> None:
    """Write pretty-printed JSON, preserving every field verbatim (no
    stripping/reshaping of upstream data, plan DoD)."""
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _find_hormuz_region(cfg: AppConfig) -> tuple[float, float, float, float]:
    """The Hormuz bbox, sourced from config (never a second hardcoded copy)."""
    for region in cfg.regions:
        if region.id == "hormuz":
            return region.bbox
    raise RuntimeError("hormuz region missing from bundled config.toml")


async def fetch_opensky_states(
    cfg: AppConfig,
    secrets: Secrets,
    bbox: tuple[float, float, float, float],
) -> dict[str, Any]:
    """GET `/states/all` for `bbox`, authenticated via the #13 token manager
    (reused through `OpenSkyAdapter.start()`)."""
    opensky_cfg = OpenSkyCfg(**cfg.opensky, **cfg.layers["air"].model_dump())
    credits = CreditLedger(opensky_cfg.daily_credit_budget)
    adapter = OpenSkyAdapter(opensky_cfg, secrets, credits)
    await adapter.start()  # opens the shared client, prefetches the token
    try:
        token = await adapter._token_manager.get_token()  # type: ignore[union-attr]
        west, south, east, north = bbox
        params = {"lamin": south, "lomin": west, "lamax": north, "lomax": east}
        response = await adapter._client.get(  # type: ignore[union-attr]
            opensky_cfg.states_url,
            params=params,
            headers={"Authorization": f"Bearer {token}"},
            timeout=30.0,
        )
        response.raise_for_status()
        return response.json()
    finally:
        await adapter.stop()


def _build_overpass_query(
    body_template: str, bbox_str: str, timeout_s: int, maxsize_bytes: int
) -> str:
    header = f"[out:json][timeout:{timeout_s}][maxsize:{maxsize_bytes}];"
    return f"{header}\n{body_template.format(bbox=bbox_str)}"


async def _fetch_overpass_class(
    client: httpx.AsyncClient,
    mirrors: list[str],
    query: str,
    timeout_s: int,
    backoff_base_s: float,
    backoff_max_s: float,
    max_attempts: int,
) -> dict[str, Any]:
    """Sequential mirror rotation with exponential backoff (design/specs/
    overpass.md "Partitioning + mirror strategy"): `429`/`504`/timeout
    advances to the next mirror and retries with `delay = min(backoff_max_s,
    backoff_base_s * 2**attempt)`."""
    last_exc: Exception | None = None
    for mirror in mirrors:
        for attempt in range(max_attempts):
            try:
                response = await client.post(
                    mirror, data={"data": query}, timeout=timeout_s + 30
                )
                # 429/504 (and any other non-2xx) trigger the same
                # mirror-rotation-with-backoff retry path below.
                response.raise_for_status()
                return response.json()
            except httpx.HTTPError as exc:
                last_exc = exc
                delay = min(backoff_max_s, backoff_base_s * (2**attempt))
                await asyncio.sleep(delay)
    raise RuntimeError(f"overpass fetch exhausted mirrors and attempts: {last_exc}")


def _oldest_osm3s(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    """Most conservative freshness claim across the six responses (design/
    specs/overpass.md "osm_base capture")."""
    return min(
        candidates,
        key=lambda osm3s: datetime.fromisoformat(
            osm3s["timestamp_osm_base"].replace("Z", "+00:00")
        ),
    )


async def fetch_overpass_all(
    cfg: AppConfig, bbox: tuple[float, float, float, float]
) -> dict[str, Any]:
    """Run the six whitelisted land-class queries sequentially (0.5 s delay
    between classes, design/specs/overpass.md), and merge into a single
    combined response: deduplicated `elements` (by `type/id`, keep first) and
    the oldest `osm3s.timestamp_osm_base` across responses."""
    overpass_cfg = cfg.overpass
    mirrors: list[str] = overpass_cfg["mirrors"]
    timeout_s: int = overpass_cfg["timeout_s"]
    maxsize_bytes: int = overpass_cfg["maxsize_bytes"]
    backoff_base_s: float = overpass_cfg["backoff_base_s"]
    backoff_max_s: float = overpass_cfg["backoff_max_s"]
    max_attempts: int = overpass_cfg["max_attempts"]

    west, south, east, north = bbox
    bbox_str = f"{south},{west},{north},{east}"

    combined_elements: dict[tuple[str, int], dict[str, Any]] = {}
    osm3s_candidates: list[dict[str, Any]] = []
    generator = "Overpass API"
    version: float = 0.6

    async with httpx.AsyncClient() as client:
        for index, (_name, body_template) in enumerate(OVERPASS_QUERIES):
            query = _build_overpass_query(body_template, bbox_str, timeout_s, maxsize_bytes)
            data = await _fetch_overpass_class(
                client, mirrors, query, timeout_s, backoff_base_s, backoff_max_s, max_attempts
            )
            generator = data.get("generator", generator)
            version = data.get("version", version)
            osm3s_candidates.append(data["osm3s"])
            for element in data.get("elements", []):
                key = (element["type"], element["id"])
                combined_elements.setdefault(key, element)
            if index < len(OVERPASS_QUERIES) - 1:
                await asyncio.sleep(0.5)

    return {
        "version": version,
        "generator": generator,
        "osm3s": _oldest_osm3s(osm3s_candidates),
        "elements": list(combined_elements.values()),
    }


async def _async_main() -> None:
    cfg, secrets = load_config()
    bbox = _find_hormuz_region(cfg)

    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)

    print("Fetching OpenSky /states/all for Hormuz...")
    opensky_data = await fetch_opensky_states(cfg, secrets, bbox)
    _write_json(OPENSKY_FIXTURE, opensky_data)
    state_count = len(opensky_data.get("states") or [])
    print(f"Wrote {state_count} OpenSky state vectors -> {OPENSKY_FIXTURE}")

    print("Fetching Overpass land-class queries for Hormuz...")
    overpass_data = await fetch_overpass_all(cfg, bbox)
    _write_json(OVERPASS_FIXTURE, overpass_data)
    element_count = len(overpass_data["elements"])
    osm_base = overpass_data["osm3s"]["timestamp_osm_base"]
    print(f"Wrote {element_count} Overpass elements (osm_base={osm_base}) -> {OVERPASS_FIXTURE}")


def main() -> None:
    try:
        asyncio.run(_async_main())
    except Exception as exc:  # top-level CLI error boundary
        print(f"fetch_fixtures failed: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
