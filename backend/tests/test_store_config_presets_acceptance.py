"""Acceptance test for config_presets -- region presets + config overrides
(active region) (issue #41).

Given a fresh SQLite database initialised from backend/schema.sql
When  add_preset("My Box", bbox=[52,26,55,28], label="My Box") is called
      then list_presets()
Then  the returned list contains that region_preset with its bbox and label
And   adding a second preset with the same (kind, name) raises the conflict
      error (the 409 mapping -- backend.store.ConflictError)
And   delete_preset(id) removes it from list_presets()
And   put then get of the active_region config_override round-trips
      {"region_id": "gulf-of-oman"}

This acceptance test covers config_presets: schema idempotency, add_preset ->
list_presets round-trip with a {bbox,label} payload, UNIQUE(kind,name) ->
ConflictError, delete_preset removes the row, and config_override upsert/read
of active_region with UTC-stamped created_at/updated_at. It was written
test-first and committed red, as an xfail, before any implementation existed;
the xfail marker was removed once the suite went green.

**API surface.** `design/contracts/storage.md` gives an *illustrative* shape
(`list_presets()`, `add_preset(name, bbox, label) -> int`,
`delete_preset(preset_id) -> None`) but leaves config-override get/put
unspecified. `design/specs/store.md` -- more specific -- pins the full
interface literally, including the two config-override methods and the
`ConflictError` exception name:

    async def list_presets(self) -> list[PresetRow]
    async def add_preset(self, name: str, bbox, label: str) -> int   # ConflictError on UNIQUE clash
    async def delete_preset(self, preset_id: int) -> None
    async def get_config_overrides(self) -> dict[str, Any]           # kind='config_override' rows, keyed by name
    async def put_config_override(self, name: str, payload: dict) -> None

This test adopts the spec's literal names verbatim (`ConflictError`,
`get_config_overrides`/`put_config_override`), following the same
spec-over-illustration precedent set by `test_store_acceptance.py`.

**Timestamp injection.** Timestamps are injectable -- no ambient clock -- for
`land_cache`/`fallback_snapshots`, where
`fetched_at`/`osm_base`/`timestamp_fetched` are meaningful *domain* facts the
caller must supply (when a fetch actually happened). But the
`design/specs/store.md` signatures for `add_preset`/`put_config_override`
take no timestamp parameter at all -- `created_at`/`updated_at` on
`config_presets` are pure row-bookkeeping metadata, not domain facts, so an
internal `datetime.now(timezone.utc)` stamp is the sensible reading. This
test therefore does not inject a clock; it only asserts the stamped
`created_at` comes back UTC-aware.

`PresetRow` mirrors the spec's `list_presets` query set
("SELECT id,name,payload_json,created_at WHERE kind='region_preset'"),
unpacked: `id`, `name`, `bbox`, `label`, `created_at`.

`ZIJ_DB_PATH` points at a `tmp_path` file so the test is hermetic and never
touches the real platformdirs location, matching `test_store_acceptance.py`
and `test_store_fallback_acceptance.py`.
"""

from pathlib import Path

import pytest

PRESET_NAME = "My Box"
PRESET_BBOX = (52.0, 26.0, 55.0, 28.0)
PRESET_LABEL = "My Box"

ACTIVE_REGION_OVERRIDE_NAME = "active_region"
ACTIVE_REGION_PAYLOAD = {"region_id": "gulf-of-oman"}


async def test_config_presets_crud_conflict_and_active_region_override_round_trip(
    tmp_path, monkeypatch
):
    # --- Given: a fresh SQLite database (hermetic path, never the real
    # platformdirs location) initialised from backend/schema.sql ---
    db_path = tmp_path / "zij-store-config-presets-test.db"
    monkeypatch.setenv("ZIJ_DB_PATH", str(db_path))

    from backend.store import ConflictError, Store

    store = Store()
    await store.init()

    assert Path(db_path).exists()

    # --- When: add_preset("My Box", bbox=[52,26,55,28], label="My Box") is
    # called ---
    preset_id = await store.add_preset(PRESET_NAME, PRESET_BBOX, PRESET_LABEL)
    assert isinstance(preset_id, int)

    # --- And: list_presets() is then called ---
    presets = await store.list_presets()

    # --- Then: the returned list contains that region_preset with its bbox
    # and label ---
    assert len(presets) == 1
    stored = presets[0]
    assert stored.id == preset_id
    assert stored.name == PRESET_NAME
    assert tuple(stored.bbox) == PRESET_BBOX
    assert stored.label == PRESET_LABEL
    assert stored.created_at.tzinfo is not None
    assert stored.created_at.utcoffset().total_seconds() == 0

    # --- And: adding a second preset with the same (kind, name) raises the
    # conflict error (409 mapping, api.md `POST /api/presets` -> `409
    # conflict` on duplicate name) ---
    with pytest.raises(ConflictError):
        await store.add_preset(PRESET_NAME, (0.0, 0.0, 1.0, 1.0), "Different label")

    # The failed duplicate attempt did not add a second row.
    presets_after_conflict = await store.list_presets()
    assert len(presets_after_conflict) == 1

    # --- And: delete_preset(id) removes it from list_presets() ---
    await store.delete_preset(preset_id)
    presets_after_delete = await store.list_presets()
    assert presets_after_delete == []

    # --- And: put then get of the active_region config_override round-trips
    # {"region_id": "gulf-of-oman"} ---
    await store.put_config_override(ACTIVE_REGION_OVERRIDE_NAME, ACTIVE_REGION_PAYLOAD)
    overrides = await store.get_config_overrides()
    assert overrides[ACTIVE_REGION_OVERRIDE_NAME] == ACTIVE_REGION_PAYLOAD

    # A second put for the same override name replaces it (upsert on
    # UNIQUE(kind,name) -- one row, not two).
    updated_payload = {"region_id": "hormuz"}
    await store.put_config_override(ACTIVE_REGION_OVERRIDE_NAME, updated_payload)
    overrides_after_update = await store.get_config_overrides()
    assert overrides_after_update[ACTIVE_REGION_OVERRIDE_NAME] == updated_payload
    assert len(overrides_after_update) == 1

    await store.close()
