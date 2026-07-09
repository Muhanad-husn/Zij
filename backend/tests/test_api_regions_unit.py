"""Inner unit tests, api-core slice 02 (issue #54): region endpoints.

DEC-34: these target collaborators/branches of `backend/main.py` that the
locked outer test (`test_api.py::test_region_list_estimate_and_activate`)
does not isolate:

  1. `backend.config.estimate_credits`' tier boundaries in isolation (the
     outer test only cross-checks two bboxes, both mid-tier).
  2. `_estimate_bbox`'s per-layer `message`/`ok` bookkeeping directly (the
     outer test only observes it through the HTTP envelope for one
     differential bbox).
  3. `POST /api/regions/activate` with a **custom bbox** (predefined-id-only
     in the outer test): the in-cap delegation path, the 422 re-validation
     path, and `save_as_preset` persistence via the real `Store`.
  4. `GET /api/regions/active` (never called by the outer test at all).
  5. The consolidated `GET /api/layers/{domain}/snapshot` route's
     registry-backed branch for `marine` (the outer test for #37/air/land
     lives in `test_snapshots_and_refresh`; marine's registry branch is new
     this slice and untouched by either existing outer test).

Authored during the marker-removal pass, against the now-built
`backend/main.py` (the implementer's uncommitted work at the time of
authoring), per DEC-33/DEC-34: the implementer cannot write tests, so the
test-author writes a slice's inner units from the plan's list once the
behavior exists to test against.
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient


# --- 1. Credit-tier mapping + area computation -----------------------------


def test_estimate_credits_tier_boundaries():
    """config.md tier table: area sq deg `<=25 -> 1, <=100 -> 2, <=400 -> 3,
    else -> 4`. Pin every boundary directly (not just the two mid-tier bboxes
    the outer test happens to use) so a future off-by-one in the tier
    thresholds is caught here rather than only in an HTTP-level assertion.
    """
    from backend.config import estimate_credits

    # area == 25 exactly -> tier 1 (boundary is inclusive: "<=25").
    assert estimate_credits((0.0, 0.0, 5.0, 5.0)) == 1
    # area == 25.0001 -> tier 2.
    assert estimate_credits((0.0, 0.0, 5.0, 5.0001)) == 2
    # area == 100 exactly -> tier 2.
    assert estimate_credits((0.0, 0.0, 10.0, 10.0)) == 2
    # area == 100.0001 -> tier 3.
    assert estimate_credits((0.0, 0.0, 10.0, 10.0001)) == 3
    # area == 400 exactly -> tier 3.
    assert estimate_credits((0.0, 0.0, 20.0, 20.0)) == 3
    # area == 400.0001 -> tier 4.
    assert estimate_credits((0.0, 0.0, 20.0, 20.0001)) == 4
    # A large area stays tier 4 (no fifth tier).
    assert estimate_credits((0.0, 0.0, 100.0, 100.0)) == 4


def test_estimate_bbox_area_computation_matches_geometry():
    """`_estimate_bbox`'s `area_sq_deg` is `(east-west) * (north-south)` --
    pin this on an asymmetric bbox (different west/south extents) so a
    transposed-axis bug (e.g. using width twice) would fail this test even
    though it might pass on a square bbox.
    """
    cfg, _secrets = _load_config()

    from backend.main import _estimate_bbox

    bbox = (50.0, 20.0, 58.0, 23.0)  # width 8, height 3 -> area 24
    result = _estimate_bbox(cfg, bbox)
    assert result["area_sq_deg"] == 24.0

    from backend.config import estimate_credits

    assert result["aviation_credit_cost"] == estimate_credits(bbox)


def _load_config():
    """Shared helper: `load_config()` with no overrides, relying on the
    session-wide hermetic secret baseline (conftest.py) -- every test in this
    module reads `cfg`/`secrets` only for the values `create_app`/the pure
    helpers need, never asserting on a secret's literal value, so no test
    needs its own explicit monkeypatched secret pair.
    """
    from backend.config import load_config

    return load_config()


# --- 2. Per-layer cap comparison: message only on ok:false -----------------


def test_estimate_bbox_message_present_only_when_failing_names_the_cap():
    """api.md: "message is present only when ok:false" and it names the
    exceeded cap. Directly exercise `_estimate_bbox` (rather than only via
    the HTTP envelope, which the outer test already covers for this exact
    differential bbox) so a future refactor of the estimate math keeps this
    invariant even if the HTTP wiring around it changes.
    """
    cfg, _secrets = _load_config()
    land_cap = cfg.layers["land"].custom_bbox_cap_sq_deg
    marine_cap = cfg.layers["marine"].custom_bbox_cap_sq_deg
    air_cap = cfg.layers["air"].custom_bbox_cap_sq_deg
    assert land_cap == 40
    assert marine_cap == 40
    assert air_cap == 100

    from backend.main import _estimate_bbox

    # area 50: over land/marine cap (40), under air cap (100).
    result = _estimate_bbox(cfg, (40.0, 20.0, 50.0, 25.0))
    assert result["valid"] is False

    air_entry = result["layer_caps"]["air"]
    assert air_entry["ok"] is True
    assert "message" not in air_entry

    for domain in ("land", "marine"):
        entry = result["layer_caps"][domain]
        assert entry["ok"] is False
        assert "message" in entry
        assert "cap" in entry["message"].lower()
        assert domain in entry["message"].lower()

    # A bbox in-cap for every layer: no layer carries a message at all.
    ok_result = _estimate_bbox(cfg, (40.0, 20.0, 42.0, 21.0))  # area 2
    assert ok_result["valid"] is True
    for domain_entry in ok_result["layer_caps"].values():
        assert domain_entry["ok"] is True
        assert "message" not in domain_entry


# --- 3. activate: custom bbox (in-cap delegate / 422 / save_as_preset) -----


def _build_app_for_activate(tmp_path, *, db_name="activate.db"):
    from backend.main import create_app
    from backend.store import Store

    cfg, secrets = _load_config()

    static_dir = tmp_path / "dist"
    static_dir.mkdir()
    (static_dir / "index.html").write_text(
        "<!doctype html><html><body>Zij</body></html>", encoding="utf-8"
    )
    store = Store(db_path=tmp_path / db_name)
    scheduler = AsyncMock()
    app = create_app(
        static_dir=static_dir,
        config=cfg,
        secrets=secrets,
        store=store,
        scheduler=scheduler,
    )
    return app, cfg, store, scheduler


def test_activate_custom_bbox_in_cap_delegates_scheduler_with_matching_region(
    tmp_path,
):
    """`POST /api/regions/activate` with a custom `{bbox, label}` (no
    `region_id`) re-validates the bbox server-side (reusing `_estimate_bbox`)
    and, when in-cap, awaits `scheduler.activate_region` with a real `Region`
    carrying the REQUESTED bbox/label -- not a predefined region's. The
    response's `active_region.kind` for this ephemeral (not saved-as-preset)
    case is asserted as the implementation's actual value, `"custom"` -- a
    third `kind` beyond `predefined`/`preset` that api.md does not name
    explicitly; flagged for the reviewer rather than treated as self-evidently
    correct.
    """
    from backend.sources.base import Region

    app, cfg, _store, scheduler = _build_app_for_activate(tmp_path)

    custom_bbox = [50.0, 20.0, 52.0, 22.0]  # area 4, in every layer's cap
    with TestClient(app) as client:
        resp = client.post(
            "/api/regions/activate",
            json={"bbox": custom_bbox, "label": "My Custom Box"},
        )

    assert resp.status_code == 200
    body = resp.json()
    active = body["active_region"]
    assert active["label"] == "My Custom Box"
    assert list(active["bbox"]) == custom_bbox
    # Implementation's actual (undocumented-by-api.md) value for an
    # activated-but-not-saved custom bbox.
    assert active["kind"] == "custom"

    scheduler.activate_region.assert_awaited_once()
    call = scheduler.activate_region.await_args
    region_arg = call.args[0] if call.args else call.kwargs.get("region")
    assert isinstance(region_arg, Region)
    assert region_arg.label == "My Custom Box"
    assert tuple(region_arg.bbox) == tuple(custom_bbox)
    # Distinct from every predefined id -- proves the handler built a fresh
    # region rather than resolving/aliasing a config region.
    assert region_arg.id not in {r.id for r in cfg.regions}


def test_activate_custom_bbox_over_cap_returns_422_and_never_calls_scheduler(
    tmp_path,
):
    """The custom-bbox branch of `POST /api/regions/activate` re-validates
    server-side using the SAME `_estimate_bbox` math the `/estimate` endpoint
    uses (api.md: "Custom bbox is re-validated server-side") -- an
    over-cap bbox must 422 with the validation_error envelope AND must NOT
    reach `scheduler.activate_region` at all, proving the cap check gates the
    delegation rather than merely annotating a response that still activates.
    """
    app, _cfg, _store, scheduler = _build_app_for_activate(
        tmp_path, db_name="activate_422.db"
    )

    over_cap_bbox = [40.0, 20.0, 50.0, 25.0]  # area 50 > land/marine cap (40)
    with TestClient(app) as client:
        resp = client.post(
            "/api/regions/activate",
            json={"bbox": over_cap_bbox, "label": "Too Big"},
        )

    assert resp.status_code == 422
    body = resp.json()
    assert body["error"]["code"] == "validation_error"
    details = body["error"]["details"]
    assert details["valid"] is False
    assert details["layer_caps"]["land"]["ok"] is False
    assert details["layer_caps"]["marine"]["ok"] is False

    scheduler.activate_region.assert_not_awaited()


async def test_activate_custom_bbox_save_as_preset_persists_via_store(tmp_path):
    """`save_as_preset: true` on a custom-bbox activate must persist the
    region as a preset via the real `Store` (FR11), not just annotate the
    HTTP response -- verified by re-reading `store.list_presets()` directly
    (a fresh read from the same collaborator the handler wrote through, not
    merely trusting the response body), and the returned `kind` becomes
    `"preset"` with an id keyed to the persisted preset's row id.
    """
    app, _cfg, store, scheduler = _build_app_for_activate(
        tmp_path, db_name="activate_preset.db"
    )

    preset_bbox = [51.0, 21.0, 53.0, 23.0]  # area 4, in-cap
    with TestClient(app) as client:
        resp = client.post(
            "/api/regions/activate",
            json={
                "bbox": preset_bbox,
                "label": "Saved Box",
                "save_as_preset": True,
            },
        )

        assert resp.status_code == 200
        active = resp.json()["active_region"]
        assert active["kind"] == "preset"
        assert active["id"].startswith("custom:")

        scheduler.activate_region.assert_awaited_once()

        # Re-read via the SAME Store instance (still initialized -- the
        # TestClient's lifespan is still open) so this is a fresh read from
        # the collaborator the handler wrote through, not the response body.
        presets = await store.list_presets()

    assert len(presets) == 1
    assert presets[0].label == "Saved Box"
    assert list(presets[0].bbox) == preset_bbox
    assert active["id"] == f"custom:{presets[0].id}"


# --- 4. GET /api/regions/active -------------------------------------------


def test_regions_active_returns_the_config_resolved_default_before_activation(
    tmp_path,
):
    """`GET /api/regions/active` before any `POST /api/regions/activate`
    call must reflect the app's actually-resolved starting region
    (`config.active_region_id`, config.md "Precedence" #5) -- not merely
    echo a hardcoded literal -- so the assertion is cross-checked against
    `cfg.active_region_id` read independently in this test, and against the
    matching `RegionCfg` entry's own label/bbox.

    Gap for the reviewer: plans/api-core/02-region-endpoints.md's inner-loop
    item says "returns the active region, else null", but in the current
    implementation `active_region_state["info"]` is unconditionally
    initialized from `config.regions` (falling back to the bundled `hormuz`
    entry, never to `None`) -- and `create_app` itself would already raise
    `StopIteration` while resolving `hormuz_cfg` if `config.regions` were ever
    empty, before reaching that fallback. The documented "else null" branch
    therefore appears unreachable as currently written; this test pins the
    real (always-populated) behavior rather than forcing an unreachable
    `None` case.
    """
    from backend.main import create_app
    from backend.store import Store

    cfg, secrets = _load_config()
    assert cfg.active_region_id

    static_dir = tmp_path / "dist"
    static_dir.mkdir()
    (static_dir / "index.html").write_text(
        "<!doctype html><html><body>Zij</body></html>", encoding="utf-8"
    )
    store = Store(db_path=tmp_path / "active_default.db")
    scheduler = AsyncMock()
    app = create_app(
        static_dir=static_dir,
        config=cfg,
        secrets=secrets,
        store=store,
        scheduler=scheduler,
    )

    expected_cfg = next(r for r in cfg.regions if r.id == cfg.active_region_id)

    with TestClient(app) as client:
        resp = client.get("/api/regions/active")

    assert resp.status_code == 200
    active = resp.json()["active_region"]
    assert active["id"] == expected_cfg.id
    assert active["label"] == expected_cfg.label
    assert list(active["bbox"]) == list(expected_cfg.bbox)
    assert active["kind"] == "predefined"
    # No activate call happened -- scheduler untouched.
    scheduler.activate_region.assert_not_awaited()


def test_regions_active_reflects_the_most_recently_activated_region(tmp_path):
    """`GET /api/regions/active` must track the LAST successful
    `POST /api/regions/activate` call, not just the pre-activation default --
    a handler that updates the response of `/activate` but forgets to update
    the state `/active` reads would fail this test even though
    `test_region_list_estimate_and_activate` (the outer test, which never
    calls `GET /api/regions/active` at all) would still pass.
    """
    app, cfg, _store, scheduler = _build_app_for_activate(
        tmp_path, db_name="active_after_activate.db"
    )
    gulf_of_oman = next(r for r in cfg.regions if r.id == "gulf-of-oman")

    with TestClient(app) as client:
        before = client.get("/api/regions/active").json()["active_region"]
        assert before["id"] != "gulf-of-oman"

        activate_resp = client.post(
            "/api/regions/activate", json={"region_id": "gulf-of-oman"}
        )
        assert activate_resp.status_code == 200

        after = client.get("/api/regions/active").json()["active_region"]

    assert after["id"] == "gulf-of-oman"
    assert after["label"] == gulf_of_oman.label
    assert list(after["bbox"]) == list(gulf_of_oman.bbox)
    scheduler.activate_region.assert_awaited_once()


# --- 5. Consolidated /api/layers/{domain}/snapshot: marine via registry ----


def test_layers_marine_snapshot_served_from_registry(tmp_path):
    """The consolidated `GET /api/layers/{domain}/snapshot` route (#37) pulls
    `marine` from the `Registry` (the scheduler's sole writer) rather than
    direct-fetching like air/land -- pin that branch here, independent of
    `test_snapshots_and_refresh` (which only exercises air/land) and of the
    outer test for this slice (which never touches `/api/layers/*` at all).
    A real `Feature`/`LayerSnapshot` is constructed (mirroring the marine
    caveats outer test's pattern) so this is not a tautology against a stub.
    """
    from backend.main import create_app
    from backend.models import (
        Domain,
        Feature,
        FeatureStatus,
        GeometryType,
        LayerSnapshot,
        LayerSnapshotMeta,
        LayerStatus,
    )
    from backend.registry import Registry
    from backend.store import Store

    cfg, secrets = _load_config()

    fetched = datetime(2026, 7, 9, 12, 0, 0, tzinfo=timezone.utc)
    vessel = Feature(
        domain=Domain.MARINE,
        source="aisstream",
        source_id="mmsi-1",
        label="Vessel 1",
        lat=26.1,
        lon=56.2,
        geometry_type=GeometryType.POINT,
        geometry=None,
        timestamp_source=fetched,
        timestamp_fetched=fetched,
        position_age_s=0.0,
        status=FeatureStatus.LIVE,
        raw_payload={"mmsi": "mmsi-1"},
    )
    marine_meta = LayerSnapshotMeta(
        layer=Domain.MARINE,
        region_id="hormuz",
        status=LayerStatus.LIVE,
        timestamp_fetched=fetched,
        timestamp_source=fetched,
        cadence_s=60,
        stale_after_s=120,
        feature_count=1,
    )
    marine_snapshot = LayerSnapshot(meta=marine_meta, features=[vessel])

    registry = Registry()
    registry[Domain.MARINE] = marine_snapshot

    static_dir = tmp_path / "dist"
    static_dir.mkdir()
    (static_dir / "index.html").write_text(
        "<!doctype html><html><body>Zij</body></html>", encoding="utf-8"
    )
    store = Store(db_path=tmp_path / "marine_snapshot.db")
    app = create_app(
        static_dir=static_dir,
        config=cfg,
        secrets=secrets,
        store=store,
        registry=registry,
    )

    with TestClient(app) as client:
        resp = client.get("/api/layers/marine/snapshot")

    assert resp.status_code == 200
    body = resp.json()
    assert body["meta"]["layer"] == "marine"
    assert body["meta"]["feature_count"] == 1
    assert len(body["features"]) == 1
    assert body["features"][0]["source_id"] == "mmsi-1"
    # raw_payload never rides the wire, even for the registry-backed branch.
    assert "raw_payload" not in resp.text


def test_layers_marine_snapshot_404_not_found_when_registry_empty(tmp_path):
    """The registry-backed branch (marine, and any future registry-only
    domain) 404s with the api.md `not_found` envelope when nothing has been
    fetched for that domain yet -- distinct from air/land, which always
    direct-fetch and so never hit this branch. An empty `Registry` (no
    scheduler has ever run) is the deterministic trigger.
    """
    from backend.main import create_app
    from backend.registry import Registry
    from backend.store import Store

    cfg, secrets = _load_config()

    static_dir = tmp_path / "dist"
    static_dir.mkdir()
    (static_dir / "index.html").write_text(
        "<!doctype html><html><body>Zij</body></html>", encoding="utf-8"
    )
    store = Store(db_path=tmp_path / "marine_404.db")
    app = create_app(
        static_dir=static_dir,
        config=cfg,
        secrets=secrets,
        store=store,
        registry=Registry(),
    )

    with TestClient(app) as client:
        resp = client.get("/api/layers/marine/snapshot")

    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "not_found"


# --- 6. Regression: duplicate save_as_preset activate -> 409 conflict -----


async def test_activate_custom_bbox_save_as_preset_duplicate_label_returns_409(
    tmp_path,
):
    """Regression for the defect fixed in `a8ef654`: activating a custom
    bbox with `save_as_preset: true` when the label/name collides with an
    already-persisted preset must surface the api.md `conflict` envelope
    (409), mirroring `POST /api/presets`'s own `ConflictError -> 409` idiom
    (`backend/main.py` around the `/api/presets` route) -- NOT bubble the
    raw `store.add_preset` `ConflictError` into an unhandled 500. The first
    activate-with-the-same-label succeeds (200) so the second call's failure
    is provably a collision with a real persisted row, not e.g. a bbox
    validation issue.
    """
    app, _cfg, store, scheduler = _build_app_for_activate(
        tmp_path, db_name="activate_conflict.db"
    )

    dup_bbox = [51.0, 21.0, 53.0, 23.0]  # area 4, in-cap
    with TestClient(app) as client:
        first = client.post(
            "/api/regions/activate",
            json={
                "bbox": dup_bbox,
                "label": "Duplicate Box",
                "save_as_preset": True,
            },
        )
        assert first.status_code == 200
        assert first.json()["active_region"]["kind"] == "preset"

        second = client.post(
            "/api/regions/activate",
            json={
                "bbox": dup_bbox,
                "label": "Duplicate Box",
                "save_as_preset": True,
            },
        )

        assert second.status_code == 409
        body = second.json()
        assert body["error"]["code"] == "conflict"

        # Only the first activate's preset persisted -- the collision was
        # rejected outright rather than silently overwriting/duplicating it.
        # Read via the SAME Store instance while the TestClient's lifespan
        # is still open (a fresh read from the collaborator the handler
        # wrote through, not the response body).
        presets = await store.list_presets()

    assert len(presets) == 1

    # The scheduler was only awaited for the first (successful) activate --
    # the second call's `ConflictError` is raised (in `backend/main.py`'s
    # `/api/regions/activate`) BEFORE `scheduler.activate_region` would be
    # reached, so the conflict aborts the whole request rather than
    # partially activating a region that failed to persist as a preset.
    assert scheduler.activate_region.await_count == 1


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__])
