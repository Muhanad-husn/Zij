# Contract — Configuration

Implements FR1, FR6, FR7, NFR5, §6.1–6.3. Format/precedence per [ADR-6](../docs/DECISIONS.md#adr-6--config-format--precedence): **TOML file + `pydantic-settings`, secrets from env only**. This is `backend/config.py` + a bundled `config.toml`.

## Precedence

Lowest → highest ([ADR-6](../docs/DECISIONS.md#adr-6--config-format--precedence)):

1. **Code defaults** — Pydantic model defaults in `config.py`.
2. **Bundled `config.toml`** — ships with the app (the region table below).
3. **User `config.toml`** — operator overrides at `platformdirs.user_config_dir("zij")/config.toml` (path via `ZIJ_CONFIG_PATH`).
4. **Environment variables** — `ZIJ_` prefix for tunables; **secrets live here and only here** (NFR5).
5. **Runtime overrides** — `config_presets(kind='config_override')` in SQLite ([storage.md](storage.md)), applied at read time (FR11). The last active region is persisted here as a `config_override` row (key `active_region`), written on region switch and read at startup to restore the default/last region ([ARCHITECTURE §4.1](../docs/ARCHITECTURE.md#41-startup--warm-cache-path-15-s-to-interactive-nfr4), [scheduler.md](../specs/scheduler.md)).

Secrets never appear in any TOML file or bundle (NFR5, §7.4). `pydantic-settings` reads `.env` in dev.

## Secrets (env only, NFR5)

| env var | source | needed from |
|---|---|---|
| `OPENSKY_CLIENT_ID` | OpenSky OAuth2 client (§7.1, D5) | v0 |
| `OPENSKY_CLIENT_SECRET` | OpenSky OAuth2 client | v0 |
| `AISSTREAM_API_KEY` | aisstream.io account (§7.1, D2) | v1 |

Startup fails fast with a named error if a secret required by an **enabled** layer is missing. Disabled layers need no secret (FR5).

## Predefined regions (FR1)

`[west, south, east, north]` in WGS84 degrees. Sized so each `/states/all` call costs **≤2 OpenSky credits** (D5, §6.1). OpenSky credit tiers by bbox area (§6.1 "cost scales with area"):

| area (sq°) | credits |
|---|---|
| ≤ 25 | 1 |
| 25 – 100 | 2 |
| 100 – 400 | 3 |
| > 400 | 4 |

The seven predefined regions and their computed cost:

| id | label | bbox `[w,s,e,n]` | area sq° | credits |
|---|---|---|---|---|
| `hormuz` | Strait of Hormuz | `[55.0, 25.0, 57.5, 27.5]` | 6.25 | 1 |
| `persian-gulf` | Persian Gulf | `[47.5, 23.5, 57.0, 30.5]` | 66.5 | 2 |
| `gulf-of-oman` | Gulf of Oman | `[56.5, 22.0, 62.0, 26.5]` | 24.75 | 1 |
| `iraq-corridor` | Iraq corridor | `[42.0, 29.5, 48.5, 35.0]` | 35.75 | 2 |
| `syria-corridor` | Syria corridor | `[35.5, 32.0, 42.0, 37.5]` | 35.75 | 2 |
| `eastern-med` | Eastern Mediterranean | `[31.0, 31.0, 36.5, 37.0]` | 33.0 | 2 |
| `suez-canal` | Suez Canal | `[31.8, 29.0, 34.5, 32.2]` | 8.64 | 1 |

Geography notes: `hormuz` spans Musandam (Oman) to Bandar Abbas (Iran); `persian-gulf` runs Shatt al-Arab (~48°E, head) to the Hormuz mouth; `gulf-of-oman` sits east of the strait along the Iran/Pakistan–Oman coasts; `iraq-corridor` covers the Basra–Baghdad logistics axis; `syria-corridor` covers Damascus–Aleppo and the coastal strip; `eastern-med` covers Cyprus, the Levantine coast, and the Syrian/Lebanese/Israeli seaboard; `suez-canal` covers Port Said→Suez plus the northern Gulf-of-Suez approach and the anchorage queue.

**Budget check (registered tier, D5/§6.1):** worst case `persian-gulf` at 2 credits, aviation cadence 10 min → 6 calls/h × 24 h × 2 = **288 credits/day** — well inside 4,000, matching §6.1's math, leaving headroom for manual refresh + a second region (success criterion §13.4: ≤50% of allowance).

## Per-layer settings (FR6, FR7)

Cadences with floors (FR6), stale = 2× cadence (FR7), and custom-bbox area caps (FR1).

```toml
[layers.air]
enabled          = true
cadence_s        = 600     # 10 min (FR6 default)
cadence_floor_s  = 60      # FR6 floor
stale_multiplier = 2       # FR7: stale when source ts > 2x cadence
deemphasize_after_s = 60   # 60 s: per-feature de-emphasis threshold (FR2); adapter stamps FeatureStatus.STALE, renderer ages client-side
custom_bbox_cap_sq_deg = 100   # <=2 OpenSky credits (D5); estimate shown pre-activation (FR1)

[layers.marine]
enabled          = true
cadence_s        = 60      # 60 s snapshot over the continuous stream (FR6)
cadence_floor_s  = 60
stale_multiplier = 2
drop_after_s     = 7200    # 2 h: drop from projection (FR3)
deemphasize_after_s = 1800 # 30 min: render de-emphasized (FR3)
custom_bbox_cap_sq_deg = 40    # aisstream subscription sanity bound

[layers.land]
enabled          = true
cadence_s        = 86400   # 24 h (D3, FR6 default)
cadence_floor_s  = 3600    # 1 h floor (FR6)
stale_multiplier = 2
custom_bbox_cap_sq_deg = 40    # Overpass payload bound (§6.3); target <=5000 features
simplify_tolerance_deg = 0.0005    # Douglas-Peucker (§6.3)
max_rendered_features  = 5000      # §6.3 target
```

`stale_multiplier` is global-overridable but per-layer here so FR7's "changing one cadence doesn't affect others" holds. `stale_after_s = cadence_s * stale_multiplier` feeds `LayerSnapshotMeta.stale_after_s` ([feature-schema.md](feature-schema.md#layersnapshot--metadata)).

## Overpass (§6.3)

```toml
[overpass]
mirrors = [
  "https://overpass-api.de/api/interpreter",
  "https://overpass.kumi.systems/api/interpreter",
  "https://overpass.private.coffee/api/interpreter",
]
timeout_s        = 180     # Overpass 'timeout' query setting
maxsize_bytes    = 536870912   # 512 MB Overpass 'maxsize'
backoff_base_s   = 5       # exponential backoff on 429/504 (§6.3)
backoff_max_s    = 300
max_attempts     = 4
# Tag whitelist (§6.3). Ways: highway in {motorway,trunk,primary}, railway=rail.
# Nodes/areas: barrier=border_control, aeroway=aerodrome, harbour=*, landuse=port,
# railway station/yard.
```

Mirror selection walks the list on failure with backoff (§6.3, §12 "mirror configurability"). Self-hosted Overpass is the P2 escape hatch (§12), added as a mirror entry — no code change.

## OpenSky (§6.1, D5)

```toml
[opensky]
token_url        = "https://auth.opensky-network.org/auth/realms/opensky-network/protocol/openid-connect/token"
states_url       = "https://opensky-network.org/api/states/all"
token_refresh_margin_s = 120   # refresh ~2 min before the ~30-min expiry (§6.1)
daily_credit_budget = 4000     # registered tier (D5); raise to 8000 if OQ2 feeder lands
credit_warn_ratio   = 0.5      # success criterion §13.4
```

## aisstream (§6.2, D2)

```toml
[aisstream]
ws_url           = "wss://stream.aisstream.io/v0/stream"
reconnect_base_s = 2       # backoff on ws drop (FR3)
reconnect_max_s  = 60
# bbox re-sent as a subscription message on connect and on region switch (FR3)
```

## Integrity (FR9, §7.3, OQ4)

FR9's landmask asset path and the kinematics thresholds live here so they are config, not magic numbers ([integrity.md](../specs/integrity.md)).

```toml
[integrity]
# Landmask for the marine spoof-suspect point-in-polygon (FR9, §7.3). Default resolves
# to platformdirs.user_data_dir("zij")/landmask/ne_10m_land.geojson; populated once by
# scripts/fetch_landmask.py (§7.3, OQ4). Overridable for a custom asset.
landmask_path       = ""       # empty → platformdirs data-dir default resolved at load
max_speed_kn_marine = 120      # FR9 implausible-kinematics threshold, marine (kn)
max_speed_kn_air    = 990      # FR9 implausible-kinematics threshold, air (Mach 3 ≈ 990 kn)
```

## SSE / server

```toml
[server]
sse_ping_s       = 15      # keep-alive interval (api.md ping event)
static_dir       = "frontend/dist"   # prod StaticFiles mount (ADR-7)
```

## Loading design (pydantic-settings)

```python
from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict

class Secrets(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    opensky_client_id: str | None = None
    opensky_client_secret: str | None = None
    aisstream_api_key: str | None = None

class RegionCfg(BaseModel):
    id: str
    label: str
    bbox: tuple[float, float, float, float]

class LayerCfg(BaseModel):
    enabled: bool = True
    cadence_s: int
    cadence_floor_s: int
    stale_multiplier: int = 2
    custom_bbox_cap_sq_deg: float
    # per-domain extras optional: air/marine deemphasize_after_s; marine drop_after_s;
    # land simplify_tolerance_deg, max_rendered_features

class AppConfig(BaseModel):
    regions: list[RegionCfg]
    layers: dict[str, LayerCfg]     # "air" | "marine" | "land"
    overpass: dict
    opensky: dict
    aisstream: dict
    integrity: dict
    server: dict

def load_config() -> tuple[AppConfig, Secrets]:
    """Merge in precedence order: defaults < bundled toml < user toml < env <
    config_overrides(DB). tomllib for parsing (stdlib, 3.13). Secrets loaded
    separately from env/.env only — never from any toml (NFR5)."""
```

`load_config()` returns config + secrets as separate objects so secrets are never accidentally serialized into `GET /api/config` ([api.md](api.md#get-apiconfig)); that endpoint returns `AppConfig` only.
