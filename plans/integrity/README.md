# Feature: integrity

`backend/integrity.py` — the FR9 plausibility flags (spec: `design/specs/integrity.md`,
D6/NFR3). A pure, deterministic post-adapter/pre-registry pass: marine-on-land spoof
detection (landmask point-in-polygon), implausible-kinematics detection (marine + air), and
the static per-layer caveat text served to the non-dismissible caveat panel. No I/O at flag
time; the landmask asset loads once at startup and fails fast if missing (NFR3 forbids
silently disabling a P0 honesty check).

Consolidated from triage's 4-slice proposal to 2 (founder decision 2026-07-06, 80/20).

| Slice | Slug | Behaviour | Blocked-by | Skeleton |
|---|---|---|---|---|
| 01 | flags | `Integrity.apply()` — landmask spoof-suspect + implausible kinematics; `scripts/fetch_landmask.py`; fail-fast load | — (v0 `models`) | |
| 02 | caveats | static `CAVEATS` per-domain text + active-flag counter for the caveats endpoint | — | |

Critical path: 01 and 02 are independent (either order). Both P0. Tests:
`backend/tests/test_integrity.py` (pytest unit; fixed landmask fixture + `Feature` examples).
