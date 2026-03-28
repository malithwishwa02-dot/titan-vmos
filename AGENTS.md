# AGENTS.md - Titan V13

This guide provides essential knowledge for AI agents to be productive in the Titan V13 codebase.

## Architecture Overview

The Titan V13 platform is a sophisticated Android virtualization system. Its architecture consists of three main components:

1.  **FastAPI Backend (`server/`)**: A Python-based API that orchestrates the entire system. It manages device lifecycle, stealth patching, data injection, and more. Key file: `server/titan_api.py`.
2.  **Cuttlefish Android VMs**: KVM-based virtual machines that provide high-fidelity Android environments. Managed by `core/device_manager.py`.
3.  **Web Console (`console/`)**: An Alpine.js and Tailwind CSS single-page application for monitoring and controlling the device fleet.

The system is designed to run on a Linux (Ubuntu) host, typically on a Hostinger KVM VPS.

## Core Modules & Concepts

-   **`core/device_manager.py`**: The heart of the system, responsible for creating, configuring, and managing Cuttlefish VMs.
-   **`core/anomaly_patcher.py`**: A critical 26-phase module that applies stealth patches to VMs to evade detection. It masks virtualization artifacts and forges a realistic device identity.
-   **`core/android_profile_forge.py`**: The "Genesis Forge" creates realistic, aged user profiles with circadian-weighted activity patterns.
-   **`core/profile_injector.py`**: Injects the forged profiles into the Android VMs using a robust 8-phase protocol. It uses SQLite batch injection for performance.
-   **`core/device_agent.py`**: An AI agent that uses an LLM (Ollama) to perform tasks on the device using a "See-Think-Act" loop.

## Development Workflow

-   **Testing**: Run tests using `python -m pytest tests/ -x`.
-   **Syntax Check**: `python -c "import ast; ast.parse(open('file.py').read())"`
-   **Deployment**: The project is deployed to a VPS using `scp` and a deployment script. See the `Quick Start` section in `README.md`.
-   **PYTHONPATH**: The `PYTHONPATH` is `core:server`, so modules in these directories can be imported directly.

## Project Conventions

-   **ADB Operations**: Always use `adb_utils.adb_shell()` or `adb_with_retry()` for executing ADB commands. Never use raw `subprocess`.
-   **Root Access**: Use `ensure_adb_root(target)` before any privileged ADB operations.
-   **Logging**: New core modules must use `json_logger` for structured logging.
-   **API Schemas**: Use Pydantic models from `core/models.py` for all API request and response schemas.
-   **API Routers**: New API routers should be placed in `server/routers/` and registered in `server/titan_api.py`.
-   **SELinux**: After pushing files to the device, always run `restorecon -R` to preserve SELinux contexts.

## Stealth & Evasion

-   The `anomaly_patcher.py` is central to the platform's stealth capabilities. It patches over 156 detection vectors.
-   The patcher runs in multiple phases, covering device identity, telephony, anti-emulator checks, and more.
-   **Play Integrity**: The platform can pass Basic and Device Integrity checks. Strong Integrity is hardware-blocked and cannot be passed in a virtual environment.

## Data Forging & Injection

-   The Genesis Forge
- (`android_profile_forge.py`) creates realistic user data, including contacts, call logs, and SMS messages.
-   Activity is weighted using a circadian rhythm to appear more human.
-   The `profile_injector.py` uses a robust 8-phase protocol for data injection, which is significantly faster and more reliable than the old `content insert` method.

## Hardware & Real-World Limitations

Be aware of the following limitations, which are documented in `copilot-instructions.md`:

-   **Play Integrity STRONG**: Cannot be passed due to the lack of a physical TEE.
-   **NFC Payments**: The system can provision wallets, but actual NFC payments require physical hardware.
-   **Samsung Pay**: Not supported due to the Knox TEE e-fuse.
-   **Real OAuth Tokens**: Cannot be generated; requires a real Google authentication flow.
-   **Stubbed Features**: Some features, like `kyc_core.py`, are stubs and not fully functional. Do not implement features that claim to work but don't.

