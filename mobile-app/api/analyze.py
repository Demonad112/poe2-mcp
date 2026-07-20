"""
Athrynas-style build-ledger API for Vercel.

POST /api/analyze {"url": "https://poe.ninja/poe2/profile/<account>/<league>/character/<name>"}
-> the same DATA JSON shape the ledger frontend (public/index.html) renders,
   built from poe2-mcp's real fetch/analyze code (vendored under
   api/_vendor/src — see that folder for why: importing the real `src`
   package pulls in unrelated heavy deps via a couple of its __init__.py
   files, so this ships a lean copy of just the modules this endpoint uses,
   unmodified except config.py's read-only-deploy fix and two trivial
   __init__.py files).

The big passive-tree data file (psg_passive_nodes.json, ~2MB) is NOT
bundled in the deployment — it's fetched once from the poe2-mcp GitHub
repo on cold start and cached in /tmp, so warm invocations reuse it.
"""

import os
import re
import sys
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "_vendor"))

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from src.api.poe_ninja_api import parse_poe_ninja_url
from src.api.character_fetcher import CharacterFetcher
from src.api.poe_ninja_ladder import LadderClient
from src.calculator.ehp_calculator import EHPCalculator, DefensiveStats, ThreatProfile, DamageType
from src.parsers.passive_tree_resolver import PassiveTreeResolver

logger = logging.getLogger(__name__)

app = FastAPI()
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)

PASSIVE_TREE_DATA_URL = (
    "https://raw.githubusercontent.com/Demonad112/poe2-mcp/main/data/psg_passive_nodes.json"
)
TREE_CACHE_DIR = Path("/tmp/poe2-mobile-ledger")
TREE_CACHE_FILE = TREE_CACHE_DIR / "psg_passive_nodes.json"

_resolver: Optional[PassiveTreeResolver] = None


async def _get_tree_resolver() -> PassiveTreeResolver:
    """Lazily download the passive-tree data file into /tmp on cold start
    (kept out of the deployment bundle - see module docstring), then
    memoize the resolver for warm reuse."""
    global _resolver
    if _resolver is not None:
        return _resolver

    if not TREE_CACHE_FILE.exists():
        TREE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(PASSIVE_TREE_DATA_URL)
            resp.raise_for_status()
            TREE_CACHE_FILE.write_bytes(resp.content)
        logger.info(f"Cached passive tree data to {TREE_CACHE_FILE} ({len(resp.content)} bytes)")

    _resolver = PassiveTreeResolver(data_dir=TREE_CACHE_DIR)
    return _resolver


class AnalyzeRequest(BaseModel):
    url: str


def fmt_dist(n: int) -> str:
    return f"{n} node away" if n == 1 else f"{n} nodes away"


SLOT_LABELS = {
    "Weapon 1": "Main Hand",
    "Weapon 2": "Off Hand",
    "Weapon 1 Swap": "Swap — Main Hand",
    "Weapon 2 Swap": "Swap — Off Hand",
    "Ring 1": "Ring",
    "Ring 2": "Ring",
}


def classify_item_bucket(slot: Optional[str]) -> str:
    if not slot:
        return "jewel"
    if "Swap" in slot:
        return "swap"
    if slot.startswith("Flask") or slot.startswith("Charm"):
        return "consum"
    return "main"


def build_item_dict(it: Dict[str, Any]) -> Dict[str, Any]:
    slot = it.get("slot")
    return {
        "slot": SLOT_LABELS.get(slot, slot or "Jewel"),
        "name": it.get("name") or "Unknown",
        "base": it.get("type_line") or it.get("base_type") or "",
        "ilvl": it.get("item_level") or 0,
        "rarity": it.get("rarity") or "Normal",
        "mods": it.get("mods") or [],
    }


