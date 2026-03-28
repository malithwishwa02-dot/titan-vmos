# 07 — Pipeline Integration

How wallet and purchase injection fits into the full Genesis provisioning pipeline, including API endpoints, phase ordering, and background job management.

---

## Table of Contents

1. [Pipeline Phase Map](#1-pipeline-phase-map)
2. [Phase 3: Wallet / CC Provisioning](#2-phase-3-wallet--cc-provisioning)
3. [Phase 5.5: Purchase History](#3-phase-55-purchase-history)
4. [Phase 5.5.1: Payment Transaction History](#4-phase-551-payment-transaction-history)
5. [Phase 6: Pipeline Wallet Provision](#5-phase-6-pipeline-wallet-provision)
6. [Phase 7: Provincial Layering](#6-phase-7-provincial-layering)
7. [Phase 10: Trust Audit](#7-phase-10-trust-audit)
8. [API Endpoints](#8-api-endpoints)
9. [Background Job Architecture](#9-background-job-architecture)
10. [Codebase Cross-References](#10-codebase-cross-references)

---

## 1. Pipeline Phase Map

The full Genesis provisioning pipeline (`_run_pipeline_job` in `server/routers/provision.py`) includes these wallet-related phases:

```
Phase 0:  Wipe                    ← Factory reset (optional)
Phase 1:  Stealth Patch           ← Anomaly patcher (age_days=1)
Phase 2:  Network/Proxy           ← VPN/proxy configuration
Phase 3:  Forge Persona           ← AndroidProfileForge
Phase 4:  Google Account          ← Account injection / creation
Phase 5:  Profile Injection       ← Full profile inject (contacts, SMS, etc.)
                                     ├── Phase 3 (internal): Wallet / CC  ← HERE
                                     ├── Phase 5.5: Purchase History      ← HERE
                                     └── Phase 5.5.1: Payment Tx History  ← HERE
Phase 6:  Wallet/GPay             ← Pipeline-level wallet provision       ← HERE
Phase 7:  Provincial Layering     ← Regional app data + wallet bypass     ← HERE
Phase 8:  Post-Harden             ← Lock settings, disable dev options
Phase 9:  Attestation             ← Play Integrity check
Phase 10: Trust Audit             ← Trust score + wallet verification     ← HERE
```

**Source:** `server/routers/provision.py` lines 530–650 (`phases` array)

---

## 2. Phase 3: Wallet / CC Provisioning

This phase runs inside `ProfileInjector.inject_full_profile()` when `card_data` is provided:

```python
# profile_injector.py Phase 3
if card_data:
    self._inject_wallet(profile, card_data)
```

### What It Does

1. Imports `WalletProvisioner`
2. Calls `provision_card()` with card details from the pipeline request body
3. Checks `wallet_result.success_count >= 3` to set `wallet_ok`
4. Logs wallet injection results

### Input (from Pipeline Request)

```json
{
    "cc_number": "4638512320340405",
    "cc_exp_month": 8,
    "cc_exp_year": 2029,
    "cc_cvv": "051",
    "cc_cardholder": "Jovany Owens"
}
```

### Output

```
Wallet: 4/4 targets | verification: 92
```

**Source:** `core/profile_injector.py` lines 182–198, 304–331

---

## 3. Phase 5.5: Purchase History

Runs immediately after Play Store purchase injection:

```python
# profile_injector.py Phase 5.5
def _inject_purchase_history(self, profile):
    from purchase_history_bridge import generate_android_purchase_history
    ph = generate_android_purchase_history(
        persona_name=profile.get("persona_name"),
        persona_email=profile.get("persona_email"),
        country=profile.get("country", "US"),
        age_days=profile.get("age_days", 90),
        card_last4=card_last4,
        card_network=card_network,
        purchase_categories=purchase_cats,
    )
    # Injects Chrome history, cookies, notifications, email receipts
```

### What Gets Injected

| Artifact | Typical Count |
|----------|:------------:|
| Chrome commerce history URLs | 15–30 |
| Chrome commerce cookies | 8–15 |
| Order notification entries | 5–15 |
| Email receipt entries | 5–15 |

**Source:** `core/profile_injector.py` lines 442–493

---

## 4. Phase 5.5.1: Payment Transaction History

Runs only if `card_data` is provided:

```python
# profile_injector.py Phase 5.5.1
if card_data:
    self._inject_payment_history(profile, card_data)
```

This calls `WalletProvisioner.correlate_transactions_with_profile()` to generate transaction records that cross-reference with Chrome browsing history, Maps navigation, and email receipts.

**Source:** `core/profile_injector.py` lines 195–197, 494–540

---

## 5. Phase 6: Pipeline Wallet Provision

The pipeline's own wallet provisioning step (separate from the profile injector's Phase 3). This runs at the pipeline level with additional controls:

```python
# provision.py — Phase 6: Wallet/GPay
from wallet_provisioner import WalletProvisioner
wp = WalletProvisioner(adb_target=adb_target)
w_result = wp.provision_card(
    card_number=body.cc_number,
    exp_month=body.cc_exp_month,
    exp_year=body.cc_exp_year,
    cardholder=body.cc_cardholder or profile_data.get("persona_name", ""),
    cvv=body.cc_cvv,
    persona_email=profile_data.get("persona_email", ""),
    persona_name=profile_data.get("persona_name", ""),
    country=body.country or "US",
    zero_auth=True,  # ← Always True in pipeline
)
```

### Additional Pipeline Steps in Phase 6

After wallet provisioning:
1. **Purchase history bridge:** Injects commerce purchase history
2. **Ownership fix:** `chown` + `restorecon` on all wallet files
3. **Wallet verify:** Quick verification pass (not full 13-check)

**Source:** `server/routers/provision.py` lines 710–759

---

## 6. Phase 7: Provincial Layering

Provincial layering injects region-specific app data including wallet-related bypass configurations:

```python
# provision.py — Phase 7: Provincial Layering
from app_data_forger import AppDataForger
forger = AppDataForger(adb_target=adb_target)
forge_result = forger.forge_and_inject(
    installed_packages=installed,
    persona=persona,
    play_purchases=profile_data.get("play_purchases", []),
    app_installs=profile_data.get("app_installs", []),
)
```

### Wallet-Related App Data Injected

| App | Data Injected |
|-----|--------------|
| Chase Mobile | Logged-in SharedPrefs, card on file |
| PayPal | Session cookie, account prefs |
| Venmo | Account state, payment history |
| Cash App | Device registration, session |
| Amazon Shopping | Cart state, order history prefs |

**Source:** `server/routers/provision.py` lines 760–790

---

## 7. Phase 10: Trust Audit

The final pipeline phase runs a comprehensive trust audit that includes wallet verification:

```python
# provision.py — Phase 10: Trust Audit
from trust_scorer import compute_trust_score
trust = compute_trust_score(adb_target, profile_data)

from wallet_verifier import WalletVerifier
wv = WalletVerifier(adb_target=adb_target)
wallet_report = wv.verify()
```

### Trust Score Wallet Checks

| Check # | Name | Weight | What It Verifies |
|:-------:|------|:------:|-----------------|
| 6 | `gpay_wallet` | 8% | tapandpay.db exists + keybox status |
| 6a | `tapandpay_tokens` | (sub) | Token count ≥ 1 |
| 6b | `nfc_enabled` | (sub) | NFC prefs set |
| 6c | `gms_billing` | (sub) | GMS billing prefs synced |
| 13 | `autofill` | 4% | Chrome Web Data has credit cards |

**Source:** `core/trust_scorer.py` lines 125–145, 197–203

### Wallet Verification Report

The full 13-check wallet verification produces:
- Score (0–100)
- Grade (A+, A, B, C, F)
- Per-check pass/fail with remediation hints

**Source:** `core/wallet_verifier.py` lines 88–142

---

## 8. API Endpoints

### Wallet-Related Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/genesis/inject/{device_id}` | Full profile inject including wallet |
| `POST` | `/api/genesis/full-provision/{device_id}` | Complete pipeline (all phases) |
| `POST` | `/api/genesis/provincial-inject/{device_id}` | Regional zero-auth injection |
| `GET` | `/api/stealth/{device_id}/wallet-verify` | 13-check wallet deep verification |
| `GET` | `/api/genesis/trust-score/{device_id}` | Trust score (includes wallet check) |
| `GET` | `/api/genesis/wallet-transactions/{device_id}` | Read back wallet transactions |
| `POST` | `/api/genesis/request-otp` | Auto-detect OTP from device SMS |
| `GET` | `/api/genesis/wallet-status/{device_id}` | Quick wallet status check |

### Pipeline Request Body

```python
class FullProvisionBody(BaseModel):
    model: str = "samsung_s24"
    persona_name: Optional[str] = None
    persona_email: Optional[str] = None
    cc_number: Optional[str] = None
    cc_exp_month: Optional[int] = None
    cc_exp_year: Optional[int] = None
    cc_cvv: Optional[str] = None
    cc_cardholder: Optional[str] = None
    country: str = "US"
    age_days: int = 90
    proxy_url: Optional[str] = None
```

### Example Pipeline Call

```bash
curl -X POST https://72.62.72.48/api/genesis/full-provision/dev-cvd001 \
  -H "Content-Type: application/json" \
  -d '{
    "model": "samsung_s24",
    "persona_name": "Jovany Owens",
    "persona_email": "adiniorjuniorjd28@gmail.com",
    "cc_number": "4638512320340405",
    "cc_exp_month": 8,
    "cc_exp_year": 2029,
    "cc_cvv": "051",
    "cc_cardholder": "Jovany Owens",
    "country": "US",
    "age_days": 500
  }'
```

**Source:** `server/routers/provision.py` lines 39–85, 300–350

---

## 9. Background Job Architecture

All wallet injection operations run as background jobs to prevent HTTP timeouts:

```python
@router.post("/full-provision/{device_id}")
async def genesis_full_provision(device_id: str, body: FullProvisionBody):
    job_id = str(uuid.uuid4())
    _provision_jobs[job_id] = {"status": "running", "phase": 0, ...}
    asyncio.get_event_loop().run_in_executor(
        None, _run_pipeline_job, job_id, device_id, body
    )
    return {"job_id": job_id, "status": "started"}
```

### Polling Job Status

```bash
curl https://72.62.72.48/api/genesis/provision-status/{job_id}
```

Returns:
```json
{
    "job_id": "abc-123",
    "status": "running",
    "phase": 6,
    "phase_name": "Wallet/GPay",
    "phases": [
        {"n": 0, "name": "Wipe", "status": "done"},
        {"n": 1, "name": "Stealth Patch", "status": "done"},
        ...
        {"n": 6, "name": "Wallet/GPay", "status": "running"},
        ...
    ]
}
```

**Source:** `server/routers/provision.py` lines 160–295

---

## 10. Codebase Cross-References

| File | Section | Description |
|------|---------|-------------|
| `server/routers/provision.py` lines 530–650 | `phases` array | Pipeline phase definitions |
| `server/routers/provision.py` lines 710–759 | Phase 6 | Pipeline wallet provision |
| `server/routers/provision.py` lines 760–790 | Phase 7 | Provincial layering |
| `server/routers/provision.py` lines 936–964 | `genesis_provincial_inject()` | Provincial injection endpoint |
| `server/routers/provision.py` lines 160–295 | Job polling | Background job status |
| `server/routers/provision.py` lines 39–85 | Request bodies | Pipeline request models |
| `core/profile_injector.py` lines 142–231 | `inject_full_profile()` | Profile injector main method |
| `core/profile_injector.py` lines 182–198 | Phase 3 | Wallet / CC provisioning |
| `core/profile_injector.py` lines 442–493 | Phase 5.5 | Purchase history injection |
| `core/profile_injector.py` lines 494–540 | Phase 5.5.1 | Payment transaction history |
| `core/wallet_provisioner.py` lines 355–575 | `provision_card()` | WalletProvisioner entry point |
| `core/trust_scorer.py` lines 125–145 | Check #6 | Trust score wallet checks |
| `core/wallet_verifier.py` lines 88–142 | `verify()` | Full 13-check wallet verification |
| `server/routers/genesis.py` lines 402–470 | `wallet_transactions()` | Read back wallet transactions |
| `provincial_injection_protocol.py` | Full file | Standalone provincial injection |

---

*See [08-verification-and-trust.md](08-verification-and-trust.md) for verification checks and trust scoring details.*
