# Spec — `config.py` (configuration module)

**Purpose.** Load and merge configuration per [config.md](../contracts/config.md) / [ADR-6](../docs/DECISIONS.md#adr-6--config-format--precedence): TOML via `tomllib` through `pydantic-settings`, secrets from env only (NFR5), region registry access, and custom-bbox validation (per-layer area caps + aviation credit estimate, FR1).

## Public interface
```python
def load_config() -> tuple[AppConfig, Secrets]      # config.md Loading design
class AppConfig(BaseModel): regions; layers; overpass; opensky; aisstream; integrity; server
class Secrets(BaseSettings): opensky_client_id; opensky_client_secret; aisstream_api_key

class ConfigService:
    def __init__(self, cfg: AppConfig, secrets: Secrets, store: Store): ...
    def regions(self) -> list[RegionCfg]                       # predefined + presets (FR1/FR11)
    def region(self, region_id: str) -> RegionCfg | None
    def effective_cadence_s(self, domain: Domain) -> int       # max(cadence_s, cadence_floor_s)
    def stale_after_s(self, domain: Domain) -> int             # cadence_s * stale_multiplier
    def validate_bbox(self, bbox: tuple[float,float,float,float]) -> BboxEstimate   # FR1
```
`BboxEstimate` mirrors the `POST /api/regions/estimate` body (api.md): `valid`, `area_sq_deg`, `aviation_credit_cost`, `layer_caps{air,land,marine}` each `{ok, cap_sq_deg, message?}`.

## Internal design

### Loading & precedence (config.md §Precedence)
Merge lowest→highest into `AppConfig`:
1. **Code defaults** — pydantic model defaults.
2. **Bundled `config.toml`** — shipped (the region table, per-layer settings).
3. **User `config.toml`** — `platformdirs.user_config_dir("zij")/config.toml`, path via `ZIJ_CONFIG_PATH`. Parsed with stdlib `tomllib` (3.13, [ADR-4](../docs/DECISIONS.md#adr-4--packaging)).
4. **Environment (`ZIJ_` prefix)** — non-secret tunables via pydantic-settings.
5. **Runtime overrides** — `store.get_config_overrides()` (`config_presets kind='config_override'`), applied at read time (FR11) — highest precedence. Includes the persisted `active_region` key (config.md §Precedence): read at startup to restore the last region, written by the scheduler on region switch.

Merge is a deep-merge of nested tables (a user override of `layers.air.cadence_s` must not wipe `layers.air.cadence_floor_s`). Implement as recursive dict merge before `AppConfig.model_validate`.

### Secrets — separate object (NFR5)
`Secrets(BaseSettings)` reads env + `.env` (dev) **only**; never any TOML. Returned as a distinct object so it can never be serialized into `GET /api/config` (which returns `AppConfig` only, api.md). **Startup fail-fast:** for each **enabled** layer, assert its required secret is present (air→`opensky_client_id`+`secret`; marine→`aisstream_api_key`). Missing → clear named error naming the env var and the layer (config.md; ARCHITECTURE §4.1). Disabled layers need no secret (FR5).

### Region registry access
- `regions()` = predefined `RegionCfg`s (bundled TOML) + `region_preset` rows from `store.list_presets()` mapped to `RegionCfg` (id `custom:<hash>` / preset id). `region(id)` resolves either.
- `RegionCfg.bbox` is `[w,s,e,n]` (config.md); converted to the adapter `Region` type at activation.

### Custom-bbox validation (FR1)
`validate_bbox(bbox)`:
1. Normalize/validate ordering (`w<e`, `s<n`, within WGS84).
2. `area_sq_deg = (e-w)*(n-s)`.
3. **Per-layer caps** from `[layers.*].custom_bbox_cap_sq_deg` (air 100, marine 40, land 40): each layer `ok = area ≤ cap`; if not, `message` names the cap (FR1 acceptance).
4. **Aviation credit estimate** via the config.md tier table (`≤25→1, ≤100→2, ≤400→3, else 4`) — same function `opensky.estimate_credits` uses (single source of truth; import it or share the table). Shown pre-activation (FR1).
5. `valid = all layer caps ok`. Backs `POST /api/regions/estimate` and the server-side re-validation in `POST /api/regions/activate` (api.md).

### Hot-reload — none in v1 (state it)
**Nothing is hot-reloadable in v1.** `load_config()` runs once at startup; changing bundled/user TOML or `ZIJ_` env requires a restart to apply. The single exception is `config_presets` runtime overrides (FR11), which are read through `store` at the point of use (cadence lookups, region list) and therefore take effect without a file reload — but they are DB rows, not file/env config. This keeps config immutable within a process lifetime (no reload races, no partial-apply); documented so operators know to restart.

## Failure modes
- Malformed TOML → `tomllib.TOMLDecodeError` surfaced with the offending file path; fail fast.
- Missing required secret for an enabled layer → named startup error (above).
- Invalid bbox (bad ordering / out of WGS84) → `validate_bbox` returns `valid:false` with a `bad_request`/`validation_error` message (api.md `422`).

## Configuration consumed
All of config.md (it *is* the loader). Env: `ZIJ_*`, `ZIJ_CONFIG_PATH`, secrets `OPENSKY_*`/`AISSTREAM_API_KEY`.

## Acceptance criteria
- [ ] **[ADR-6]** — precedence defaults < bundled TOML < user TOML < env < DB overrides, with deep-merge of nested tables.
- [ ] **NFR5** — secrets loaded only from env/`.env`, returned separately, never present in `AppConfig`/`GET /api/config`; startup fails fast (named error) when an enabled layer's secret is missing.
- [ ] **FR1** — `validate_bbox` rejects a bbox exceeding any layer cap with a message naming the cap, and returns the aviation credit estimate (tier table) before activation.
- [ ] **FR6/FR7** — `effective_cadence_s` applies the floor; `stale_after_s = cadence_s × stale_multiplier` per layer independently.
- [ ] **FR11** — region presets and `config_override` rows are read through `store` at use time (effective without a restart); file/env config is not hot-reloadable (restart required) — stated.
