"""Session-wide test hermeticity fixtures for backend/tests.

Root cause (CI investigation, issue #17): `backend.config.load_config()`
raises `MissingSecretError` when the enabled `air` layer's
`OPENSKY_CLIENT_ID`/`OPENSKY_CLIENT_SECRET` secrets are absent from the
environment. Locally, the checked-in (gitignored) `D:\\Zij\\.env` supplies
real values via `pydantic_settings`' `env_file` fallback -- but CI has no
`.env` and `ci.yml` injects no OpenSky secrets, so any test that calls
`load_config()` without first monkeypatching those two vars fails in CI even
though it passes locally (`test_overpass.py::test_fetch_hormuz_land` and
`test_api.py::test_unmatched_non_api_path_does_not_get_the_api_error_envelope`
were both found calling `load_config()` this way).

The fixture below makes the whole suite hermetic: it sets obviously-fake
`OPENSKY_CLIENT_ID`/`OPENSKY_CLIENT_SECRET` baseline values in the process
environment once, for the whole session, before any test runs --
independent of whether a real `.env` is present on disk. Individual tests
that need specific secret values (including empty-string values, to prove
the fail-fast path) still win: pytest's per-test `monkeypatch` fixture is
function-scoped, so `monkeypatch.setenv(...)`/`monkeypatch.delenv(...)`
inside a test is always applied after this session-scoped fixture has
already run, overriding the baseline for the duration of that test, and its
teardown reverts back to this baseline afterwards (not to whatever the real
ambient/`.env` value would have been) -- so tests are isolated from each
other's secret values too.

`pydantic_settings.BaseSettings(env_file=".env")` (`backend.config.Secrets`)
gives actual process env vars priority over the `.env` file's contents, so
setting these here in `os.environ` -- whether or not a real `.env` exists on
disk -- is sufficient to satisfy `_check_required_secrets` for any test that
does not override them itself. This mirrors the pattern already used
per-test throughout `test_config.py`/`test_config_acceptance.py`/
`test_api.py`/`test_opensky.py` (explicit `monkeypatch.setenv` before calling
`load_config()`), just supplying a session-wide default so tests that forgot
to (or don't otherwise care about the specific values) still get a hermetic,
non-empty pair.
"""

from collections.abc import Iterator

import pytest

# Obviously-fake placeholders -- never real credentials. Any non-empty string
# satisfies `_check_required_secrets` (backend/config.py); the specific value
# is irrelevant to every test that relies on this baseline (they only assert
# the secrets are *present*, not what they equal -- tests that care about the
# literal value always set their own via function-scoped `monkeypatch`,
# which wins over this baseline; see module docstring above).
BASELINE_OPENSKY_CLIENT_ID = "test-opensky-client-id"
BASELINE_OPENSKY_CLIENT_SECRET = "test-opensky-client-secret"


@pytest.fixture(scope="session", autouse=True)
def _hermetic_opensky_secrets() -> Iterator[None]:
    """Autouse, session-scoped: guarantees `OPENSKY_CLIENT_ID`/
    `OPENSKY_CLIENT_SECRET` are non-empty for the whole test session, so
    `load_config()` never fails fast with `MissingSecretError` purely for
    lack of an ambient `.env`/shell secret (CI has neither). Uses
    `pytest.MonkeyPatch.context()` (the pytest-documented pattern for
    session-scoped monkeypatching) rather than the function-scoped
    `monkeypatch` fixture, so this can be `autouse` at session scope; a
    function-scoped `monkeypatch.setenv(...)` inside any individual test
    still overrides these values for that test only, per pytest's fixture
    teardown ordering.
    """
    with pytest.MonkeyPatch.context() as session_mp:
        session_mp.setenv("OPENSKY_CLIENT_ID", BASELINE_OPENSKY_CLIENT_ID)
        session_mp.setenv("OPENSKY_CLIENT_SECRET", BASELINE_OPENSKY_CLIENT_SECRET)
        yield
