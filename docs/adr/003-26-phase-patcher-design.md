# ADR-003: 26-Phase Anomaly Patcher Design

**Status:** Accepted
**Date:** 2025-03-14
**Decision Makers:** Core team

## Context

Android antidetect requires patching hundreds of device fingerprint vectors across multiple subsystems. We needed to decide how to organize the patching logic: monolithic function, plugin system, or phased pipeline.

## Decision

Implement the anomaly patcher as a **26-phase sequential pipeline** within a single orchestrator class (`AnomalyPatcher`), where each phase covers a distinct detection surface.

## The 26 Phases

| # | Phase | Vectors | Purpose |
|---|-------|---------|---------|
| 1 | Identity | 12 | Device model, brand, fingerprint, serial, IMEI |
| 2 | Telephony | 8 | SIM state, carrier, MCC/MNC, phone number |
| 3 | Anti-Emulator | 6 | Remove vsoc/virtio/cuttlefish artifacts |
| 4 | Build Verification | 5 | build.prop, build tags, build type |
| 5 | RASP Evasion | 7 | Root hiding, Magisk, Frida, Xposed detection |
| 6 | GPU/Graphics | 4 | GL renderer, vendor, version strings |
| 7 | Battery | 3 | Fake battery level, temperature, charging state |
| 8 | Location | 4 | GPS coordinates, timezone, locale |
| 9 | Media History | 5 | Chrome history, cookies, localStorage |
| 10 | Network | 6 | WiFi MAC, saved networks, DNS, IP |
| 11 | GMS/Integrity | 4 | Play Integrity, SafetyNet, GMS checkin |
| 12 | Keybox/Attestation | 3 | Hardware attestation keybox |
| 13 | GSF Alignment | 3 | Google Services Framework ID coherence |
| 14 | Sensors | 7 | Accelerometer, gyroscope, magnetometer noise |
| 15 | Bluetooth | 3 | BT MAC, adapter name, paired devices |
| 16 | /proc Sterilize | 5 | mountinfo, cpuinfo, meminfo scrubbing |
| 17 | Camera | 2 | Camera HAL IDs, capabilities |
| 18 | NFC/Storage | 3 | NFC state, storage paths |
| 19 | WiFi Scan | 3 | Fake nearby APs, signal strengths |
| 20 | SELinux | 2 | Enforcing mode, policy version |
| 21 | Storage Encryption | 2 | FBE state, vold |
| 22 | Process Stealth | 4 | Hide emulator processes from ps/proc |
| 23 | Audio | 2 | Audio HAL, mixer paths |
| 24 | Kinematic Input | 2 | Touch event timing, pressure patterns |
| 25 | Kernel Hardening | 3 | Kernel version, cmdline, modules |
| 26 | Persistence | 4 | Reboot survival via init.d, service.d, local.prop |

**Total: 103+ individual detection vectors**

## Rationale

### Why 26 phases (not 10 or 50)?

Each phase maps to a distinct **Android subsystem** with its own detection surface. Grouping by subsystem means:
- Each phase can be independently timed, debugged, and skipped
- Failure in one phase doesn't cascade (battery failure doesn't break telephony)
- The audit system mirrors the same 26 categories for before/after comparison

### Why a single file (not per-phase modules)?

At the time of initial implementation, keeping all phases in one file (`anomaly_patcher.py`, ~157KB) was chosen for:
1. **Shared state**: All phases share `self._results`, `self._phase_timings`, and ADB helpers
2. **Sequential orchestration**: Phases must run in order (identity before telephony, persistence last)
3. **Grep-ability**: A single file is easier to search and cross-reference

**Trade-off acknowledged**: The file is large. Future refactoring into a `core/anomaly_patcher/` package with per-phase modules is planned, retaining the orchestrator pattern.

### Why sequential (not parallel)?

Phases have implicit dependencies:
- Phase 1 (Identity) sets `ro.product.model` which Phase 6 (GPU) references
- Phase 5 (RASP) must complete before Phase 11 (GMS) to avoid SafetyNet trip
- Phase 26 (Persistence) must run last to capture all changes

Parallel execution would require explicit dependency graph management with minimal time savings (most phases are I/O-bound on the same ADB connection).

## Consequences

- Full patch takes 200–365 seconds (sequential ADB commands)
- `quick_repatch()` skips media-generation phases for ~30s reboot recovery
- The 157KB file size is a maintenance concern — mitigated by clear section headers and phase numbering
- Adding a new phase requires incrementing the count and updating the audit system

## Alternatives Considered

- **Plugin system**: Each phase as a registered plugin. Rejected — over-engineered for a fixed pipeline
- **DAG scheduler**: Parallel execution with dependency resolution. Rejected — ADB is single-threaded bottleneck
- **External config**: Phase definitions in YAML/JSON. Rejected — phases contain complex Python logic that can't be declaratively expressed
