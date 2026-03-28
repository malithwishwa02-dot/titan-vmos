# ADR-002: Circadian Weighting for Temporal Data Distribution

**Status:** Accepted
**Date:** 2025-03-14
**Decision Makers:** Core team

## Context

Forged device profiles need realistic temporal distribution of user activity (calls, SMS, browsing, app usage). Uniform random distribution is trivially detectable by behavioral analytics — real humans have predictable daily patterns (sleep at night, active during day, peak phone use in evening).

## Decision

Implement **circadian weighting** for all time-series data generation in `AndroidProfileForge`. Activity timestamps are drawn from a weighted probability distribution that models a 24-hour human activity cycle.

## Rationale

Real-world mobile usage data shows consistent patterns:
- **00:00–06:00**: Near-zero activity (sleep)
- **07:00–09:00**: Morning ramp-up (commute browsing, quick calls)
- **09:00–12:00**: Moderate (work hours — fewer personal calls, some browsing)
- **12:00–14:00**: Lunch spike (social media, messaging, short calls)
- **14:00–17:00**: Moderate decline
- **17:00–21:00**: Evening peak (highest personal activity — calls, browsing, shopping)
- **21:00–23:59**: Gradual wind-down

The weight function approximates this as a piecewise distribution with Gaussian smoothing at transition boundaries.

### Detection vectors this defeats:
1. **Uniform timestamp distribution** — flagged by ML classifiers trained on real usage
2. **Activity during sleep hours** — immediate red flag for behavioral profiling
3. **Missing evening peaks** — inconsistent with every demographic studied
4. **Identical inter-event intervals** — suggests programmatic generation

## Implementation

- `AndroidProfileForge._circadian_weight(hour: int) -> float` returns weight 0.0–1.0
- All timestamp generators (calls, SMS, history, cookies) use weighted random sampling
- The weight curve is parameterized per archetype (e.g., "night_owl" shifts peak to 23:00–02:00)
- Weekend vs weekday patterns differ (weekend morning activity starts ~2h later)

## Consequences

- Profile generation is slightly slower due to rejection sampling (~5% overhead)
- Age boundaries at 0h and 24h need careful handling (wrapping midnight)
- The weight curve is currently US-centric; other locales may have different patterns (e.g., Spanish siesta gap at 14:00–17:00)

## Alternatives Considered

- **Poisson process**: Simpler but doesn't capture the bimodal daily pattern
- **Markov chain**: More accurate but adds complexity without proportional stealth benefit
- **Real user data replay**: Requires sourcing real datasets — privacy/legal issues
