"""
Titan V12.0 — Intelligence Router
/api/intel/* — AI copilot, recon, OSINT, 3DS strategy, dark web
"""

import logging
from fastapi import APIRouter, Request

router = APIRouter(prefix="/api/intel", tags=["intel"])
logger = logging.getLogger("titan.intel")


@router.post("/copilot")
async def intel_copilot(request: Request):
    body = await request.json()
    query = body.get("query", "")
    try:
        from core.ai_intelligence_engine import AIIntelligenceEngine
    except ImportError:
        from ai_intelligence_engine import AIIntelligenceEngine
    try:
        engine = AIIntelligenceEngine()
        result = engine.orchestrate_operation_intel(query)
        return {"result": result}
    except Exception as e:
        logger.exception("Copilot processing failed")
        return {
            "result": {
                "query": query,
                "response": "Failed to generate copilot intelligence.",
                "error": str(e),
            }
        }


@router.post("/recon")
async def intel_recon(request: Request):
    body = await request.json()
    domain = body.get("domain", "")
    try:
        from core.ai_intelligence_engine import AIIntelligenceEngine
    except ImportError:
        from ai_intelligence_engine import AIIntelligenceEngine

    try:
        engine = AIIntelligenceEngine()
        result = engine.analyze_domain(domain)
        return {"result": result}
    except Exception as e:
        logger.exception("Recon failed")
        return {"result": {"error": "Failed to analyze domain", "details": str(e)}}


@router.post("/osint")
async def intel_osint(request: Request):
    """Run OSINT tools (Sherlock, Maigret, Holehe, etc.) on a target."""
    body = await request.json()
    query_data = {
        "name": body.get("name", ""),
        "email": body.get("email", ""),
        "username": body.get("username", ""),
        "phone": body.get("phone", ""),
        "domain": body.get("domain", ""),
    }
    try:
        from osint_orchestrator import OSINTOrchestrator
        orch = OSINTOrchestrator()
        result = orch.run(**query_data)
        return {"result": result}
    except ImportError:
        logger.warning("OSINT orchestrator unavailable, returning fallback.")
        return {
            "result": {
                "status": "unavailable",
                "message": "OSINT module not installed.",
                "query": query_data,
            }
        }
    except Exception as e:
        logger.exception("OSINT processing failed")
        return {"result": {"error": str(e)}}


@router.post("/3ds-strategy")
async def intel_3ds_strategy(request: Request):
    body = await request.json()
    try:
        from core.ai_intelligence_engine import AIIntelligenceEngine
    except ImportError:
        from ai_intelligence_engine import AIIntelligenceEngine

    try:
        engine = AIIntelligenceEngine()
        result = engine.get_3ds_strategy(
            bin_prefix=body.get("bin", ""),
            merchant=body.get("merchant", ""),
            amount=float(body.get("amount", 0)),
        )
        return {"result": result}
    except Exception as e:
        logger.exception("3DS strategy failed")
        return {"result": {"error": "3DS strategy unavailable", "details": str(e)}}


@router.post("/darkweb")
async def intel_darkweb(request: Request):
    body = await request.json()
    query = body.get("query", "")
    try:
        from onion_search_engine import OnionSearchEngine
        engine = OnionSearchEngine()
        result = engine.search(query)
        return {"result": result}
    except ImportError:
        logger.warning("Onion search engine unavailable, returning empty result.")
        return {
            "result": {
                "status": "unavailable",
                "message": "Dark web search module missing",
                "query": query,
            }
        }
    except Exception as e:
        logger.exception("Darkweb query failed")
        return {"result": {"error": str(e)}}