def compute_strengths_weaknesses(stats: Dict[str, Any]) -> (List[str], List[Dict[str, str]]):
    life = stats.get("life", 0) or 0
    es = stats.get("energyShield", 0) or 0
    total_pool = life + es
    fire_res = stats.get("fireResistance", 0) or 0
    cold_res = stats.get("coldResistance", 0) or 0
    lightning_res = stats.get("lightningResistance", 0) or 0
    chaos_res = stats.get("chaosResistance", 0) or 0
    evasion = stats.get("evasionRating", 0) or 0
    armour = stats.get("armour", 0) or 0
    block = stats.get("blockChance", 0) or 0
    ward = stats.get("ward", 0) or 0

    strengths, weaknesses = [], []

    if total_pool > 6000:
        strengths.append(f"Good defensive pool ({total_pool:,.0f} combined life+ES)")
    elif total_pool < 4000:
        weaknesses.append(
            {"text": f"Low combined pool — {total_pool:,.0f} life+ES is on the thin side", "level": "critical"}
        )

    if fire_res >= 75 and cold_res >= 75 and lightning_res >= 75:
        strengths.append("All three elemental resistances capped at 75%")
    else:
        uncapped = [f"{n} {v}%" for n, v in (("Fire", fire_res), ("Cold", cold_res), ("Lightning", lightning_res)) if v < 75]
        weaknesses.append({"text": f"Uncapped resistances ({', '.join(uncapped)})", "level": "critical"})

    if chaos_res < 0:
        weaknesses.append({"text": f"Negative chaos resistance ({chaos_res}%)", "level": "critical"})
    elif chaos_res < 30:
        weaknesses.append({"text": f"Low chaos resistance ({chaos_res}%)", "level": "critical"})

    if evasion > 4000:
        strengths.append(f"{evasion:,.0f} evasion rating is a real mitigation layer")
    if ward > 0:
        strengths.append(f"{ward:,.0f} Ward adds a recovering buffer on top of Life/ES")
    if armour < 500 and block < 20:
        weaknesses.append({"text": "Low armour / block — leaning on evasion or resistances alone", "level": "warning"})

    if not strengths:
        strengths.append("No standout defensive strengths detected yet")
    if not weaknesses:
        weaknesses.append({"text": "No major defensive gaps detected", "level": "warning"})

    return strengths, weaknesses


def compute_score(stats: Dict[str, Any]) -> Dict[str, Any]:
    life = stats.get("life", 0) or 0
    es = stats.get("energyShield", 0) or 0
    total_pool = life + es
    fire_res = stats.get("fireResistance", 0) or 0
    cold_res = stats.get("coldResistance", 0) or 0
    lightning_res = stats.get("lightningResistance", 0) or 0
    capped = fire_res >= 75 and cold_res >= 75 and lightning_res >= 75

    score = 0.0
    notes = []
    if total_pool > 6000:
        score += 0.3
    else:
        notes.append("combined life+ES pool")
    if capped:
        score += 0.3
        notes.append("capped elemental resists carry the score" if score <= 0.3 else "")
    else:
        notes.append("uncapped elemental resistances")
    # DPS isn't computed here (see limits) so the 3rd weight is unscored — treat
    # remaining 0.4 as unknown rather than silently failing it.
    score = round(score, 2)

    if score >= 0.6:
        tier = "A"
    elif score >= 0.4:
        tier = "B"
    elif score >= 0.2:
        tier = "C"
    else:
        tier = "D"

    note = "Defenses only — DPS isn't factored in here (see the DPS limitation note)."
    if not capped:
        note = "Uncapped elemental resistances are the main thing pulling this down."
    elif total_pool <= 6000:
        note = "Capped resists help, but the combined life+ES pool is on the low side."

    return {"overall": score, "tier": tier, "note": note}


def build_recs(stats: Dict[str, Any], nearby: List[Dict[str, Any]], skills: List[Dict[str, Any]], ladder_you: Dict, ladder_median: Dict) -> List[Dict[str, str]]:
    recs = []
    chaos_res = stats.get("chaosResistance", 0) or 0
    if chaos_res < 75:
        recs.append({
            "title": "Close the chaos resistance gap",
            "body": f"Chaos resistance sits at {chaos_res}%, well behind the elemental caps. A chaos-res craft or corrupted implicit closes the one real hole in the defensive sheet.",
        })
    es_gap = (ladder_median.get("es") or 0) - (ladder_you.get("es") or 0)
    if es_gap and es_gap > 300:
        recs.append({
            "title": "Close the Energy Shield gap to the ladder median",
            "body": f"Median ES for this cohort is {ladder_median.get('es'):,}, about {es_gap:,.0f} ahead of yours. Likely a tiering upgrade (better-rolled bases) rather than a change in direction.",
        })
    if nearby:
        n = nearby[0]
        recs.append({
            "title": f"Path to {n['name']} — {n['dist']}",
            "body": f"Nearest unallocated notable: {n['effects'][0] if n['effects'] else 'see Passive Tree tab'}",
        })
    if len(skills) > 4:
        recs.append({
            "title": f"Consider consolidating {len(skills)} linked skill setups",
            "body": "That many simultaneously-linked setups often includes leftover leveling links — trimming frees support-gem slots for your real rotation.",
        })
    if not recs:
        recs.append({"title": "No major gaps detected", "body": "This build's defenses and passive allocation look solid based on what's checked here."})
    return recs


