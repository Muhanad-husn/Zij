"""One-time fetch: Natural Earth 10m land polygons -> the FR9 landmask asset
(design/specs/integrity.md "Load once at startup"; OQ4, §7.3; STRUCTURE.md
"scripts/fetch_landmask.py").

Run manually, once, during dev/deploy setup (never at runtime -- STRUCTURE.md
"scripts/" is dev-time tooling, not something `backend/` imports):

    uv run python scripts/fetch_landmask.py

Downloads the public, no-key-required Natural Earth 10m "land" dataset as a
GeoJSON `FeatureCollection` of Polygon/MultiPolygon geometries -- exactly the
shape `backend/integrity.py` (`_load_land_geometries`) and the test fixture
(`backend/tests/fixtures/landmask_test.geojson`) already expect -- and writes
it to `[integrity].landmask_path`'s default location
(`platformdirs.user_data_dir("zij")/landmask/ne_10m_land.geojson`,
config.md), or to `--out` if given.

Source: the `nvkelso/natural-earth-vector` GitHub repo publishes Natural
Earth's shapefiles pre-converted to GeoJSON (the "geojson" branch/folder),
one file per dataset, updated in step with the upstream Natural Earth
releases used elsewhere in this project (naturalearthdata.com is
shapefile/zip-only and has no native GeoJSON export, so this pre-converted
mirror is the practical no-key public source):

    https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_10m_land.geojson

If that mirror is ever unavailable, `--url` accepts any alternate source
that serves the same GeoJSON `FeatureCollection` shape (e.g. a locally
shapefile-to-GeoJSON-converted `ne_10m_land.zip` from
https://naciscdn.org/naturalearth/10m/physical/ne_10m_land.zip).

This script does not run in CI and is not network-tested (no live download
in the test suite); `backend.integrity.Integrity.__init__` fails fast
(`LandmaskError`) if the asset it points at is missing or corrupt, so a
skipped/failed fetch here is never silently masked at runtime (NFR3).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import httpx
import platformdirs

_DEFAULT_SOURCE_URL = (
    "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/"
    "master/geojson/ne_10m_land.geojson"
)


def _default_output_path() -> Path:
    """`[integrity].landmask_path`'s empty-string default (config.md):
    `platformdirs.user_data_dir("zij")/landmask/ne_10m_land.geojson`."""
    return Path(platformdirs.user_data_dir("zij")) / "landmask" / "ne_10m_land.geojson"


def fetch_landmask(url: str, out_path: Path, *, timeout_s: float = 60.0) -> int:
    """Download `url`, validate it is a GeoJSON `FeatureCollection`, write it
    verbatim to `out_path`. Returns the feature count. Raises on any
    download/parse failure -- honest failure, no silent partial write."""
    response = httpx.get(url, timeout=timeout_s, follow_redirects=True)
    response.raise_for_status()

    collection = response.json()
    if (
        not isinstance(collection, dict)
        or collection.get("type") != "FeatureCollection"
        or not isinstance(collection.get("features"), list)
        or not collection["features"]
    ):
        raise ValueError(
            f"downloaded landmask from {url!r} is not a non-empty GeoJSON "
            "FeatureCollection"
        )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(collection), encoding="utf-8")
    return len(collection["features"])


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="output GeoJSON path (default: platformdirs data-dir, config.md)",
    )
    parser.add_argument(
        "--url",
        default=_DEFAULT_SOURCE_URL,
        help="landmask GeoJSON source URL (default: Natural Earth 10m land, "
        "nvkelso/natural-earth-vector GeoJSON mirror)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)
    out_path = args.out or _default_output_path()

    print(f"Fetching Natural Earth 10m land polygons from {args.url} ...")
    try:
        feature_count = fetch_landmask(args.url, out_path)
    except Exception as exc:  # top-level CLI error boundary
        print(f"fetch_landmask failed: {exc}", file=sys.stderr)
        sys.exit(1)

    print(f"Wrote {feature_count} land polygon feature(s) -> {out_path}")


if __name__ == "__main__":
    main()
