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
* **Pipeline API**: Reference `VMOS-API-ERRORS-AND-DEBUGGING-LOG.md` for undocumented API quirks. Device status: `10`=Running, `11`=Booting, `12`=Resetting, `14`=Abnormal.

## CRITICAL Crash Prevention Rules
* **NEVER** `pm disable-user com.cloud.rtcgesture` — VMOS WebRTC control channel; causes permanent status=11 (device bricked, needs full RESET)
* **NEVER** `pm disable-user com.android.expansiontools` — VMOS management app; may brick device
* **NEVER** mount tmpfs over `/system/priv-app/` — breaks PackageManagerService
* **NEVER** mass chmod on `/sys/block/` — 679 loop + 64 NBD devices; kernel read-only; timeout causes crash
* **NEVER** rapid-fire async_adb_cmd calls (<3s apart) — triggers 110031 cascade → status=14
* **NEVER** restart a device in status=11 — causes 11↔14 boot loop; wait patiently for 11→10
* VMOS `/system` is device-mapper (dm-6) protected — `remount rw` ALWAYS fails
* Space ADB commands ≥3s apart; batch related commands into single shell strings

## Safe Stealth Techniques
* `tmpfs` staging at `/dev/.sc` (anonymous mount)
* `bind-mount` sterile files over `/proc/cmdline`, `/proc/mounts`, `/proc/1/cgroup`
* `resetprop --delete` for non-boot properties
* `resetprop <prop> ""` for boot-locked `ro.boot.*` properties
* `rmmod selinux_leak_fix` (unloads VMOS kernel module)
* Process comm rename via `echo newname > /proc/PID/comm`
* Full iptables control for network filtering
