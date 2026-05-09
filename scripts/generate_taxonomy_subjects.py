"""Génération de sujets d'image par feuille de taxonomie via qwen3.5:4b.

Pour chaque feuille (terme sans enfants) de `data/taxonomy_universal_v0.json`,
demande à `qwen3.5:4b` de produire 6 sujets concrets dessinables, chacun
classifié dans un tier de routage (simple_inanimate / simple_animated /
anatomy / mandala / educational).

Output : `data/taxonomy_subjects.json` (écriture atomique via .tmp + replace).

Usage :
    python scripts/generate_taxonomy_subjects.py
"""
from __future__ import annotations

import io
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
else:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(PROJECT_ROOT / ".env")

import os

import httpx  # noqa: E402

from services.ollama_json import parse_json_response  # noqa: E402

TAXONOMY_JSON = PROJECT_ROOT / "data" / "taxonomy_universal_v0.json"
OUTPUT_JSON = PROJECT_ROOT / "data" / "taxonomy_subjects.json"
OUTPUT_TMP = OUTPUT_JSON.with_suffix(".json.tmp")

MODEL = "qwen3.5:4b"
TEMPERATURE = 0.7
TIMEOUT = 180
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")


def call_qwen35_direct(user: str, system: str) -> str:
    """Appel HTTP direct à Ollama avec ``think: false`` natif (qwen3.5+).

    Bypass de ``services.ollama_json.call_ollama_sync`` parce que la version
    actuelle de ce module ne propage pas ``think: false`` pour qwen3.5+, ce
    qui fait passer ~60 s en mode thinking et vide souvent le contexte
    avant la sortie JSON. Ici on désactive explicitement le thinking.
    """
    payload = {
        "model": MODEL,
        "system": system,
        "prompt": user,
        "stream": False,
        "options": {"temperature": TEMPERATURE},
        "think": False,
    }
    with httpx.Client(timeout=float(TIMEOUT)) as c:
        r = c.post(f"{OLLAMA_BASE_URL}/api/generate", json=payload)
        r.raise_for_status()
        data = r.json()
    if "error" in data and "response" not in data:
        raise RuntimeError(f"Ollama erreur modèle : {data['error']}")
    return data.get("response", "")

VALID_TIERS = {"simple_inanimate", "simple_animated", "anatomy", "mandala", "educational"}

SYSTEM_PROMPT = (
    "You are a creative assistant for a children's coloring book platform. "
    "Generate specific, child-friendly image subjects."
)

USER_TEMPLATE = (
    "Category: {leaf_name_en} (parent: {parent_name_en})\n"
    "Generate exactly 6 specific subjects suitable for children's coloring pages.\n"
    "Each subject must be a concrete, drawable thing (not abstract).\n"
    "For each subject also classify its routing tier:\n"
    "- 'simple_inanimate': objects, plants, tools, vehicles with no living figures\n"
    "- 'simple_animated': animals, creatures without complex anatomy poses\n"
    "- 'anatomy': human figures, characters in action poses (sport, jobs, dance)\n"
    "- 'mandala': mandala or geometric patterns\n"
    "- 'educational': letters, numbers, shapes, maps\n"
    "Reply ONLY with valid JSON array:\n"
    '[\n'
    '  {{"name_en": "...", "tier": "...", "description": "one sentence"}},\n'
    "  ...\n"
    "]"
)


def walk_leaves(nodes: list, parent_name_en: str | None = None) -> list[dict]:
    """Parcourt les nœuds et retourne uniquement les feuilles (pas d'enfants)."""
    leaves: list[dict] = []
    for n in nodes:
        if not isinstance(n, dict):
            continue
        children = n.get("children") or []
        if not children:
            leaves.append({
                "id": n.get("id"),
                "slug": n.get("slug"),
                "name_en": n.get("name_en") or n.get("name_fr") or n.get("id"),
                "parent_name_en": parent_name_en or "(root)",
            })
        else:
            leaves.extend(walk_leaves(children, n.get("name_en")))
    return leaves


def load_leaves() -> list[dict]:
    data = json.loads(TAXONOMY_JSON.read_text(encoding="utf-8"))
    out: list[dict] = []
    for v in data.get("vocabularies") or []:
        out.extend(walk_leaves(v.get("terms") or []))
    return out


