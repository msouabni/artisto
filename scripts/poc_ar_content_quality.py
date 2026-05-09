"""POC jetable : Ollama génère-t-il de l'arabe naturel pour du contenu éditorial coloriage ?

Pour 10 concepts FR, demande à qwen2.5:7b un JSON {title, title_card, description, keywords[]}
en arabe. Affiche le résultat brut + longueurs + validité JSON. Pas de jugement de qualité
côté script — évaluation humaine.

Usage :
    python scripts/poc_ar_content_quality.py
"""
from __future__ import annotations

import io
import json
import sys
import time
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
else:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from services.ollama_json import (  # noqa: E402
    OLLAMA_MODEL,
    call_ollama_sync,
    parse_json_response,
)

CONCEPTS_FR = [
    "lion dans la savane",
    "chat dans une bibliothèque",
    "papillon coloré",
    "éléphant avec ses petits",
    "poisson dans l'océan",
    "renard dans la forêt",
    "lapin blanc",
    "oiseau sur une branche",
    "tortue sur un rocher",
    "dauphin qui saute",
]

PROMPT_TPL = """Tu génères du contenu éditorial en arabe pour un site de coloriage pour enfants (4-10 ans).
Pour ce concept : "{concept}"
Génère en JSON :
{{
  "title": "titre en arabe (40-60 caractères)",
  "title_card": "titre court en arabe (max 30 caractères)",
  "description": "description en arabe, prose pure sans markdown (80-130 caractères)",
  "keywords": ["mot-clé 1", "mot-clé 2", "mot-clé 3"]
}}
Réponds uniquement avec le JSON, rien d'autre."""


def _check_lengths(parsed: dict) -> dict[str, str]:
    """Mesure et catégorise les longueurs vs bornes attendues."""
    out: dict[str, str] = {}
    title = parsed.get("title", "")
    out["title"] = f"{len(title)} chars"
    if not (40 <= len(title) <= 60):
        out["title"] += f" (HORS [40,60])"

    card = parsed.get("title_card", "")
    out["title_card"] = f"{len(card)} chars"
    if len(card) > 30:
        out["title_card"] += f" (>30)"

    desc = parsed.get("description", "")
    out["description"] = f"{len(desc)} chars"
    if not (80 <= len(desc) <= 130):
        out["description"] += f" (HORS [80,130])"

    kw = parsed.get("keywords", [])
    out["keywords"] = f"{len(kw)} items"
    if isinstance(kw, list):
        item_lens = [len(k) for k in kw if isinstance(k, str)]
        if item_lens:
            out["keywords"] += f" (lens={item_lens})"

    return out


def main() -> int:
    print(f"Modèle : {OLLAMA_MODEL}  ·  T=0  ·  {len(CONCEPTS_FR)} concepts\n")
    print("=" * 100)

    for idx, concept in enumerate(CONCEPTS_FR, 1):
        prompt = PROMPT_TPL.format(concept=concept)
        print(f"\n[{idx}/{len(CONCEPTS_FR)}] CONCEPT FR : {concept}")
        print("-" * 100)
        t0 = time.time()
        try:
            raw = call_ollama_sync(prompt=prompt, system="", temperature=0.0)
            dt = time.time() - t0
        except Exception as exc:
            print(f"  ❌ Erreur Ollama : {type(exc).__name__}: {exc}")
            continue

        print(f"  RAW OUTPUT ({dt:.1f}s, {len(raw)} chars) :")
        print(f"  {raw}")
        print()

        try:
            parsed = parse_json_response(raw)
            json_ok = isinstance(parsed, dict)
        except Exception as exc:
            print(f"  ❌ JSON non parsable : {type(exc).__name__}: {exc}")
            continue

        if not json_ok:
            print(f"  ❌ JSON parsé n'est pas un objet : {type(parsed).__name__}")
            continue

        print(f"  JSON PARSÉ :")
        try:
            pretty = json.dumps(parsed, ensure_ascii=False, indent=2)
            for line in pretty.splitlines():
                print(f"    {line}")
        except Exception:
            print(f"    {parsed!r}")

        print(f"\n  LONGUEURS :")
        for field, info in _check_lengths(parsed).items():
            print(f"    {field:<14} : {info}")

    print()
    print("=" * 100)
    return 0


if __name__ == "__main__":
    sys.exit(main())
