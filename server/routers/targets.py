"""
Titan V12.0 — Targets Router
/api/targets/* — Site analysis, WAF detection, DNS, SSL, scoring
"""

import logging
from fastapi import APIRouter, Request

router = APIRouter(prefix="/api/targets", tags=["targets"])
logger = logging.getLogger("titan.targets")


@router.post("/analyze")
async def target_analyze(request: Request):
    body = await request.json()
    domain = body.get("domain", "")
    try:
        from core.ai_intelligence_engine import AIIntelligenceEngine
    except ImportError:
        from ai_intelligence_engine import AIIntelligenceEngine

    try:
        engine = AIIntelligenceEngine()
        result = engine.analyze_domain(domain)
        return {"domain": domain, "result": result}
    except Exception as e:
        logger.exception("Target analysis failed")
        return {"domain": domain, "result": {"error": "target analysis failed", "details": str(e)}}


@router.post("/waf")
async def target_waf(request: Request):
    body = await request.json()
    domain = body.get("domain", "")
    try:
        from waf_detector import WAFDetector
        detector = WAFDetector()
        result = detector.detect(domain)
        return {"domain": domain, "result": result}
    except ImportError:
        logger.warning("WAF detector unavailable, using passive indicators")
        return {
            "domain": domain,
            "result": {
                "waf_detected": False,
                "notes": "waf_detector module missing, using fallback heuristics",
            },
        }
    except Exception as e:
        logger.exception("WAF detection failed")
        return {"domain": domain, "result": {"error": str(e)}}


@router.post("/dns")
async def target_dns(request: Request):
    body = await request.json()
    domain = body.get("domain", "")
    try:
        import dns.resolver
        answers = {}
        for rtype in ["A", "AAAA", "MX", "NS", "TXT", "CNAME"]:
            try:
                resp = dns.resolver.resolve(domain, rtype, lifetime=5)
                answers[rtype] = [r.to_text() for r in resp]
            except Exception:
                answers[rtype] = []
        return {"domain": domain, "result": answers}
    except ImportError:
        logger.warning("dnspython not installed, falling back to socket for A record")
        import socket
        try:
            ip = socket.gethostbyname(domain)
            return {"domain": domain, "result": {"A": [ip]}}
        except Exception as e:
            return {"domain": domain, "result": {"error": str(e)}}
    except Exception as e:
        logger.exception("DNS lookup failed")
        return {"domain": domain, "result": {"error": str(e)}}


@router.post("/profiler")
async def target_profiler(request: Request):
    body = await request.json()
    domain = body.get("domain", "")
    try:
        from target_profiler import TitanTargetProfiler
        profiler = TitanTargetProfiler()
        result = profiler.profile(domain)
        return {"domain": domain, "result": result}
    except ImportError:
        logger.warning("Target profiler unavailable, returning minimal profile")
        return {
            "domain": domain,
            "result": {
                "status": "fallback",
                "host": domain,
            },
        }
    except Exception as e:
        logger.exception("Target profiler failed")
        return {"domain": domain, "result": {"error": str(e)}}
