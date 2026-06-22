# Building a standalone `obtools` executable

Produces a single-file binary that runs on an acquisition PC **without Python
installed**, for portable USB use (see "Portable use" in the top-level README).

> **PyInstaller is not a cross-compiler.** A Windows `.exe` must be built on
> Windows, a macOS binary on macOS. Pick the option that matches the target.

## Option A — GitHub Actions (recommended; build Windows from a Mac)

You don't need a Windows machine. The `.github/workflows/build.yml` workflow
builds both Windows and macOS binaries on hosted runners.

1. Push this repo to GitHub.
2. Actions tab → **build-standalone** → **Run workflow** (or push a `vX.Y.Z` tag).
3. Download the `obtools-windows` artifact — it contains `obtools.exe` plus a
   `.obtools/` folder. Unzip both into the same folder on the USB stick.

## Option B — local build

**Windows** (PowerShell):

```powershell
powershell -ExecutionPolicy Bypass -File packaging\build.ps1
# → dist\obtools.exe  +  dist\.obtools\
```

**macOS / Linux**:

```bash
packaging/build.sh
# → dist/obtools  +  dist/.obtools/
```

Both install `.[secure]` (so the encrypted-credentials path is bundled) and
PyInstaller, then run `packaging/obtools.spec`.

## On the stick

Copy the binary **and** the `.obtools/` folder into the same directory on the
stick. The presence of `.obtools/` next to the executable switches obtools into
portable mode (config + session token stay on the stick). Then:

```
obtools cred set     # writes a passphrase-encrypted password into .obtools/
obtools connect      # verify
```

## Files

| File | Purpose |
|---|---|
| `launch.py` | Frozen-app entry point (`obtools.cli:main`) |
| `obtools.spec` | PyInstaller config — collects pybis data + obtools submodules |
| `build.ps1` / `build.sh` | One-shot local builds |
| `portable-readme.txt` | Dropped into `.obtools/` in the built artifact |
