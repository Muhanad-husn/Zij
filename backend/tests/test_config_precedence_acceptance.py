"""Locked outer acceptance test for config slice 03 (issue #46): the full
ADR-6 precedence chain (code defaults < bundled `config.toml` < user
`config.toml` < `ZIJ_`-prefixed env tunables < DB `config_presets
(kind='config_override')` rows) plus active-region persistence with a
default-region fallback.

Given a bundled default (`layers.air.cadence_s == 600`, the real, shipped
      `backend/config.toml`), a user `config.toml` overriding it to `450`
      (path via `ZIJ_CONFIG_PATH`), a `ZIJ_`-prefixed env var overriding it
      further to `300`, and a DB `config_override` overriding it to `120` for
      that same key
When  `load_config()` merges them, called incrementally so each layer's win
      is independently observable
Then  the DB override (`120`) wins over the env var (`300`), which wins over
      the user file (`450`), which wins over the bundle (`600`) -- and the
      untouched sibling key `layers.air.cadence_floor_s` stays at its bundled
      value (`60`) at every step, proving the merge is a deep-merge of nested
      tables (config-module.md "Merge is a deep-merge of nested tables") and
      never a wholesale table replacement
And   a persisted `active_region` `config_override`
      (`{"region_id": "gulf-of-oman"}`) is restored as the active region
And   when no `active_region` override exists, or its `region_id` names a
      region that isn't one of the seven predefined regions, the active
      region falls back to the configured default (`"hormuz"`, `regions[0]`,
      config.md "Predefined regions" / ARCHITECTURE §4.1 "falls back to the
      configured default when absent")
And   a secret-shaped key set in a TOML layer is never read into `Secrets`
      (NFR5: secrets are env-only, never from any TOML)

This is the behavioral contract (DEC-1), transcribed from
plans/config/03-precedence.md ("Acceptance criterion") and
design/contracts/config.md ("Precedence", "Loading design") and
design/specs/config-module.md ("Loading & precedence", "Secrets -- separate
object"). Authored and committed red by the test-author before any
implementation exists (strict xfail, DEC-33): as of this commit,
`backend.config.load_config()` takes no arguments at all and only merges
code defaults with the bundled TOML (layers 1-2) -- it does not read a user
TOML, does not read any `ZIJ_`-prefixed env var, has no `overrides` keyword,
and `AppConfig` has no `active_region_id` field. Every stage below therefore
either raises `TypeError` (unexpected `overrides` kwarg) or fails a plain
value assertion (e.g. the user-file override is silently ignored), so this
test genuinely `xfail`s rather than passing vacuously against a stub.

**Interface locked here (the implementer must build to this exact shape).**
`design/contracts/config.md` and `design/specs/config-module.md` both pin
`load_config() -> tuple[AppConfig, Secrets]` as the public signature but do
not (and structurally cannot, since they predate store/03's
`get_config_overrides()`) spell out how the DB override layer or the
persisted `active_region` key are threaded through a *synchronous*
`load_config()`. This test locks the natural, minimal, backward-compatible
extension:

    def load_config(
        *, overrides: Mapping[str, Any] | None = None,
    ) -> tuple[AppConfig, Secrets]

- `overrides` is optional and keyword-only, defaulting to `None`. Every one
  of the ~15 existing call sites (`backend/main.py::_build_default_app` plus
  every test calling `load_config()` with no arguments) keeps working
  unchanged: `overrides=None` means "no DB layer", matching today's output
  exactly. `load_config()` is still the async-free, sync function it always
  was -- the *caller* is responsible for awaiting `Store.get_config_overrides()`
  and passing the resulting `{name: payload}` dict in (the plan calls this
  "an injected store override reader"); this test injects that dict directly
  rather than standing up a real async `Store`, exactly as
  plans/config/03-precedence.md directs ("Boundary: `load_config()` with
  layered fake TOMLs + env + an injected `store` override reader").
- `overrides`'s shape mirrors `Store.get_config_overrides()`'s return value
  verbatim: `{name: payload}`. Every key *other than* the reserved name
  `"active_region"` is deep-merged directly into the accumulating
  `AppConfig`-shaped dict as another (the highest-precedence) layer -- e.g.
  `overrides={"layers": {"air": {"cadence_s": 120}}}` overrides
  `layers.air.cadence_s` without touching `layers.air.cadence_floor_s`,
  reusing the very same deep-merge already proven for the bundled/user/env
  layers. This matches `schema.sql`'s own comment on `config_presets.
  payload_json`: `-- region_preset: {bbox,label}; override: {key:value}`.
- The reserved `"active_region"` key carries `{"region_id": <id>}`
  (storage.md "config_presets") and is extracted *separately* -- it does not
  land in the deep-merge above -- to resolve a new `AppConfig.active_region_id:
  str` field: the given `region_id` when it names one of the seven predefined
  regions, else `regions[0].id` (`"hormuz"`, the configured default -- ADR-6 /
  ARCHITECTURE §4.1).
- The user-TOML layer (3) and the `ZIJ_`-prefixed env-tunable layer (4) need
  no new parameter at all: both are resolved from the real process
  environment on every call, exactly as config.md already specifies --
  `ZIJ_CONFIG_PATH` (unset -> `platformdirs.user_config_dir("zij")/
  config.toml`) for the user file, and `ZIJ_`-prefixed vars (this test locks
  the pydantic-settings nested-delimiter convention `ZIJ_LAYERS__AIR__CADENCE_S`
  for a nested tunable) for env. Neither layer contributes anything when the
  file doesn't exist / no such var is set, which is why this is
  backward-compatible for every existing no-arg call site: none of them set
  `ZIJ_CONFIG_PATH` or any `ZIJ_LAYERS__*` var, and (per
  `test_config_acceptance.py`'s own defensive `monkeypatch.delenv
  ("ZIJ_CONFIG_PATH")`) no CI/dev environment is expected to carry a stray
  real user config at that path.

Note on import hermeticity: `backend.config` is imported inside the test
body, not at module scope, matching `test_config_acceptance.py`/
`test_config_sections_acceptance.py` -- an eager module-level `load_config()`
call would run during pytest *collection*, before `conftest.py`'s
session-scoped secret baseline fixture has run, and abort the whole suite in
a secret-free CI environment.
"""

