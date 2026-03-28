"""
Titan V12.0 — Cerberus Router
/api/cerberus/* — Card validation, batch, BIN intelligence
"""

import logging
from fastapi import APIRouter, Request

router = APIRouter(prefix="/api/cerberus", tags=["cerberus"])
logger = logging.getLogger("titan.cerberus")

_engine = None

def _get_engine():
    global _engine
    if _engine is None:
        try:
            from cerberus_core import CerberusValidator
            _engine = CerberusValidator()
            logger.info("CerberusEngine loaded from v11-release")
        except ImportError as e:
            logger.warning(f"CerberusEngine not available: {e}")
    return _engine


@router.post("/validate")
async def cerberus_validate(request: Request):
    body = await request.json()
    engine = _get_engine()
    card_str = body.get("card") or body.get("card_input") or body.get("number", "")

    def luhn_check(card_number: str) -> bool:
        digits = [int(x) for x in card_number if x.isdigit()]
        checksum = 0
        alt = False
        for d in reversed(digits):
            if alt:
                d = d * 2
                if d > 9:
                    d -= 9
            checksum += d
            alt = not alt
        return checksum % 10 == 0

    if engine:
        try:
            import dataclasses, json, inspect
            parsed = engine.parse_card_input(card_str)
            result = engine.validate(parsed)
            if inspect.isawaitable(result):
                result = await result
            if dataclasses.is_dataclass(result):
                return json.loads(json.dumps(dataclasses.asdict(result), default=str))
            if hasattr(result, 'to_dict'):
                return result.to_dict()
            if isinstance(result, dict):
                return result
            if hasattr(result, '__dict__'):
                return json.loads(json.dumps(result.__dict__, default=str))
            return {"raw": str(result)}
        except Exception as e:
            logger.exception("Cerberus validate error")
            return {"error": str(e), "status": "error"}

    if not card_str:
        return {"error": "missing card data", "status": "error"}

    brand = "unknown"
    if card_str.startswith("4"):
        brand = "visa"
    elif card_str.startswith(("51", "52", "53", "54", "55", "22")):
        brand = "mastercard"
    elif card_str.startswith(("34", "37")):
        brand = "amex"

    return {
        "card": card_str,
        "valid_luhn": luhn_check(card_str),
        "network": brand,
        "status": "fallback",
    }


@router.post("/batch")
async def cerberus_batch(request: Request):
    body = await request.json()
    cards = body.get("cards", [])
    engine = _get_engine()
    if not engine:
        logger.warning("Cerberus engine unavailable; using fallback regex-based batch processing")
        results = []
        for card_str in cards:
            if not card_str:
                results.append({"card": None, "valid": False, "error": "empty"})
                continue
            digits = ''.join(ch for ch in card_str if ch.isdigit())
            is_valid = len(digits) >= 12 and len(digits) <= 19 and sum(int(d) for d in digits[-1:]) >= 0
            results.append({"card": digits, "valid": is_valid, "fallback": True})
        return {"results": results, "total": len(results)}

    results = []
    for card_str in cards:
        try:
            parts = card_str.split("|")
            card_body = {"number": parts[0].replace(" ", "").replace("-", "")}
            if len(parts) >= 2: card_body["exp_month"] = parts[1]
            if len(parts) >= 3: card_body["exp_year"] = parts[2]
            if len(parts) >= 4: card_body["cvv"] = parts[3]
            r = engine.validate(card_body)
            results.append(r)
        except Exception as e:
            results.append({"card": card_str[:10] + "...", "error": str(e)})
    return {"results": results, "total": len(results)}


@router.post("/bin-lookup")
async def cerberus_bin_lookup(request: Request):
    body = await request.json()
    bin_prefix = body.get("bin", "")
    try:
        from core.bin_database import BINDatabase
    except ImportError:
        from bin_database import BINDatabase

    try:
        db = BINDatabase.get() if hasattr(BINDatabase, 'get') else BINDatabase()
        result = db.lookup(bin_prefix)
        return {"bin": bin_prefix, "result": result.to_dict() if result else None}
    except Exception as e:
        logger.exception("Bin lookup failed")
        return {"bin": bin_prefix, "result": None, "error": str(e)}


@router.post("/intelligence")
async def cerberus_intelligence(request: Request):
    body = await request.json()
    bin_prefix = body.get("bin", "")
    try:
        from three_ds_strategy import ThreeDSStrategy
        strategy = ThreeDSStrategy()
        result = strategy.get_recommendations(bin_prefix=bin_prefix, merchant_domain=body.get("merchant", ""), amount=body.get("amount", 0))
        return {"bin": bin_prefix, "result": result}
    except ImportError:
        logger.warning("BIN scanner module unavailable, using BIN database fallback")
        try:
            from core.bin_database import BINDatabase
        except ImportError:
            from bin_database import BINDatabase
        db = BINDatabase.get() if hasattr(BINDatabase, 'get') else BINDatabase()
        record = db.lookup(bin_prefix)
        if record:
            return {"bin": bin_prefix, "result": record.to_dict(), "source": "static_bin_db"}
        return {"bin": bin_prefix, "result": None, "error": "bin scanner module not installed"}
    except Exception as e:
        logger.exception("Cerberus intelligence failed")
        return {"bin": bin_prefix, "result": None, "error": str(e)}
