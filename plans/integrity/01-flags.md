# Slice 01: Integrity flags — landmask spoof-suspect + implausible kinematics

- **Feature:** integrity
- **Slice slug:** flags
- **Issue:** #43
- **Branch:** feat/integrity/01-flags
- **Project directory:** `backend`
- **Status:** ▹ planned (sprint v1)
- **Walking skeleton?** no

> **Zij roles (DEC-1):** **test-author** commits the outer acceptance test **red** before
> implementation; **implementer** drives inner cycles and may not edit the outer test or
> `design/`; **test-author** confirms green. Spec wrong mid-build ⇒ `spec-drift` issue.

## Goal — the minimum testable behaviour

Implement `integrity.py` `Integrity` with a pure `apply(features, prev) -> features` that
appends `integrity_flags`, plus `scripts/fetch_landmask.py` (one-time Natural Earth 10m land
polygon fetch). On construction, load the landmask from `[integrity].landmask_path` (empty →
the platformdirs data-dir default) into a shapely `STRtree`; **fail fast with a named error
if the asset is missing or corrupt** (FR9/NFR3 forbid shipping the spoof check silently
disabled). Two cheap flags, computed at flag time with no I/O:

- **Landmask (marine only):** `Point(lon, lat)` tested against the `STRtree` — if any land
  polygon `contains` it → append `SPOOF_SUSPECT_ON_LAND` (a vessel on land is a jamming/spoof
  ghost). Air-on-land and land features are never flagged.
- **Implausible kinematics (marine + air):** with `prev[source_id]` and both timestamps
  present, `implied_kn = haversine(prev, curr)/1852 ÷ (dt/3600)`; guard `dt <= 0` → skip (no
  div-by-zero). Marine `> max_speed_kn_marine` (120) or air `> max_speed_kn_air` (990) →
  append `IMPLAUSIBLE_KINEMATICS`. Uses positional implied speed, not broadcast velocity.

## INVEST check

- **Independent:** pure function over v0 `Feature`s + a `prev` map; no scheduler/store/API needed.
- **Valuable:** the FR9 honesty machinery — the product's core "position honesty" promise (NFR3).
- **Small:** one class, an STRtree load, two flag functions, a haversine helper, one fetch script.
- **Testable:** pytest unit against a fixed small landmask fixture and hand-built `Feature` pairs.

## Acceptance criterion (outer loop — the failing test)

```gherkin
Given an Integrity loaded with a known landmask and configured thresholds
When  apply() runs over a marine feature whose lat/lon falls inside a land polygon
Then  that feature carries SPOOF_SUSPECT_ON_LAND
When  a consecutive-report pair implies >120 kn (marine) or >990 kn (air)
Then  the current feature carries IMPLAUSIBLE_KINEMATICS
And   a same-timestamp pair (dt<=0) is skipped without error (no div-by-zero, no flag)
And   an air feature over land is NOT flagged spoof-suspect
```

- **Boundary:** `Integrity.apply(features, prev)` in isolation (pure); startup asset-load path.
- **test type:** pytest unit; **file:** `backend/tests/test_integrity.py`.

## Inner loop — initial unit test list

- [ ] STRtree query + `contains` flags a known on-land marine coordinate; an at-sea one is clean.
- [ ] Haversine implied-speed math matches a hand-computed value for a known pair.
- [ ] `dt <= 0` (same/out-of-order timestamp) is skipped — no exception, no flag.
- [ ] Marine threshold 120 kn vs air threshold 990 kn applied per `domain`.
- [ ] Null `timestamp_source` → kinematics skipped for that feature, but landmask still applies.
- [ ] Purity: identical `(features, prev)` inputs always yield identical flags.
- [ ] Missing/corrupt landmask asset at construction raises a named, fail-fast error.

## Out of scope (deferred)

- Static caveat text + active-flag counting (slice 02).
- Wiring `apply` into the scheduler write path (scheduler/02); `prev` map assembly (adapter/scheduler own it).
- NFR4 performance target (<100 ms for 1000 vessels via prepared STRtree) — a measured, non-blocking follow-up check, not this slice's gate.

## Definition of done

- [ ] Outer test authored **RED before implementation** (DEC-1), seen red, now GREEN.
- [ ] Inner units covered; `uv run pytest`, `uv run ruff` green; refactor on green.
- [ ] Evidence: pytest transcript (spoof + kinematics + guard assertions). CI green; PR via `safe-pr`.

## Status / progress log

- 2026-07-06 planned (sprint v1). Blocked-by: none new (v0 `models`).
