# Spec — v2 packaging, onboarding, and auto-update (desktop)

**Purpose.** The short governing spec [PRD §11](../docs/zij_prd.md) promised: "A separate
short spec governs auto-update and the mobile service-hosting decision (OQ3)." It covers
what v2 adds on top of the v1 monitor — a Tauri desktop bundle, first-run credential
onboarding (NFR5), auto-update, and the two P1 fast-follow features (presets UI, popup
depth) — and states plainly what v2 does **not** include.

**Scope decision (locked).** v2 is **desktop only** ([ADR-13](../docs/DECISIONS.md#adr-13--v2-desktop-only)):
Windows, macOS, Linux via Tauri. Mobile (Capacitor) and OQ3 are deferred to a later phase.
Auto-update uses Tauri's built-in updater against a signed GitHub Releases manifest
([ADR-14](../docs/DECISIONS.md#adr-14--auto-update)) — no update server.

Cross-refs: [PRD §7.4/§11/§12/§14](../docs/zij_prd.md), FR11, FR12, NFR1, NFR5, success
criterion #6; [ARCHITECTURE §4.4/§6](../docs/ARCHITECTURE.md), [STRUCTURE §3/§7](../docs/STRUCTURE.md),
[config.md](../contracts/config.md), [api.md](../contracts/api.md),
[feature-schema.md](../contracts/feature-schema.md), [frontend.md](frontend.md).

---

## 1. The v2 constraint: the shell boundary holds

The single most important property of v2 is that **the backend does not change**. Tauri
hosts the *unchanged* v1 backend and frontend. Restated from
[ARCHITECTURE §6](../docs/ARCHITECTURE.md#6-the-shell-boundary-d1-no-rewrite-promise) as a
v2 acceptance constraint:

- No backend module (`sources/*`, `models.py`, `store.py`, `scheduler.py`, `config.py`,
  `main.py`) learns it is inside a desktop shell. No `if tauri:` anywhere. If v2 needs a
  backend code change to work, that is a boundary violation and a design bug, not a v2 task.
- The frontend targets a **relative origin** (`/api/...`) exactly as in v1. This is what lets
  the same build serve a browser and a Tauri webview with no fork (see §2 for how the origin
  is made relative in the desktop case).
- Secrets never enter the bundle (NFR5, §3). The frozen backend executable contains **no keys**.
- v2-specific behavior lives entirely **above the HTTP line**: the Tauri Rust shell (process
  hosting, updater) and the frontend/onboarding UI. Nothing below it.

Because the boundary holds, everything in this spec is additive. Deleting the v2 shell leaves
a working v1 browser app.

---

## 2. Tauri desktop packaging

### 2.1 Bundle composition

A v2 desktop bundle is one Tauri application containing three parts:

1. **A frozen backend sidecar** — the `backend/` FastAPI app plus its bundled `config.toml`,
   frozen to a single self-contained executable (PyInstaller or equivalent; the exact freezer
   is a build-script detail, not a contract). It is registered as a Tauri **sidecar** (an
   external binary Tauri ships and spawns). It embeds no secrets and no user data.
2. **The built frontend** — `frontend/dist` from `vite build`, served by the sidecar's
   FastAPI via `StaticFiles` at `/`, exactly as ADR-7's prod mode already specifies. The
   frontend is **not** loaded from Tauri's own `tauri://localhost` asset origin; it is served
   by the sidecar so that the frontend's relative `/api` calls resolve against the sidecar.
3. **The Tauri Rust shell** — a thin webview host. On launch it (a) resolves credentials and
   spawns the sidecar (§3), (b) waits for the sidecar to be healthy, then (c) points its
   webview at the sidecar's loopback origin.

### 2.2 Process lifecycle (owned by the shell)

- **Launch:** the shell binds/reads a **loopback-only** port for the sidecar (`127.0.0.1`,
  never `0.0.0.0` — the service is never exposed off-machine), spawns the sidecar with that
  port and the resolved credentials in its environment (§3), and polls `GET /api/health`
  until ready or a timeout elapses. The webview loads `http://127.0.0.1:<port>/` only after
  health passes. The port may be a configured default with a fallback-to-ephemeral on
  conflict; the chosen port is handed to the webview by the shell. The backend reads its port
  from config/env as in any deployment — it does not learn *why* the port was chosen.
- **Shutdown:** on window close the shell terminates the sidecar via graceful signal, driving
  the backend's existing shutdown path ([ARCHITECTURE §4.4](../docs/ARCHITECTURE.md#44-graceful-shutdown):
  scheduler stops, stream closes, SQLite closed). The shell must not leave an orphaned sidecar.
- **Crash:** if the sidecar exits unexpectedly, the shell surfaces a failure state and offers
  a restart; it does not silently hang on a blank webview.

This keeps the sidecar an ordinary uvicorn process. The shell owns hosting; the backend owns
behavior. Neither reaches across.

### 2.3 Per-OS bundle targets (contract level)

| OS | Bundle target(s) | Distribution prerequisite |
|---|---|---|
| Windows | MSI and/or NSIS `.exe` installer | Authenticode signing before public release (else SmartScreen friction) |
| macOS | `.dmg` / `.app` | Apple code-signing **and notarization** — an unnotarized build is gatekeeper-blocked |
| Linux | AppImage (primary) and/or `.deb` | none required for the AppImage self-contained path |

These are the delivery formats, not build-script detail; the concrete `tauri.conf.json`
bundle config and CI matrix belong to the implementing sprint. Per-OS code-signing is a
**distribution** prerequisite (see OQ5, §7), not a prerequisite to building or running a
local dev bundle.

### 2.4 Icon assets

The Tauri bundle's app icons live in the root **`assets/`** directory
([STRUCTURE §3/§7](../docs/STRUCTURE.md)), **derived at packaging time from the brand source
SVGs in [`design/assets/`](../assets/)** (`zij_mark.svg`, [PRD §1.1](../docs/zij_prd.md)).
`design/assets/` remains the single source of truth for the brand; `assets/` holds only
generated exports and must never become a second source. Required per-platform derivatives:
`assets/icons/` with the Windows `.ico`, macOS `.icns`, and the PNG size set Tauri expects.
`tauri.conf.json` references `assets/icons/`, never `design/assets/` directly. The lockup's
text-to-outlines caveat (PRD §1.1, [DECISIONS design-phase open items](../docs/DECISIONS.md#design-phase-open-items))
applies to any public-facing lockup use, not to the app icon itself.

---

## 3. Credential onboarding — first-run flow (NFR5, PRD §7.4)

The app ships with **no embedded keys** (NFR5). An operator installing a desktop build needs
their own OpenSky API client and aisstream.io key (PRD §7.4, §7.1). v2 makes that a friendly
first-run step instead of a startup crash.

### 3.1 The design that keeps the boundary clean

The **shell resolves credentials before it spawns the sidecar** and passes them as process
environment variables. This is the key move: the backend's existing contract already reads
secrets from env only ([config.md §Secrets](../contracts/config.md)) and already **fails fast
if a secret required by an enabled layer is missing**. By resolving keys shell-side first, the
sidecar always starts in a known-good state — the backend never sees a "first run," it just
reads env like any deployment. No backend change, no `if first_run:`, boundary intact.

### 3.2 Flow

1. **On launch**, before spawning the sidecar, the shell checks the secret store (§3.3) for
   `OPENSKY_CLIENT_ID`, `OPENSKY_CLIENT_SECRET`, `AISSTREAM_API_KEY`
   ([config.md §Secrets](../contracts/config.md)).
2. **If all present:** inject them into the sidecar's environment and spawn. No prompt. This
   is the steady-state path after first run.
3. **If any are missing:** show the **first-run onboarding UI** before spawning. It:
   - Explains that Zij needs the operator's own free provider credentials and that none are
     bundled (why: NFR5, and OpenSky's non-commercial terms mean keys are per-operator, §12).
   - **Links directly to both providers' sign-up pages** (OpenSky account/API-client page;
     aisstream.io sign-up), per PRD §7.4.
   - Collects the OpenSky `client_id` + `client_secret` pair and the aisstream key.
   - Lets the operator **skip a provider**. Skipping a provider **disables that layer** for
     the session via config precedence (a disabled layer needs no secret, FR5) so the app
     still runs on the remaining layers ([FR10](../docs/zij_prd.md) degrade-to-remaining). Land
     needs no key and is always available.
4. The shell **writes** the entered secrets to the secret store (§3.3), then injects and
   spawns the sidecar. First fetch for a layer is gated on its key's presence by the existing
   startup contract — no separate gate is invented here.

### 3.3 Where secrets live

NFR5 permits "environment or an OS keychain." For a distributed desktop build the target store
is the **OS secret store** (Windows Credential Manager, macOS Keychain, Linux Secret Service).
A **fallback** for platforms without one available is a `0600`-mode file at
`platformdirs.user_config_dir("zij")` (the same user-config location config.md already uses),
never inside the bundle and never in the repo. Either way the shell reads the store and passes
values as **process env** to the sidecar; the backend's env-only loading is unchanged. The
exact keyring library is an implementation choice for the sprint (small open item), but the
contract is fixed: secret store or `0600` user-config file, injected as env, never bundled.

### 3.4 Missing vs. invalid keys

- **Missing** (operator skipped): that layer is disabled (§3.2 step 3); no error, the app runs.
- **Invalid** (wrong/expired key, unverifiable at entry — no free validation call is assumed):
  the layer starts enabled, the first fetch fails auth, and the existing error taxonomy maps
  it — OpenSky `AuthError` → the layer's `error` badge; aisstream auth-close → the marine
  stream's failure path ([ARCHITECTURE §5](../docs/ARCHITECTURE.md#5-failure-isolation-fr10-and-the-layer-status-state-machine),
  [feature-schema.md LayerStatus](../contracts/feature-schema.md)). No new mechanism. The
  operator can re-open onboarding from an app menu to correct a key; corrected keys are
  written to the store and take effect on the next sidecar restart.

---

## 4. Auto-update ([ADR-14](../docs/DECISIONS.md#adr-14--auto-update))

Tauri's built-in updater, pulling a signed static manifest and bundles from GitHub Releases.
No update server runs — the mechanism is consistent with success-criterion #6 (no hosted/cloud
dependency in the default deployment).

### 4.1 Manifest and hosting

- The manifest is a **static JSON** (Tauri updater format: version, per-platform bundle URLs,
  per-bundle signatures, optional release notes) hosted as a **GitHub Releases** asset at a
  **stable URL** (e.g. a `latest`-tagged release asset). `tauri.conf.json`'s updater endpoint
  points at that URL. Bundles themselves are ordinary GitHub Release assets.
- Hosting is therefore static file serving only. Nothing to operate, nothing to pay for.

### 4.2 Signature verification

- Updates are signed with **Tauri's updater keypair**. The **public key is embedded in the
  app** (`tauri.conf.json`). The **private key is an operator/release secret** — held in the
  release/CI environment, used to sign each bundle at release time, and never committed and
  never placed in any bundle (same discipline as NFR5).
- The updater **verifies the signature before install**. An unsigned, tampered, or
  wrong-key bundle is rejected and not installed. This is what makes static hosting safe.

### 4.3 Cadence and consent

- **Check on launch** against the manifest URL. A manual "Check for updates" menu action may
  also trigger a check.
- On finding a newer, correctly-signed version, **prompt the user**. Install (and the
  app relaunch it entails) happens **only on user confirmation** — never a silent
  auto-install. Release notes from the manifest are shown in the prompt where present.

### 4.4 Offline and failure behavior

- **No network / manifest unreachable:** the check is a **silent no-op**. The app runs
  normally on its installed version. An update check never blocks or delays launch.
- **Download or signature-verification failure:** the update aborts, the running (already
  installed) version is untouched, and the failure is surfaced non-fatally (the operator can
  retry later). A failed update never leaves the app in a broken partial state.

---

## 5. P1 features in v2 scope (fast-follow)

Both are P1 ([FR11](../docs/zij_prd.md)) and land in v2 alongside packaging. Both are
**frontend surfacings of surfaces that already exist** — no new backend endpoints, no new
schema fields. Specified at behavioral-contract level so a later sprint can slice them.

### 5.1 Presets UI (FR11)

The `config_presets` table and the `/api/presets` endpoints already exist
([api.md §presets](../contracts/api.md), [storage.md](../contracts/storage.md)) and `POST /api/regions/activate`
already accepts `save_as_preset` ([frontend.md §6](frontend.md)). v2 surfaces them in
`ui/regionSelector.ts`:

- Saving the current custom bbox as a **named preset** → `POST /api/presets {name, bbox}`
  (or the `save_as_preset` flag on activate); `409` on a duplicate name is shown inline.
- Listing saved presets in the region dropdown **alongside the predefined regions**
  (`GET /api/regions` already returns predefined + saved presets, [api.md](../contracts/api.md)).
- Deleting a preset → `DELETE /api/presets/{id}`.

Acceptance: an operator can save, re-select, and delete a named region without editing config;
presets persist across restart (they are in SQLite, not memory).

### 5.2 Popup inspection depth (FR11)

The schema already carries `raw_payload` (in-memory only) and the inspection endpoint already
exists (`GET /api/features/{domain}/{source_id}/raw`,
[feature-schema.md raw_payload](../contracts/feature-schema.md#raw_payload-handling),
[api.md](../contracts/api.md)). v2 surfaces it: a **raw-payload toggle** in the feature popup
that fetches and displays the untouched upstream record on demand. No new fields — this is
display depth over data the schema already defines.

Acceptance: a popup exposes a "raw" toggle that renders the source record verbatim; the raw
payload is fetched only on demand and never rides normal snapshot serialization (the
[shell-boundary](../docs/ARCHITECTURE.md#6-the-shell-boundary-d1-no-rewrite-promise) rule on
`raw_payload` still holds).

---

## 6. Non-goals for v2 (explicit)

Each is out of scope for a stated reason. Adding any of them back is a scope change requiring
a removal or a phase extension ([PRD §11](../docs/zij_prd.md) scope rule).

- **Mobile / Capacitor builds, on-device mobile Python, anything OQ3.** Deferred to a later
  phase ([ADR-13](../docs/DECISIONS.md#adr-13--v2-desktop-only)). v2 does not design Capacitor
  internals or the on-device-vs-hosted backend split.
- **An auto-update server / service.** We use GitHub Releases **static** hosting
  ([ADR-14](../docs/DECISIONS.md#adr-14--auto-update)); running an update endpoint would
  violate success-criterion #6.
- **Monetization / commercial distribution.** OpenSky's API is non-commercial
  ([PRD §12](../docs/zij_prd.md)); distributing a free installer is compatible, monetizing it
  is not. Recorded so a distribution decision does not trip over it.
- **New backend endpoints for the P1 features.** Presets and raw-payload endpoints already
  exist ([api.md](../contracts/api.md)); v2 is UI surfacing only.
- **Any backend behavior change.** By construction (§1) — if v2 needs one, it is a bug.
- **The unchanged §4 PRD non-goals** (history/replay, analytics, alerting, multi-tenancy)
  remain out of scope in v2 as in every phase.

---

## 7. Open questions carried forward

| ID | Status in v2 | Note |
|----|---|---|
| **OQ3** — mobile architecture (on-device Python vs. hosted thin client) | **Resolved-by-deferral for v2.** v2 targets desktop; mobile architecture is out of scope for v2 and remains open for a later phase ([ADR-13](../docs/DECISIONS.md#adr-13--v2-desktop-only)). | Not designed here. Whenever it is taken up, the [D1 boundary](../docs/ARCHITECTURE.md#6-the-shell-boundary-d1-no-rewrite-promise) means it is a shell-and-hosting decision, not a backend rewrite. |
| **OQ5** — name/trademark clearance for "Zij" | **Open. Not resolved here.** | Blocks public **distribution** (signed/notarized installers to the public), **not** development or a local dev bundle ([PRD §14/§1.1](../docs/zij_prd.md)). The §2.3 per-OS code-signing prerequisites and this clearance together gate the first public release. |

---

## 8. Acceptance criteria (v2-owned)

- [ ] **Shell boundary (§1)** — the v2 bundle runs the unchanged v1 `backend/`; no backend
      module contains shell-specific code; deleting the shell leaves a working browser app.
- [ ] **Packaging (§2)** — a Tauri bundle spawns the frozen backend sidecar on a loopback port,
      waits for `GET /api/health`, then loads the webview at the sidecar origin so `/api` calls
      resolve; window close terminates the sidecar via the graceful shutdown path.
- [ ] **Per-OS targets (§2.3)** — Windows, macOS, and Linux bundles are produced; app icons in
      root `assets/icons/` are derived from `design/assets/` sources.
- [ ] **Onboarding (§3)** — with no stored keys, first launch shows the credential prompt
      linking both providers' sign-up pages, collects and stores keys in the OS secret store
      (or a `0600` user-config file), and spawns the sidecar with them as env; keys are never
      bundled. Skipping a provider disables its layer; the app still runs.
- [ ] **Missing/invalid keys (§3.4)** — a skipped provider disables its layer (no error); an
      invalid key surfaces as that layer's `error`/auth status via the existing taxonomy, never
      crashing the app.
- [ ] **Auto-update (§4)** — on launch the app checks a static GitHub Releases manifest,
      verifies the bundle signature against the embedded public key, prompts on a newer signed
      version, and installs only on user confirmation.
- [ ] **Update offline/failure (§4.4)** — no network is a silent no-op; a failed
      download/verify aborts without touching the installed version; launch is never blocked.
- [ ] **Presets UI (§5.1)** — save/list/delete named presets via existing `/api/presets`;
      presets persist across restart.
- [ ] **Popup depth (§5.2)** — a popup raw-payload toggle fetches
      `GET /api/features/{domain}/{source_id}/raw` on demand.
- [ ] **Non-goals (§6)** — no mobile/Capacitor code, no update server, no new backend
      endpoints, no monetization path shipped in v2.
