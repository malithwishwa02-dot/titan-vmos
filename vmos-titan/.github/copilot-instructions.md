# VMOS Titan Genesis Engine Guidelines

You are an AI assistant working on the Genesis Pipeline (Titan V13) for VMOS Cloud.
ALWAYS consult your `.github/skills/genesis-engine/SKILL.md` skill for deep context.

## Core Directives
1. **Never use `updatePadAndroidProp`** — it queues tasks and reboots devices, bricking the pipeline. Use shell batched `resetprop` commands via `syncCmd`.
2. **Never use `replacePad`** — it unpredictably triggers device resets.
3. Understand the Phase Structure: The pipeline goes from Device Readiness (0), Identity Injection (1), Stealth (2), Networks (3), GApps & Play Store (4/5), Device Forging & Data (6), to Wallet & Payment (7/8/9), Attestation (10), and Scoring (11).
4. **Shell Constraints**: Only run shell commands when `padStatus=10`. Rely on chunked Base64 transfers for SQLite database deployments (`tapandpay.db`, Web Data, etc.) as detailed in `purchase-validation/`.

## Knowledge Scope
* **Purchase Validation**: For any payment questions, check the docs in `purchase-validation/*.md` (Google Pay DPANs, Play Store `COIN.xml`, Chrome Autofill).
* **Pipeline API**: Reference `VMOS-API-ERRORS-AND-DEBUGGING-LOG.md` for undocumented API quirks. Device status: `10`=Running, `11`=Booting, `12`=Resetting, `14`=Stopped.
