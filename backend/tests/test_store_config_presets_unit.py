"""Unit tests for config_presets branches the acceptance test
(test_store_config_presets_acceptance.py) never reaches (issue #41).

The acceptance test already exercises every column in `config_presets`, and
unlike `land_cache`/`fallback_snapshots` there is no nullable column here to
target -- every column in the DDL is `NOT NULL` (schema.sql). Two real
behaviour branches remain untested by the acceptance test:

1. `delete_preset` on a missing id is a defined no-op. The acceptance test
   only ever deletes an id it just inserted -- it never calls `delete_preset`
   with an id that was never assigned, so the "no-op, doesn't raise, doesn't
   disturb other rows" behaviour of `Store._delete_preset_sync` is never
   actually asserted.

2. `kind` discrimination between `region_preset` and `config_override` rows
   sharing the same `config_presets` table. In the acceptance test, the
   single `region_preset` row is deleted *before* the `config_override` row
   is ever inserted, so `list_presets()`/`get_config_overrides()` are never
   called while both kinds of row coexist -- a regression that dropped the
   `WHERE kind = ...` filter from either query would still pass it. This test
   puts both kinds in the same database and asserts each listing method only
   ever sees its own kind.
"""

from backend.store import Store

PRESET_NAME = "Persian Gulf"
PRESET_BBOX = (48.0, 24.0, 57.0, 30.0)
PRESET_LABEL = "Persian Gulf"


async def test_delete_preset_missing_id_is_a_noop(tmp_path, monkeypatch):
    monkeypatch.setenv("ZIJ_DB_PATH", str(tmp_path / "unit-config-presets-delete.db"))

    store = Store()
    await store.init()

    preset_id = await store.add_preset(PRESET_NAME, PRESET_BBOX, PRESET_LABEL)

    # Deleting an id that was never assigned raises nothing and does not
    # touch the existing row.
    await store.delete_preset(preset_id + 999)

    presets = await store.list_presets()
    assert len(presets) == 1
    assert presets[0].id == preset_id

    await store.close()


async def test_list_presets_and_get_config_overrides_are_isolated_by_kind(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("ZIJ_DB_PATH", str(tmp_path / "unit-config-presets-kind.db"))

    store = Store()
    await store.init()

    # A region_preset and a config_override coexist in the same table.
    await store.add_preset(PRESET_NAME, PRESET_BBOX, PRESET_LABEL)
    await store.put_config_override("active_region", {"region_id": "hormuz"})

    presets = await store.list_presets()
    assert len(presets) == 1
    assert presets[0].name == PRESET_NAME

    overrides = await store.get_config_overrides()
    assert list(overrides.keys()) == ["active_region"]
    assert overrides["active_region"] == {"region_id": "hormuz"}

    await store.close()
