# IDFA - Intelligent Digital Forensic Analysis

IDFA is a local-first Windows desktop application for digital forensic investigation. It runs a GUI plus a local forensic worker on one machine—no WSL, no Docker.

## Get started

```powershell
git lfs install
git clone --branch Desktop-Application https://github.com/sarvagnasrao/Intelligent-Digital-Forensic-AI-Assistant.git
cd Intelligent-Digital-Forensic-AI-Assistant
git lfs pull
.\SETUP_IDFA.bat
.\START_IDFA.bat
```

- Setup installs the Python environment, local services, and bundled models.
- On first launch, sign in as **admin** / **1234**, then change the password.
- Open or create a case, add evidence, run an examination, then use **AI Analysis** to ask questions about that case's evidence.

For an air-gapped machine, see [INSTALL_LOCAL.md](INSTALL_LOCAL.md).

## Exhibition demo (synthetic)

`tests/demo_case/` contains fully fictional teaching datasets and their builders.
**Aurora** (`aurora_fiction/`) is a 1.44 MB FAT12 image of invented notes, logs,
messages and a manifest. **Aurora expanded** (`aurora_expanded/`) is a 36-file
companion with many cross-file identifiers that exercises the entity and
relationship graph. Start with `tests/demo_case/README.md` and the dataset README
for the exact workflow and expected source claims.

Build and verify both images offline; none of these commands starts services or
calls a model:

```powershell
.venv\Scripts\python.exe tests\demo_case\aurora_fiction\build_image.py
.venv\Scripts\python.exe tests\demo_case\aurora_expanded\build_image.py
.venv\Scripts\python.exe -m pytest tests\test_aurora_fiction.py tests\test_aurora_expanded.py -q
```

Create the labelled cases from a terminal only when needed (each script run
refuses an existing case):

```powershell
.venv\Scripts\python.exe scripts\prepare_aurora_demo.py --create --confirm-gui-not-in-aurora --username admin
.venv\Scripts\python.exe scripts\prepare_aurora_demo.py --create --confirm-gui-not-in-aurora --username admin --dataset expanded
```

The demo works with keyword search and source review alone. Start with
`prism-drop-47@example.test`, `192.0.2.47`, `USB-AURORA-0042` and
`TX-AURORA-19`, then compare the sources; the expanded image adds more device,
phone and transfer identifiers for the entity and relationship views. The
prepared demo path does **not** run live AI, embeddings or a model; keep model
calls disabled if you build a case by hand. Graph edges and AI answers are not
proof of identity, delivery or culpability. The optional importer prompts
for an existing user's password, creates only `SYNTHETIC-AURORA-DEMO-2026`
(default) or `SYNTHETIC-AURORA-EXPANDED-2026` (`--dataset expanded`), stores a
reference to the bundled image, persists the Fast profile and
`llm_enabled=false` before dispatch, and never deletes/replaces cases or
changes provider configuration. It performs no indexing or model calls;
without `--create` it only prints usage, and it refuses to run without
`--confirm-gui-not-in-aurora`.

## Control services

```powershell
.\START_IDFA.bat      # Start Qdrant, worker, Ollama, and launch the GUI
.\START_IDFA.bat -Status   # Check service health
.\STOP_IDFA.bat            # Stop IDFA services
.\SETUP_IDFA.bat -Check    # Verify installation without changing anything
.\UNINSTALL_IDFA.bat       # Remove runtime; keeps case data unless -PurgeData
```

## AI providers

Local chat uses **Ollama** (`phi3:mini`) and embeddings use **all-minilm**; both work offline.

For cloud chat, open **Settings → AI & Models → Chat connections**, choose **Connect provider** (or **Edit provider…**), pick NVIDIA NIM, OpenAI, or a custom OpenAI-compatible endpoint, and enter its API key. Use the **Chat models** card to add or refresh model IDs and enable the ones AI Analysis may offer, then select **Save Settings**. Cloud chat requires per-case consent before evidence is sent. API keys are encrypted with DPAPI for your Windows account—never include a real key in a shared copy.

Long answers may hit the interactive output limit (default 2,048 tokens). IDFA marks incomplete answers. Raise the limit in **Settings → AI & Models** if needed; generation takes longer with local models.

## Configuration

Settings are stored in `%APPDATA%\IDFA\config.yaml` on first run. Case data, logs, database, and vector storage all live under one data folder you choose during setup.

## Default login

- Username: `admin`
- Password: `1234`

Change this immediately after first login.
