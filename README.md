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

For cloud chat, open **Settings → AI & Models → Providers**, connect a provider (NVIDIA NIM, OpenAI, or custom OpenAI-compatible endpoint), enter its API key, then go to **Models** to enable individual models and save Settings. Cloud chat requires per-case consent before evidence is sent. API keys are encrypted with DPAPI for your Windows account—never include a real key in a shared copy.

Long answers may hit the interactive output limit (default 2,048 tokens). IDFA marks incomplete answers. Raise the limit in **Settings → AI & Models** if needed; generation takes longer with local models.

## Configuration

Settings are stored in `%APPDATA%\IDFA\config.yaml` on first run. Case data, logs, database, and vector storage all live under one data folder you choose during setup.

## Default login

- Username: `admin`
- Password: `1234`

Change this immediately after first login.