# config.md "[layers.air]" (bundled default) / "Predefined regions".
BUNDLED_AIR_CADENCE_S = 600
BUNDLED_AIR_CADENCE_FLOOR_S = 60

USER_TOML_AIR_CADENCE_S = 450
ENV_AIR_CADENCE_S = 300
DB_OVERRIDE_AIR_CADENCE_S = 120

DEFAULT_REGION_ID = (
    "hormuz"  # config.md "Predefined regions" regions[0]; ARCHITECTURE §4.1 default
)
OTHER_REGION_ID = (
    "gulf-of-oman"  # a different predefined region, to prove restore is real
)
UNKNOWN_REGION_ID = "atlantis-not-a-real-region"  # not in the 7 predefined regions

TOML_SECRET_LEAK_CLIENT_ID = "toml-secret-should-never-leak-into-Secrets-client-id"
TOML_SECRET_LEAK_CLIENT_SECRET = (
    "toml-secret-should-never-leak-into-Secrets-client-secret"
)

REAL_OPENSKY_CLIENT_ID = "precedence-outer-real-opensky-client-id"
REAL_OPENSKY_CLIENT_SECRET = "precedence-outer-real-opensky-client-secret"
REAL_AISSTREAM_API_KEY = "precedence-outer-real-aisstream-api-key"


def _set_hermetic_secrets(monkeypatch) -> None:
    """Air and marine are both enabled in the bundled config.toml (slice
    config-02, #42); both secret gates need real (non-empty) values or
    `load_config()` raises `MissingSecretError` for a reason this test does
    not cover."""
    monkeypatch.setenv("OPENSKY_CLIENT_ID", REAL_OPENSKY_CLIENT_ID)
    monkeypatch.setenv("OPENSKY_CLIENT_SECRET", REAL_OPENSKY_CLIENT_SECRET)
    monkeypatch.setenv("AISSTREAM_API_KEY", REAL_AISSTREAM_API_KEY)


