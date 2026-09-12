# Packaging

Builds a standalone Windows distributable of Claude Code Coach — no Python
install required to run it.

```powershell
.\packaging\build.ps1
```

Produces:

```
dist\ClaudeCodeCoach\                    <- run ClaudeCodeCoach.exe from here
    ClaudeCodeCoach.exe
    _internal\                           (bundled Python + PySide6/Qt)
    hook_receiver\
        hook_receiver.exe                <- see "Why two executables" below
        _internal\
    README.md
dist\ClaudeCodeCoach-v0.3.0-win64.zip    <- attach this to a GitHub Release
```

## What's in this folder

| File | Purpose |
|---|---|
| `build.ps1` | The actual build — installs PyInstaller/Pillow if missing, builds both executables, merges them, zips the result. |
| `hook_receiver_entry.py` | Thin PyInstaller entry point for the standalone receiver build (see below). |
| `version_info.txt` | Windows file-properties resource (product name, version, company) embedded in `ClaudeCodeCoach.exe`. |
| `assets/icon.ico` | Multi-resolution icon generated once from `vscode-extension/icon.png` — same artwork as the VS Code extension, committed so a build doesn't need Pillow unless the source art actually changes. |
| `build/` | PyInstaller's own work directories and generated `.spec` files — gitignored, safe to delete, regenerated on every build. |

## Why two executables

`claude_code_coach/runtime/hook_installer.py` writes a hook command into
the user's real Claude Code `settings.json`. Running from source, that
command is `sys.executable` (the Python interpreter) plus this repo's
`hook_receiver.py` (a script that interpreter runs). Freeze that into a
*single* exe and both halves break:

- `sys.executable` in a frozen app is the app's own GUI exe, not a Python
  interpreter — Claude Code would try to hand it a script path as if it
  were `python.exe`, which it isn't.
- Under PyInstaller's one-file mode especially, a bundled module's own
  `__file__` resolves inside a temporary extraction directory that gets
  deleted the moment the process exits — fatal for a hook Claude Code
  invokes long after the app has closed.

So the receiver ships as its own small, separate executable
(`hook_receiver.exe`) at a stable, persistent path next to the main app.
`hook_installer.hook_command()` is the one place that decision is made —
when `sys.frozen` is true it points straight at that companion exe with no
interpreter involved; running from source it's unchanged from before. See
that function's docstring, and `tests/test_runtime.py::TestHookInstallerFrozen`,
which exercises this without needing an actual frozen build.

## Distributing a release

1. Run `.\packaging\build.ps1`.
2. Smoke-test `dist\ClaudeCodeCoach\ClaudeCodeCoach.exe` actually launches.
3. On GitHub: Releases -> Draft a new release -> upload
   `dist\ClaudeCodeCoach-v0.3.0-win64.zip` as a release asset.

The zip is the only thing meant to leave this machine — `dist/` and
`packaging/build/` are both gitignored; nothing here gets committed except
the build scripts and the small `assets/icon.ico`.

## Bundling the Coach service into the VS Code extension

```powershell
.\packaging\build_vscode_service.ps1
```

A third, separate PyInstaller build (`service_entry.py` -> `CoachService.exe`,
same onedir approach) placed at
`vscode-extension\bundled\win32-x64\CoachService\`, which
`vscode-extension\src\serviceLauncher.ts` spawns automatically when it
activates and no Coach service (standalone or desktop) is already
reachable — so an ordinary Marketplace install never needs Python. This is
the *service* only (`claude_code_coach/service/__main__.py`, zero PySide6
import), not the desktop GUI — about 15 MB on disk versus the desktop
build's ~116 MB, entirely because it never pulls in Qt.

Run this before `npx vsce package` inside `vscode-extension/` — the .vsix
step picks up whatever is already sitting in `bundled/`, it doesn't build
it. `vscode-extension/bundled/` is gitignored; only the two build scripts
and their small shared `assets/icon.ico` are.

See `serviceLauncher.ts`'s module docstring for the auto-start design (why
it never connects on a bare open port, how multiple VS Code windows racing
at startup are handled, and why a spawned service is deliberately never
killed when the window that started it closes).
