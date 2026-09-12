# Standalone Service — Real-World Mileage Log (Phase 4D-A Stabilization)

**Purpose**: accumulate genuine, real-elapsed-time usage evidence before
Phase 4D-B (removing the embedded fallback) — not another controlled test
pass. See `docs/DESKTOP_SERVICE_MIGRATION.md` for the mechanism this is
gathering evidence about.

**Honesty note (read before adding an entry)**: an entry here must
correspond to a real work session that actually happened — an actual
elapsed period of ordinary use, not a scripted verification run (those
belong in `DESKTOP_SERVICE_MIGRATION.md`'s "Real-world verification"
section instead, and are already recorded there for Phases 4C/4D-A).
Never backfill or invent an entry for a session that didn't occur; a
sparse, honest log is worth more than a complete-looking fabricated one.
An assistant session that only *reads code, runs the test suite, or does
scripted process verification* has not generated mileage — mileage means
someone actually working through VS Code and/or the Desktop app with the
standalone service as the live backend, for real.

## Baseline (recorded at the start of this stabilization period)

```
2026-09-12
python -m pytest tests/ -q         349 passed (1 known pre-existing flaky
                                    test — ConnectionAbortedError on a
                                    Windows HTTP-server-teardown race,
                                    documented since Phase 4A, confirmed
                                    passing in isolation; not a new issue)
python tests/run_benchmark.py       58/58
python tests/run_runtime_benchmark.py  30/30
vscode-extension: npm run compile   clean
```

## One real, unscripted observation available at the start of this period

A Coach service (`pid 23860`, `port 47823`) has been continuously alive
and answering on this machine since `2026-09-11T23:15:05` — confirmed
still alive and responding as of this entry, i.e. **9+ hours of real,
unattended uptime with no observed crash or restart**. Its discovery file
has no `schema_version`/`service_version` field, meaning the process was
started from a build of this code that predates the Phase 4A/4C changes —
it is a real, independently-running process this stabilization effort did
not start and has not touched. This is genuine evidence (uptime stability
of *a* Coach service on this exact machine), but it does not by itself
tell us anything about the Desktop↔standalone handoff specifically, since
its origin/mode were not observed at startup.

## Entries

*(Add one entry per real work session below, oldest first. Use the format
from the spec: Date, Approximate session duration, Projects used, Backend
mode observed, VS Code used, Desktop used, Notifications observed,
Reconnects observed, Errors observed, Runtime anomalies, Outcome.)*

