"""Qt-free HTTP client for the desktop application to talk to a Coach
service — desktop-embedded or standalone, indistinguishable — as a client
rather than as the service's owner (Phase 4C, Step 3).

Mirrors vscode-extension/src/coachClient.ts's discovery+request logic
*conceptually* (Step 3: "share the protocol definition conceptually, not
implementation") — the same three-check discovery validation (file shape,
PID liveness, api_version compatibility), the same "re-read service.json
fresh on every call, never cache port/token" contract (Step 19), the same
one-exception-type-per-failure-mode shape — but written independently in
Python against `urllib` (stdlib, no new dependency, consistent with this
project's "no new dependencies unless necessary" rule stated in every
prior phase's docs). Nothing here is a port of the TypeScript.

Deliberately reuses `service/lifecycle.py`'s `read_discovery_file()`
rather than re-implementing discovery a third time (Step 6: "do NOT
create a second service-discovery mechanism" — this is the same reader
`app.py`'s startup check and the standalone entry point's own diagnostics
already use). This module adds only the HTTP request layer on top.

GUI thread safety (Step 4): every call here is a synchronous, blocking
`urllib.request.urlopen` — deliberately, not routed through a QThread.
This is safe specifically because every request targets `127.0.0.1` with a
short, bounded timeout: the common failure mode (nothing listening) fails
in about a millisecond (ECONNREFUSED), and the common success case (a real
loopback round trip) is sub-millisecond in practice — neither is
"noticeable" on the UI thread the way a real network call or a multi-
second local scan would be. `DEFAULT_TIMEOUT_SECONDS` bounds the pathological
case (port bound but unresponsive) so a call here can never hang the UI
indefinitely. If a future caller needs a call that can legitimately take
longer (e.g. an environment scan proxied through /approach), reuse the
existing `QThread` worker pattern already established in
`ui/env_worker.py`/`ui/usage_worker.py` rather than raising this module's
timeout — this module intentionally stays Qt-free so it can be reused from
either a worker thread or the main thread.
"""

from __future__ import annotations

import enum
import json
import urllib.error
import urllib.parse
import urllib.request

from . import lifecycle, models

# Bounds every plain read (health/status/session/environment) — see the
# module docstring for why staying short is safe here.
DEFAULT_TIMEOUT_SECONDS = 1.5
# Prompt analysis can run a real environment scan as part of /approach —
# same generous-but-bounded allowance vscode-extension/src/coachClient.ts
# gives these same three endpoints (PROMPT_REQUEST_TIMEOUT_MS there).
PROMPT_TIMEOUT_SECONDS = 10.0


class BackendMode(enum.Enum):
    """Phase 4D-A, Step 2: explicit backend states — replaces reasoning
    about `is_running()`/`is_available()` combinations ad hoc at each call
    site. Computed fresh on every read (see
    `CoachController.current_backend_mode()`), never stored/cached, so it
    always reflects the current reality rather than a snapshot from
    whenever the process started.
    """

    # This process is a pure client of a service it did not start —
    # standalone, or another desktop instance.
    STANDALONE = "standalone"
    # This process started and owns the embedded copy (the temporary
    # Step 9/4C compatibility path) because nothing else was reachable
    # when it looked.
    EMBEDDED_FALLBACK = "embedded_fallback"
    # No Coach service — this process's own or external — is reachable
    # right now.
    UNAVAILABLE = "unavailable"


class ServiceUnavailableError(Exception):
    """No usable Coach service right now — missing, stale, incompatible,
    unreachable, or timed out. Carries a specific diagnostic when
    `lifecycle.get_last_discovery_issue()` has one; a generic message
    otherwise (routine "nothing has run yet")."""


class InvalidRequestError(ValueError):
    """The service rejected a POST body as structurally invalid (400) —
    distinct from ServiceUnavailableError so a caller can show the real
    validation message instead of "service unavailable"."""


