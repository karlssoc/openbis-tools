# Building a standalone `obtools` executable

Produces a single-file binary that runs on an acquisition PC **without Python
installed**, for portable USB use (see "Portable use" in the top-level README).

> **PyInstaller is not a cross-compiler.** A Windows `.exe` must be built on
> Windows, a macOS binary on macOS. Pick the option that matches the target.

## Option A — GitHub Release (recommended; no build, no GitHub login)

Pushing a `vX.Y.Z` tag runs the `build-standalone` workflow, which builds the
Windows and macOS binaries and publishes them as **Release assets**:

1. From the repo landing page, open **Releases** (right sidebar), pick the
   version, and download `obtools-windows-x64.zip` (or `obtools-macos-arm64.zip`).
2. Unzip onto the USB stick — each zip contains the binary plus a `.obtools/`
   folder, so it runs in portable mode immediately.

Release assets download anonymously over a stable URL — anyone can grab them
without a GitHub account, unlike Actions artifacts (which live under the Actions
tab, need a login, and expire). To cut a release, bump the version and push a tag:

```bash
git tag -a v0.2.3 -m "obtools 0.2.3" && git push origin v0.2.3
```

A manual **Actions → build-standalone → Run workflow** (no tag) still builds the
same zips but leaves them as Actions artifacts instead of a release.

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