def test_precedence_chain_and_active_region_restore(tmp_path, monkeypatch):
    _set_hermetic_secrets(monkeypatch)

    from backend.config import load_config

    # === Stage A: nothing but the bundle -- no user file, no ZIJ_ env, no DB
    # override. Baseline: the bundled value wins (config.md "[layers.air]"). ===
    monkeypatch.delenv("ZIJ_CONFIG_PATH", raising=False)
    monkeypatch.delenv("ZIJ_LAYERS__AIR__CADENCE_S", raising=False)

    cfg_bundle_only, secrets_bundle_only = load_config()
    air_bundle_only = cfg_bundle_only.layers["air"]
    assert air_bundle_only.cadence_s == BUNDLED_AIR_CADENCE_S
    assert air_bundle_only.cadence_floor_s == BUNDLED_AIR_CADENCE_FLOOR_S

    # === Stage B: a user config.toml overriding layers.air.cadence_s to 450
    # (path via ZIJ_CONFIG_PATH). Then: the user file wins over the bundle. ===
    user_toml_path = tmp_path / "user-config.toml"
    user_toml_path.write_text(
        f"""
[layers.air]
cadence_s = {USER_TOML_AIR_CADENCE_S}

# A secret-shaped key placed directly in a TOML layer (NFR5 probe below) --
# must never be read into `Secrets`, even though it sits in the legitimate
# [opensky] table and therefore *does* legitimately land in `AppConfig.opensky`.
[opensky]
client_id = "{TOML_SECRET_LEAK_CLIENT_ID}"
client_secret = "{TOML_SECRET_LEAK_CLIENT_SECRET}"
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("ZIJ_CONFIG_PATH", str(user_toml_path))

    cfg_user, secrets_user = load_config()
    air_user = cfg_user.layers["air"]
    assert air_user.cadence_s == USER_TOML_AIR_CADENCE_S, (
        "user config.toml (layer 3) must win over the bundled default (layer 2)"
    )
    # The untouched sibling key is untouched -- deep-merge, not table replacement.
    assert air_user.cadence_floor_s == BUNDLED_AIR_CADENCE_FLOOR_S

    # NFR5: the secret-shaped keys placed in the user TOML legitimately land
    # in AppConfig.opensky (it's a plain dict, not a secret)...
    assert cfg_user.opensky["client_id"] == TOML_SECRET_LEAK_CLIENT_ID
    assert cfg_user.opensky["client_secret"] == TOML_SECRET_LEAK_CLIENT_SECRET
    # ...but must NEVER be read into `Secrets` -- Secrets stays sourced from
    # env/.env only (NFR5), so it still carries the real env-provided values,
    # not the TOML ones.
    assert secrets_user.opensky_client_id == REAL_OPENSKY_CLIENT_ID
    assert secrets_user.opensky_client_secret == REAL_OPENSKY_CLIENT_SECRET
    assert secrets_user.opensky_client_id != TOML_SECRET_LEAK_CLIENT_ID
    assert secrets_user.opensky_client_secret != TOML_SECRET_LEAK_CLIENT_SECRET

    # === Stage C: additionally set a ZIJ_-prefixed env tunable overriding the
    # same key to 300. Then: the env var wins over the user file. ===
    monkeypatch.setenv("ZIJ_LAYERS__AIR__CADENCE_S", str(ENV_AIR_CADENCE_S))

    cfg_env, _secrets_env = load_config()
    air_env = cfg_env.layers["air"]
    assert air_env.cadence_s == ENV_AIR_CADENCE_S, (
        "ZIJ_-prefixed env tunable (layer 4) must win over the user "
        "config.toml (layer 3)"
    )
    assert air_env.cadence_floor_s == BUNDLED_AIR_CADENCE_FLOOR_S

    # === Stage D: additionally inject a DB config_override for the same key
    # (plus, simultaneously, a persisted active_region override) -- both
    # merged in the same call, proving the two reserved/non-reserved override
    # entries are handled independently. Then: the DB override wins over the
    # env var, and the active region is restored from the override. ===
    cfg_db, _secrets_db = load_config(
        overrides={
            "layers": {"air": {"cadence_s": DB_OVERRIDE_AIR_CADENCE_S}},
            "active_region": {"region_id": OTHER_REGION_ID},
        }
    )
    air_db = cfg_db.layers["air"]
    assert air_db.cadence_s == DB_OVERRIDE_AIR_CADENCE_S, (
        "DB config_override (layer 5, highest precedence) must win over the "
        "ZIJ_-prefixed env tunable (layer 4)"
    )
    assert air_db.cadence_floor_s == BUNDLED_AIR_CADENCE_FLOOR_S, (
        "overriding layers.air.cadence_s must not wipe the untouched sibling "
        "layers.air.cadence_floor_s (config-module.md deep-merge requirement)"
    )
    assert cfg_db.active_region_id == OTHER_REGION_ID, (
        "a persisted active_region config_override must be restored as the "
        "active region"
    )

    # === Stage E: no active_region override at all (overrides=None, matching
    # every pre-existing no-arg call site). Then: the configured default
    # region is used. ===
    monkeypatch.delenv("ZIJ_CONFIG_PATH", raising=False)
    monkeypatch.delenv("ZIJ_LAYERS__AIR__CADENCE_S", raising=False)
    cfg_no_override, _secrets_no_override = load_config()
    assert cfg_no_override.active_region_id == DEFAULT_REGION_ID

    # === Stage F: an active_region override naming a region_id that is not
    # one of the seven predefined regions. Then: falls back to the default,
    # exactly like the absent case above -- "invalid" and "absent" behave the
    # same way (config.md "Precedence" / ARCHITECTURE §4.1). ===
    cfg_invalid_override, _secrets_invalid_override = load_config(
        overrides={"active_region": {"region_id": UNKNOWN_REGION_ID}}
    )
    assert cfg_invalid_override.active_region_id == DEFAULT_REGION_ID

    # === Stage G: a valid active_region override in isolation (no other
    # overrides), to prove restore doesn't depend on also overriding a
    # tunable in the same call. ===
    cfg_valid_override, _secrets_valid_override = load_config(
        overrides={"active_region": {"region_id": OTHER_REGION_ID}}
    )
    assert cfg_valid_override.active_region_id == OTHER_REGION_ID