LIMITS = [
    {
        "title": "DPS isn't computed here",
        "body": "This ledger focuses on defenses, passive tree, and ladder comparison. DPS depends on exact skill setup and weapon rolls that need a dedicated calculator pass — ask an AI assistant with the poe2-mcp tool connected to run calculate_character_dps for a precise number.",
    },
    {
        "title": "“Disconnected tree” flags are usually a data-completeness artifact",
        "body": "Path of Exile 2 doesn't allow allocating a broken passive tree in-game. If this ledger flags nodes as disconnected, it almost always means a few allocated node IDs aren't in the local tree database yet — not a real problem with your tree.",
    },
    {
        "title": "Ladder comparison uses the current top-of-ladder page",
        "body": "The comparison cohort is whatever poe.ninja's builds search returns right now for your ascendancy/league, sorted by level — not a fixed historical snapshot.",
    },
]


@app.post("/api/analyze")
async def analyze(req: AnalyzeRequest) -> Dict[str, Any]:
    parsed = parse_poe_ninja_url(req.url)
    if not parsed:
        raise HTTPException(status_code=400, detail="That doesn't look like a poe.ninja profile URL.")

    account, character, league = parsed["account"], parsed["character"], parsed["league"]

    fetcher = CharacterFetcher()
    try:
        char_data = await fetcher.get_character(account, character, league)
        if not char_data:
            raise HTTPException(
                status_code=404,
                detail=fetcher.last_error_message
                or "Character not found — check the profile is public and the URL is correct.",
            )

        stats = char_data.get("stats") or {}
        life = stats.get("life", 0) or 0
        es = stats.get("energyShield", 0) or 0

        # ---- EHP ----
        ehp_mcp = None
        try:
            ehp_calc = EHPCalculator()
            defensive_stats = DefensiveStats(
                life=life,
                energy_shield=es,
                armor=stats.get("armour", 0) or 0,
                evasion=stats.get("evasionRating", 0) or 0,
                block_chance=stats.get("blockChance", 0) or 0,
                fire_res=stats.get("fireResistance", 0) or 0,
                cold_res=stats.get("coldResistance", 0) or 0,
                lightning_res=stats.get("lightningResistance", 0) or 0,
                chaos_res=stats.get("chaosResistance", 0) or 0,
            )
            threat = ThreatProfile(expected_hit_size=1000.0)
            results = [
                ehp_calc.calculate_ehp(defensive_stats, dt, threat)
                for dt in (DamageType.PHYSICAL, DamageType.FIRE, DamageType.COLD, DamageType.LIGHTNING)
            ]
            ehp_mcp = int(sum(r.effective_hp for r in results) / len(results))
        except Exception as e:
            logger.warning(f"EHP calc failed: {e}")
            ehp_mcp = life + es

        # ---- Passive tree ----
        tree_out = {
            "totalNodes": 0, "keystonesCount": 0, "smallNodeTotal": 0,
            "jewelSockets": 0, "disconnectNote": None,
        }
        notables_out: List[Dict[str, Any]] = []
        smallnodes_out: List[Dict[str, Any]] = []
        nearby_out: List[Dict[str, Any]] = []
        # character_fetcher returns passive_tree as a flat list of node IDs
        # when parsed from an embedded PoB export, but as a richer dict
        # ({allocated_nodes, total_points, ascendancy_nodes, mastery_effects})
        # when parsed via the poe.ninja profile API fallback tier — handle both.
        raw_passive = char_data.get("passive_tree")
        if isinstance(raw_passive, dict):
            passive_ids = raw_passive.get("allocated_nodes") or []
        else:
            passive_ids = raw_passive or []
        if passive_ids:
            try:
                resolver = await _get_tree_resolver()
                analysis = resolver.analyze_build(passive_ids)
                tree_out = {
                    "totalNodes": analysis.total_nodes,
                    "keystonesCount": len(analysis.keystones),
                    "smallNodeTotal": len(analysis.small_nodes),
                    "jewelSockets": len(analysis.jewel_sockets),
                    "disconnectNote": None if analysis.is_connected else (analysis.connectivity_note or "Tree reports as disconnected."),
                }
                notables_out = [{"name": n.name, "effects": n.stats} for n in analysis.notables]
                small_by_name: Dict[str, list] = {}
                for node in analysis.small_nodes:
                    small_by_name.setdefault(node.name, []).append(node)
                smallnodes_out = [
                    {"name": name, "count": len(nodes), "effect": (nodes[0].stats[0] if nodes[0].stats else "No stats")}
                    for name, nodes in sorted(small_by_name.items(), key=lambda x: -len(x[1]))
                ]
                nearby_out = [
                    {"name": n.name, "dist": fmt_dist(d), "effects": n.stats[:3], "pick": i == 0}
                    for i, (n, d) in enumerate(analysis.nearest_notables[:5])
                ]
            except Exception as e:
                logger.warning(f"Passive tree analysis failed: {e}")

        # ---- Ladder comparison ----
        ladder_out = {"cohort": "N/A", "you": {"level": char_data.get("level", 0), "life": life, "es": es}, "median": {"level": 0, "life": 0, "es": 0}, "table": []}
        try:
            league_slug = fetcher._to_poe_ninja_league_slug(league)
            ladder_class = char_data.get("ascendancy") or char_data.get("class")
            ladder = LadderClient(rate_limiter=fetcher.rate_limiter)
            try:
                rows = await ladder.top_builds(league_slug, class_name=ladder_class, sort="level")
                if not rows:
                    rows = await ladder.top_builds(league_slug, sort="level")
            finally:
                await ladder.close()

            if rows:
                def _median(key):
                    vals = sorted(r[key] for r in rows if isinstance(r.get(key), (int, float)))
                    return vals[len(vals) // 2] if vals else 0

                top = rows[:10]
                table = [
                    {
                        "name": r.get("name", "?"),
                        "level": r.get("level", 0),
                        "life": r.get("life", 0) or 0,
                        "es": r.get("energyshield", "—"),
                        "ehp": r.get("ehp", "—"),
                        "dps": r.get("dps", "—"),
                    }
                    for r in top
                ]
                table.append({
                    "name": f"{character} (you)", "level": char_data.get("level", 0),
                    "life": life, "es": es, "ehp": f"{ehp_mcp:,}", "dps": "—", "you": True,
                })
                ladder_out = {
                    "cohort": f"top {len(rows)} {ladder_class} builds in {league}",
                    "you": {"level": char_data.get("level", 0), "life": life, "es": es},
                    "median": {"level": _median("level"), "life": _median("life"), "es": _median("energyshield")},
                    "table": table,
                }
        except Exception as e:
            logger.warning(f"Ladder comparison failed: {e}")

        # ---- Skills & gear ----
        skills_out = []
        for setup in char_data.get("skills") or []:
            gems = setup.get("gems") or []
            if not gems:
                continue
            main = gems[0]
            skills_out.append({
                "main": main.get("name", "?"), "lv": main.get("level", 0), "q": main.get("quality", 0),
                "supports": [g.get("name", "?") for g in gems[1:]],
            })

        buckets = {"main": [], "consum": [], "swap": [], "jewel": []}
        for it in char_data.get("items") or []:
            buckets[classify_item_bucket(it.get("slot"))].append(build_item_dict(it))

        strengths, weaknesses = compute_strengths_weaknesses(stats)
        score = compute_score(stats)
        recs = build_recs(stats, nearby_out, skills_out, ladder_out["you"], ladder_out["median"])

        return {
            "character": {
                "name": char_data.get("name") or character,
                "account": char_data.get("account") or account,
                "level": char_data.get("level", 0),
                "classType": char_data.get("class") or "Unknown",
                "ascendancy": char_data.get("ascendancy") or char_data.get("class") or "Unknown",
                "league": char_data.get("league") or league,
            },
            "score": score,
            "stats": {
                "life": life, "es": es, "ward": stats.get("ward", 0) or 0,
                "evasion": stats.get("evasionRating", 0) or 0,
                "evadeChance": stats.get("evadeChance", 0) or 0,
                "ehpMcp": ehp_mcp, "ehpPoeNinja": stats.get("effectiveHealthPool", 0) or 0,
            },
            "resistances": {
                "fire": stats.get("fireResistance", 0) or 0, "cold": stats.get("coldResistance", 0) or 0,
                "lightning": stats.get("lightningResistance", 0) or 0, "chaos": stats.get("chaosResistance", 0) or 0,
                "fireOvercap": stats.get("fireResistanceOverCap", 0) or 0,
                "coldOvercap": stats.get("coldResistanceOverCap", 0) or 0,
                "lightningOvercap": stats.get("lightningResistanceOverCap", 0) or 0,
            },
            "maxHit": {
                "physical": stats.get("physicalMaximumHitTaken", 0) or 0,
                "fire": stats.get("fireMaximumHitTaken", 0) or 0,
                "cold": stats.get("coldMaximumHitTaken", 0) or 0,
                "lightning": stats.get("lightningMaximumHitTaken", 0) or 0,
                "chaos": stats.get("chaosMaximumHitTaken", 0) or 0,
            },
            "strengths": strengths,
            "weaknesses": weaknesses,
            "tree": tree_out,
            "notables": notables_out,
            "smallnodes": smallnodes_out,
            "jewels": buckets["jewel"],
            "nearby": nearby_out,
            "ladder": ladder_out,
            "skills": skills_out,
            "gearMain": buckets["main"],
            "gearConsum": buckets["consum"],
            "gearSwap": buckets["swap"],
            "recs": recs,
            "limits": LIMITS,
            "meta": {"generatedAt": __import__("datetime").datetime.utcnow().isoformat() + "Z", "source": req.url},
        }
    finally:
        try:
            await fetcher.client.aclose()
        except Exception:
            pass
        try:
            await fetcher.ninja_api.client.aclose()
        except Exception:
            pass


@app.get("/api/health")
async def health() -> Dict[str, str]:
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# AI companion — real Gemini API chat about the currently-loaded snapshot.
# Uses a Google AI Studio API key (free tier) rather than the Anthropic API,
# since that's what's actually configured on this deployment. Reads the key
# from GEMINI_API_KEY if set, else ANTHROPIC_API_KEY (kept as a fallback name
# since that's the variable this project's Vercel settings already use —
# despite the name, its value is expected to be a Google AI Studio key here).
# This endpoint never stores or logs that key beyond reading it from the
# environment.
# ---------------------------------------------------------------------------

GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash")
GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta"


def _get_gemini_api_key() -> str:
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise HTTPException(
            status_code=503,
            detail="AI companion isn't configured — add a Google AI Studio API key as the "
            "GEMINI_API_KEY (or ANTHROPIC_API_KEY) environment variable in the Vercel project "
            "settings, then redeploy.",
        )
    return api_key


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    message: str
    history: List[ChatMessage] = []
    snapshot: Dict[str, Any]


def _snapshot_summary(snapshot: Dict[str, Any]) -> str:
    """Condense the ledger snapshot into a compact text block for the system
    prompt — the raw snapshot carries full mod text / raw_data noise that
    would waste tokens without helping the model answer build questions."""
    c = snapshot.get("character", {})
    s = snapshot.get("stats", {})
    r = snapshot.get("resistances", {})
    t = snapshot.get("tree", {})
    ladder = snapshot.get("ladder", {})
    score = snapshot.get("score", {})

    lines = [
        f"Character: {c.get('name')} — {c.get('classType')} / {c.get('ascendancy')}, "
        f"level {c.get('level')}, league {c.get('league')}",
        f"Build score: {score.get('overall')} (tier {score.get('tier')}) — {score.get('note')}",
        f"Life {s.get('life')}, Energy Shield {s.get('es')}, Ward {s.get('ward')}, "
        f"Evasion {s.get('evasion')} ({s.get('evadeChance')}% evade), EHP {s.get('ehpMcp')}",
        f"Resistances — Fire {r.get('fire')}%, Cold {r.get('cold')}%, "
        f"Lightning {r.get('lightning')}%, Chaos {r.get('chaos')}%",
        f"Passive tree — {t.get('totalNodes')} nodes, {t.get('keystonesCount')} keystones, "
        f"{len(snapshot.get('notables', []))} notables, {t.get('jewelSockets')} jewel sockets"
        + (f" (note: {t.get('disconnectNote')})" if t.get("disconnectNote") else ""),
        f"Ladder comparison — {ladder.get('cohort')}",
    ]

    notables = snapshot.get("notables", [])
    if notables:
        lines.append("Notables: " + "; ".join(n.get("name", "?") for n in notables[:15]))

    skills = snapshot.get("skills", [])
    if skills:
        lines.append(
            "Linked skill setups: "
            + "; ".join(f"{sk.get('main')} ({', '.join(sk.get('supports', []))})" for sk in skills[:6])
        )

    gear = snapshot.get("gearMain", [])
    if gear:
        lines.append(
            "Equipped gear: "
            + "; ".join(f"{it.get('slot')}: {it.get('name')} ({it.get('rarity')})" for it in gear)
        )

    strengths = snapshot.get("strengths", [])
    if strengths:
        lines.append("Strengths: " + "; ".join(strengths))

    weaknesses = snapshot.get("weaknesses", [])
    if weaknesses:
        lines.append("Weaknesses: " + "; ".join(w.get("text", w) if isinstance(w, dict) else w for w in weaknesses))

    recs = snapshot.get("recs", [])
    if recs:
        lines.append("Existing recommendations: " + "; ".join(rc.get("title", "?") for rc in recs))

    return "\n".join(lines)


@app.post("/api/chat")
async def chat(req: ChatRequest) -> Dict[str, str]:
    api_key = _get_gemini_api_key()

    system_prompt = (
        "You are a knowledgeable Path of Exile 2 build companion embedded in a build-ledger "
        "app. You're discussing one specific character snapshot with its owner. Be specific, "
        "reference actual numbers from the snapshot below, and keep answers focused and concise "
        "(a few sentences to a short paragraph, using bullet points only when comparing multiple "
        "options). You do not have access to live game data beyond what's in the snapshot, and "
        "this app doesn't compute DPS — say so plainly if asked and you can't back it with data "
        "rather than guessing a number.\n\n"
        f"Current build snapshot:\n{_snapshot_summary(req.snapshot)}"
    )

    # Gemini's generateContent API uses "model" (not "assistant") for the
    # model's own turns, and takes the system prompt as a separate field
    # rather than a message in the list.
    contents = [
        {"role": "model" if m.role == "assistant" else "user", "parts": [{"text": m.content}]}
        for m in req.history
    ]
    contents.append({"role": "user", "parts": [{"text": req.message}]})

    url = f"{GEMINI_API_BASE}/models/{GEMINI_MODEL}:generateContent"
    payload = {
        "system_instruction": {"parts": [{"text": system_prompt}]},
        "contents": contents,
    }

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(url, params={"key": api_key}, json=payload)
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPStatusError as e:
        logger.error(f"Gemini API call failed: {e.response.status_code} {e.response.text}")
        raise HTTPException(
            status_code=502,
            detail=f"AI companion request failed ({e.response.status_code}): {e.response.text[:300]}",
        )
    except Exception as e:
        logger.error(f"Gemini API call failed: {e}")
        raise HTTPException(status_code=502, detail=f"AI companion request failed: {e}")

    candidates = data.get("candidates") or []
    reply = ""
    if candidates:
        parts = candidates[0].get("content", {}).get("parts", [])
        reply = "".join(p.get("text", "") for p in parts)
        if not reply:
            finish_reason = candidates[0].get("finishReason")
            if finish_reason and finish_reason != "STOP":
                reply = f"(No response — Gemini stopped with reason: {finish_reason})"
    if not reply:
        reply = "I couldn't generate a response for that — try rephrasing."

    return {"reply": reply}
