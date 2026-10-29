# Offline installation

IDFA runs without internet access once one machine has prepared a bundle. This
is how the demo laptops are prepared: no Python packages, no Qdrant download and
no model pull on the target machine.

## What the bundle contains

| Folder / file | Purpose |
|---|---|
| `packages\*.whl` | Every wheel in `requirements.txt` (GUI + worker + forensics) |
| `packages\offline-manifest.json` | Marker that a complete cache exists; `setup.ps1` prefers the cache when it is present |
| `packages\qdrant-x86_64-pc-windows-msvc.zip` | Official Qdrant Windows build, extracted to `tools\qdrant\` |
| `packages\ollama-windows-cpu.zip` | Portable Ollama runtime (CPU), extracted to `tools\ollama\` if Ollama is missing |
| `packages\python-3.12*-amd64.exe` | Python installer, run silently if no Python 3.12 is found |
| `models\ollama\manifests`, `models\ollama\blobs` | `phi3:mini` and `all-minilm` weights, copied into the Ollama model store (`OLLAMA_MODELS`, default `%USERPROFILE%\.ollama\models`) |

The whole folder is roughly 2.4 GiB: about 2.07 GiB of model weights and 350 MB
of wheels, Python and tools. `packages\offline-manifest.json` records the
expected counts and byte sizes. Setup stops with a `git lfs pull` instruction
if the LFS pointers are present but the bundle payload is missing.

The `Desktop-Application` branch stores this payload with Git LFS. Install Git
LFS before cloning; the clone downloads about 2.4 GiB and then setup can run
offline. GitHub Free includes 10 GiB of Git LFS storage and monthly bandwidth.
The largest Ollama layer is split into sub-2-GB parts to fit GitHub's per-file
limit and is reassembled directly into the user's Ollama model store by setup.

The bundle deliberately does **not** include `OllamaSetup.exe`. That installer is
1.6 GB because it ships CUDA and ROCm runtimes, and it downloads from a rate
limited GitHub mirror. The portable runtime in `packages\` is the same program
with only the CPU libraries: 24.5 MB zipped, 66 MB unpacked, no administrator
rights, no service registration. If a demo machine has an NVIDIA GPU and should
use it, install Ollama from <https://ollama.com/download/windows> before running
setup; `Find-Ollama` still prefers `tools\ollama\ollama.exe`, so delete that
folder first in that case.

## Building the bundle (once, on a connected machine)

```powershell
SETUP_IDFA.bat          # a working .venv and Ollama are prerequisites
powershell -ExecutionPolicy Bypass -File scripts\build_offline_bundle.ps1
```

The script:

1. downloads every wheel in `requirements.txt` for CPython 3.12 / `win_amd64`,
2. fetches the Qdrant Windows archive and the Python 3.12 installer into
   `packages\`, and packs the local Ollama installation into
   `packages\ollama-windows-cpu.zip` (program plus CPU libraries only),
3. copies the `phi3:mini` and `all-minilm` manifests and only the blobs they
   reference from the local Ollama store into `models\ollama\`,
4. writes `packages\offline-manifest.json`, which marks the cache as complete.

It reuses anything already present, so it can be re-run safely. Individual
stages can be skipped with `-SkipWheels`, `-SkipTools` or `-SkipModels`. To
rebuild the Ollama runtime after an Ollama upgrade, delete
`packages\ollama-windows-cpu.zip` first.

Model files are content-addressed, so copying `manifests` (and
`manifests-v2`) together with `blobs` is enough; Ollama picks them up without a
pull. If the store lives outside `%USERPROFILE%\.ollama\models`, the script uses
`OLLAMA_MODELS` when it is set.

## Installing on an offline machine

1. Copy the whole project folder (including `packages\` and `models\`).
2. Run `SETUP_IDFA.bat -Offline`.
3. Run `START_IDFA.bat`.

Setup prints a preflight report first, then unpacks Qdrant and the Ollama runtime
into `tools\`, imports the models into the local store, applies migrations and
creates **IDFA** / **Stop IDFA** shortcuts on the Desktop and in the Start Menu
(skip them with `-NoShortcuts`). `START_IDFA.bat` notices a missing or
half-installed `.venv` and offers to run setup itself, so the wrong order no
longer ends in an error message. `SETUP_IDFA.bat -Repair` deletes `.venv` and
reinstalls every package from the bundle if an install is damaged. Nothing is installed system-wide
and no administrator rights are needed (Python itself is the only exception: if
no 3.12 is present, setup runs the bundled installer per user).

`-Offline` refuses to reach the network. If a wheel or the Qdrant archive is
missing, setup stops with a message naming what is absent instead of hanging on a
download. Without `-Offline`, setup still prefers a complete cache and falls back
to the network when one is not available.

## Verifying

```powershell
SETUP_IDFA.bat -Check
START_IDFA.bat -Status
```

`-Status` prints one line per dependency and the data folder in use. A demo
machine is ready when the table shows:

```text
Worker       RUNNING  http://127.0.0.1:8000
                      pytsk3 ok, pyewf ok
Ollama       RUNNING  http://127.0.0.1:11434
Embedding    READY    all-minilm
Qdrant       RUNNING  http://127.0.0.1:6333
```

If Qdrant says `DOWN`, semantic search is unavailable but keyword search,
examination, findings and reports still work. If `Embedding` says `MISSING`, run
`ollama pull all-minilm` on a connected machine or re-import
`models\ollama`.

## Notes

- All wheels must be Windows x64 (`win_amd64`) and match the Python minor
  version (3.12). A cache built on another platform installs nothing and pip
  reports each unsatisfied requirement.
- `pytsk3` and `libewf-python` (which provides `pyewf`) are required for disk
  and E01 images. Both are pure Windows wheels, so they belong in the cache.
- The bundled Ollama runtime is CPU only. On a laptop without a discrete GPU it
  is also the fastest option, since a GPU that is not there costs load time. On
  a machine with a supported GPU, install the official Ollama build instead and
  remove `tools\ollama\`.
- The cache is only used as a package source. It is never modified at runtime,
  and removing `packages\` after setup does not affect a working installation.