class CoachBackendClient:
    """One instance per `CoachController` (Phase 4C) is enough — this
    class holds no connection state of its own between calls (matching
    `CoachClient` in coachClient.ts, which re-reads `service.json` on
    every call for exactly the same reason: a service restart must be
    picked up on the very next call, never require anything to be
    recreated — Step 19)."""

    def __init__(self, timeout: float = DEFAULT_TIMEOUT_SECONDS):
        self.timeout = timeout

    def is_available(self) -> bool:
        """True only if a live, compatible Coach service is currently
        discoverable. Does not itself make an HTTP request — one small
        file read plus a PID-liveness check — so a caller can cheaply poll
        "should I even try" (e.g. once per refresh tick) without paying
        for a socket round trip every time. Mirrors the discovery half of
        vscode-extension's `readDiscovery()`."""
        return lifecycle.read_discovery_file() is not None

    def discovery_issue(self) -> str | None:
        """The specific reason `is_available()`/the last request call
        returned False/raised, when there is one — mirrors
        coachClient.ts's `getLastDiscoveryIssue()`."""
        return lifecycle.get_last_discovery_issue()

    def _discovery(self) -> dict:
        discovery = lifecycle.read_discovery_file()
        if discovery is None:
            raise ServiceUnavailableError(
                lifecycle.get_last_discovery_issue() or "Coach service is not running"
            )
        return discovery

    def _request(self, path: str, *, method: str = "GET", body: dict | None = None,
                  timeout: float | None = None) -> dict:
        discovery = self._discovery()
        url = f"http://127.0.0.1:{discovery['port']}{path}"
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("X-Coach-Token", str(discovery["token"]))
        if data is not None:
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=timeout or self.timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            try:
                payload = json.loads(raw.decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                payload = {}
            if exc.code == 400:
                detail = payload.get("detail") or payload.get("error") or "Coach service rejected this request."
                raise InvalidRequestError(detail) from exc
            raise ServiceUnavailableError(f"Coach service returned {exc.code}") from exc
        except (ValueError, UnicodeDecodeError) as exc:
            raise ServiceUnavailableError("Coach service returned invalid JSON") from exc
        except (urllib.error.URLError, OSError) as exc:
            raise ServiceUnavailableError(str(exc)) from exc

    # -- GET endpoints (Step 6/17: unchanged existing API) -----------------------
    def health(self) -> dict:
        return self._request("/api/v1/health")

    def status(self, project_root: str | None = None) -> dict:
        qs = f"?project_root={urllib.parse.quote(project_root)}" if project_root else ""
        return self._request(f"/api/v1/status{qs}")

    def session(self, cwd: str | None = None) -> dict:
        qs = f"?cwd={urllib.parse.quote(cwd)}" if cwd else ""
        return self._request(f"/api/v1/session{qs}")

    def environment(self, project_root: str | None = None) -> dict:
        qs = f"?project_root={urllib.parse.quote(project_root)}" if project_root else ""
        return self._request(f"/api/v1/environment{qs}")

    # -- POST endpoints (Phase 3/Step 14: analysis, not migrated onto this
    # path by any Desktop page in Phase 4C — exposed here so a later phase
    # can wire the Prompt Inspector/Approach Advisor through the same
    # backend VS Code uses, without adding a second client class) ---------------
    def analyze(self, prompt: str) -> dict:
        return self._request(
            "/api/v1/analyze", method="POST", body={"prompt": prompt}, timeout=PROMPT_TIMEOUT_SECONDS,
        )

    def suggest(self, prompt: str) -> dict:
        return self._request(
            "/api/v1/suggest", method="POST", body={"prompt": prompt}, timeout=PROMPT_TIMEOUT_SECONDS,
        )

    def approach(self, prompt: str, *, project_root: str | None = None, cwd: str | None = None) -> dict:
        body = {"prompt": prompt, "project_root": project_root, "cwd": cwd}
        return self._request(
            "/api/v1/approach", method="POST", body=body, timeout=PROMPT_TIMEOUT_SECONDS,
        )


# Re-exported so a caller only needs `from .client import ...` — API_VERSION
# lives in models.py (the single source of truth also used server-side).
API_VERSION = models.API_VERSION