def call_llm_for_leaf(leaf: dict) -> tuple[list[dict] | None, str | None, str]:
    """Retourne (subjects | None, error | None, raw_response)."""
    user = USER_TEMPLATE.format(
        leaf_name_en=leaf["name_en"],
        parent_name_en=leaf["parent_name_en"],
    )
    try:
        raw = call_qwen35_direct(user, SYSTEM_PROMPT)
    except Exception as exc:
        return None, f"ollama: {type(exc).__name__}: {exc}", ""

    try:
        parsed = parse_json_response(raw)
    except Exception as exc:
        return None, f"parse: {exc}", raw

    # Le modèle peut wrapper dans un dict
    if isinstance(parsed, dict):
        for key in ("subjects", "items", "results", "data"):
            if isinstance(parsed.get(key), list):
                parsed = parsed[key]
                break
        else:
            return None, f"parsed dict sans clé liste reconnue (clés: {list(parsed.keys())[:5]})", raw

    if not isinstance(parsed, list):
        return None, f"parsed n'est pas une liste : {type(parsed).__name__}", raw

    cleaned: list[dict] = []
    for item in parsed:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name_en") or "").strip()
        tier = str(item.get("tier") or "").strip().lower()
        desc = str(item.get("description") or "").strip()
        if not name:
            continue
        if tier not in VALID_TIERS:
            tier = "simple_inanimate"  # fallback prudent
        cleaned.append({"name_en": name, "tier": tier, "description": desc})

    if not cleaned:
        return None, "aucun sujet valide après nettoyage", raw
    return cleaned, None, raw


def atomic_write(path: Path, tmp: Path, data: dict) -> None:
    tmp.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    tmp.replace(path)


def main() -> int:
    print("=" * 100, flush=True)
    print(f"Génération sujets taxonomie — modèle {MODEL} (T={TEMPERATURE})", flush=True)
    print("=" * 100, flush=True)

    leaves = load_leaves()
    print(f"\nFeuilles trouvées : {len(leaves)} (depuis {TAXONOMY_JSON.name})", flush=True)
    print(f"Output cible      : {OUTPUT_JSON.relative_to(PROJECT_ROOT)} (atomique via .tmp)", flush=True)
    print(flush=True)

    all_subjects: list[dict] = []
    leaves_processed = 0
    leaves_failed: list[dict] = []

    for i, leaf in enumerate(leaves, 1):
        print(f"Processing [{i}/{len(leaves)}] {leaf['name_en']}…", flush=True, end=" ")
        t0 = time.time()
        subjects, err, raw = call_llm_for_leaf(leaf)
        dt = time.time() - t0
        if err is not None:
            print(f"❌ {err} ({dt:.1f}s)", flush=True)
            leaves_failed.append({"leaf": leaf, "error": err, "raw_first_200": (raw or "")[:200]})
            continue

        # Cap à 6 (le modèle peut en renvoyer plus, on coupe ; ou moins, on prend ce qu'il y a)
        subjects = subjects[:6]
        for s in subjects:
            all_subjects.append({
                "leaf_id": leaf["id"],
                "leaf_name_en": leaf["name_en"],
                "parent_name_en": leaf["parent_name_en"],
                "name_en": s["name_en"],
                "tier": s["tier"],
                "description": s["description"],
            })
        leaves_processed += 1
        # Distribution rapide
        tier_counts: dict[str, int] = {}
        for s in subjects:
            tier_counts[s["tier"]] = tier_counts.get(s["tier"], 0) + 1
        print(f"✅ {len(subjects)} sujets ({tier_counts}) {dt:.1f}s", flush=True)

        # Persist incrémental après chaque feuille (utile si le run plante en cours)
        partial = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "taxonomy_version": "universal_v0",
            "model": MODEL,
            "temperature": TEMPERATURE,
            "leaves_total": len(leaves),
            "leaves_processed": leaves_processed,
            "leaves_failed_count": len(leaves_failed),
            "total_subjects": len(all_subjects),
            "subjects": all_subjects,
            "failures": leaves_failed,
        }
        atomic_write(OUTPUT_JSON, OUTPUT_TMP, partial)

    # ── Résumé final ──
    final = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "taxonomy_version": "universal_v0",
        "model": MODEL,
        "temperature": TEMPERATURE,
        "leaves_total": len(leaves),
        "leaves_processed": leaves_processed,
        "leaves_failed_count": len(leaves_failed),
        "total_subjects": len(all_subjects),
        "subjects": all_subjects,
        "failures": leaves_failed,
    }
    atomic_write(OUTPUT_JSON, OUTPUT_TMP, final)

    tier_global: dict[str, int] = {}
    for s in all_subjects:
        tier_global[s["tier"]] = tier_global.get(s["tier"], 0) + 1

    print(flush=True)
    print("─── Résumé ────────────────────────────────────────────────────────────────────", flush=True)
    print(f"Feuilles traitées : {leaves_processed}/{len(leaves)}  (échecs : {len(leaves_failed)})", flush=True)
    print(f"Sujets générés    : {len(all_subjects)}", flush=True)
    print("Distribution par tier :", flush=True)
    for tier in sorted(tier_global, key=lambda t: -tier_global[t]):
        print(f"  {tier:<22} : {tier_global[tier]}", flush=True)
    if leaves_failed:
        print(flush=True)
        print("Feuilles en échec :", flush=True)
        for f in leaves_failed:
            print(f"  - {f['leaf']['id']:<25} {f['leaf']['name_en']:<25} → {f['error']}", flush=True)
    print(flush=True)
    print(f"Output : {OUTPUT_JSON.relative_to(PROJECT_ROOT)}", flush=True)
    return 0 if leaves_processed == len(leaves) else 1


if __name__ == "__main__":
    sys.exit(main())
