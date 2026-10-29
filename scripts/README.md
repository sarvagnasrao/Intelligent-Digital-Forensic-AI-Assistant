# Scripts

The three root BAT files are the normal entry points. Everything they do runs
on native Windows: no WSL, no Docker.

| Root file | Purpose |
|-----------|---------|
| `SETUP_IDFA.bat` | Preflight, then create `.venv`, install packages (local cache or network), install the bundled Qdrant, check Ollama and both models, run migrations, verify the install and create shortcuts |
| `START_IDFA.bat` | Start Ollama, Qdrant and the forensic worker, print a status table, then launch the GUI. Offers to run setup when `.venv` is missing or incomplete |
| `STOP_IDFA.bat` | Stop the worker and Qdrant (Ollama is shared, so it stays running unless asked) |
| `UNINSTALL_IDFA.bat` | Remove the environment, `tools\`, caches and shortcuts; keeps case data unless `-PurgeData` |

## Flags

`SETUP_IDFA.bat`:

| Flag | Effect |
|------|--------|
| `-Check` | Preflight and doctor only: verify the computer, modules, Qdrant, Ollama, models, shortcuts and config without changing anything |
| `-Repair` | Delete `.venv` and reinstall every Python package (asks first) |
| `-Offline` | Refuse to use the network; fail if `packages\` cannot satisfy `requirements.txt` |
| `-SkipModels` | Do not check or pull the Ollama models |
| `-SkipQdrant` | Do not download Qdrant (semantic search stays unavailable) |
| `-NoShortcuts` | Do not create Desktop/Start Menu shortcuts |
| `-Yes` | Accept confirmations (used with `-Repair`) |

The Desktop-Application branch includes `packages\` and `models\` through Git
LFS. Install Git LFS before cloning (`git lfs install`); for an existing clone,
run `git lfs pull`. Setup checks the bundle byte counts and stops with this
instruction if Git LFS returned pointer files instead of the actual payload.

`START_IDFA.bat`:

| Flag | Effect |
|------|--------|
| `-NoGui` | Start the services only |
| `-Status` | Print the status table and exit |
| `-Yes` | Run setup automatically when the environment is missing |
| `-NoSetup` | Never run setup; print what to do instead |

`STOP_IDFA.bat`:

| Flag | Effect |
|------|--------|
| `-IncludeOllama` | Also stop Ollama, which other applications may be using |

`UNINSTALL_IDFA.bat`:

| Flag | Effect |
|------|--------|
| `-DryRun` | Show what would be removed without changing anything |
| `-Yes` | Do not ask for confirmation |
| `-PurgeData` | Also delete the case database/evidence folder and `%APPDATA%\IDFA\config.yaml` (asks you to type `DELETE`) |
| `-RemoveModels` | Also delete `phi3:mini` and `all-minilm` from the Ollama store, keeping blobs other models use |
| `-RemoveBundle` | Also delete `packages\` and `models\` |

```powershell
SETUP_IDFA.bat -Check
SETUP_IDFA.bat -Offline
SETUP_IDFA.bat -Repair
START_IDFA.bat -NoGui
START_IDFA.bat -Status
STOP_IDFA.bat -IncludeOllama
UNINSTALL_IDFA.bat -DryRun
UNINSTALL_IDFA.bat -PurgeData
```

## Helper scripts

| File | Purpose |
|------|---------|
| `setup.ps1` | Implementation of `SETUP_IDFA.bat`, including the preflight report |
| `start_idfa.ps1` | Implementation of `START_IDFA.bat`, including the setup prompt |
| `stop_idfa.ps1` | Implementation of `STOP_IDFA.bat` |
| `uninstall.ps1` | Implementation of `UNINSTALL_IDFA.bat`; stops services, removes runtime files and optionally data/models/bundle |
| `install_shortcuts.ps1` | Creates or removes the per-user Desktop/Start Menu shortcuts (`-Remove` to delete them) |
| `_common.ps1` | Shared paths, HTTP probes, disk/port checks, bundle inspection and PID-file helpers; dot-sourced by the launchers |
| `config_dump.py` | Prints the resolved configuration as JSON, so the launchers and the GUI always agree on paths |
| `install_from_local.ps1` | Installs wheels from `packages\` with `--no-index` (used by setup when a cache exists) |
| `build_offline_bundle.ps1` | Builds the offline bundle: wheels, Qdrant archive, portable Ollama runtime and model weights (see `INSTALL_LOCAL.md`) |

`legacy\` keeps the old WSL scripts (`setup_wsl2_worker.bat`,
`start_worker.sh`) for reference only. Nothing calls them.

## Behaviour worth knowing

- **PID files** live in `%LOCALAPPDATA%\IDFA\run` (`worker.pid`, `qdrant.pid`).
  Only processes recorded there, or processes listening on the configured port
  whose command line points at `worker\main.py` / `qdrant.exe`, are stopped. A
  port held by something else is reported and left alone.
- **Logs** go to `<data_dir>\logs` (`worker.log`, `worker.err.log`,
  `qdrant.log`, `qdrant.err.log`). The data folder itself is chosen on first
  GUI launch and can be changed in **Settings → Data & Storage**.
- **Configuration** is read through `app.config` via `config_dump.py`, never
  parsed by hand, so `localhost` and the retired
  `sentence-transformers/all-MiniLM-L6-v2` id are normalised exactly like the
  GUI does.
- **Database**: `alembic upgrade head` runs first. If the database has no
  usable revision history, setup calls `init_db()`, which creates the schema and
  reconciles `alembic_version` with the actual tables, then retries.
- **Qdrant** is downloaded once into `tools\qdrant\` from the official Windows
  release. SQLite data is not touched by STOP; it only stops processes.
