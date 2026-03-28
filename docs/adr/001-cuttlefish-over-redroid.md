# ADR-001: Cuttlefish over Redroid

**Status:** Accepted
**Date:** 2025-03-14
**Decision Makers:** Core team

## Context

Titan V11 originally used Redroid (Remote Android in Docker) containers for device virtualization. We needed to evaluate whether to continue with Redroid or migrate to Google's Cuttlefish KVM-based virtual device for V11.3.

## Decision

Migrate to **Cuttlefish** (AOSP `launch_cvd`) as the primary Android virtualization backend.

## Rationale

| Factor | Redroid | Cuttlefish |
|--------|---------|------------|
| **Kernel** | Shared host kernel (container) | Dedicated guest kernel (KVM VM) |
| **Detection surface** | High — `/proc/1/cgroup` leaks Docker, no `/dev/kvm` | Low — real Android kernel, real `/proc` layout |
| **GPU passthrough** | Limited (virgl only) | Full virtio-gpu + GfxStream |
| **Telephony** | None — no RIL stack | Full modem emulation (CF modem simulator) |
| **GMS certification** | Impossible (no CTS profile) | Possible via Play Integrity + keybox |
| **Kernel modules** | Host kernel constraints | Independent — vhost_vsock, v4l2loopback |
| **Scalability** | Fast (container spin-up <5s) | Slower (VM boot ~30s) but more isolated |
| **ADB** | TCP over Docker network | TCP over vsock bridge (6520) |

Key deciding factors:
1. **Stealth score**: Redroid maxed at ~45% due to unavoidable container artifacts. Cuttlefish achieves 91%+.
2. **Telephony**: Real SIM/modem emulation is critical for carrier identity forging.
3. **GMS**: Play Integrity attestation requires a real Android boot chain that containers can't provide.

## Consequences

- Higher resource requirements (8+ cores, 16GB+ RAM per VM vs 2 cores for Redroid)
- Slower VM startup (~30s vs ~5s)
- Need KVM host support (`/dev/kvm`)
- 42 `ro.*` system props on erofs can't be changed at runtime — requires custom system image for full Samsung identity
- Retained Redroid Dockerfiles in `docker/_deprecated/` for reference

## Alternatives Considered

- **Redroid with custom kernel**: Too fragile, detection surface remains
- **AVD (Android Virtual Device)**: No headless mode, designed for developer workstations
- **Anbox**: Abandoned upstream, no Android 14 support
