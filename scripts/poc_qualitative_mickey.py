"""POC qualitatif — qwen3.5:4b sur thème "Mickey Mouse".

Étape 1 : 20 concepts (sujets) via prompt generate_concepts.
Étape 2 : pour les 5 premiers concepts, générer le contenu éditorial EN + FR + AR.
Étape 3 : rapport lisible humain (sans métriques auto, jugement laissé au lecteur).

Usage :
    python scripts/poc_qualitative_mickey.py
"""
from __future__ import annotations

import io
import json
import re
import sys
import time
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
else:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(PROJECT_ROOT / ".env")

import yaml  # noqa: E402

from services.ollama_json import (  # noqa: E402
    apply_no_think_system,
    call_ollama_sync,
    parse_json_response,
)

REPORT_JSON = PROJECT_ROOT / "docs" / "reports" / "2026-05-05_poc-qualitative-mickey.json"
REPORT_MD = PROJECT_ROOT / "docs" / "reports" / "2026-05-05_poc-qualitative-mickey.md"
IMAGE_PROMPTS = PROJECT_ROOT / "prompts" / "image_prompts.yaml"

MODEL = "qwen3.5:4b"
THEME = "Mickey Mouse"
TERM_AR = "ميكي ماوس"   # ancre AR
TERM_EN = "Mickey Mouse"
N_CONCEPTS = 20
N_DETAILED = 5

# Bornes SOFT par locale (cf. CLAUDE.md "Validation de contenu")
BOUNDS = {
    "en": {"title": [40, 60], "title_card": [None, 30], "description": [80, 130]},
    "fr": {"title": [40, 60], "title_card": [None, 30], "description": [80, 130]},
    "ar": {"title": [25, 55], "title_card": [None, 25], "description": [40, 100]},
}

# Codepoints explicites (RTL trap résolu)
HARAKAT_RE = re.compile(r"[ؐ-ًؚ-ٟ]")  # même regex que poc_qwen35_volume — passée en escape ci-dessous via Python :
HARAKAT_RE = re.compile("[ؐ-ًؚ-ٟ]")


def strip_harakat(s: str) -> str:
    return HARAKAT_RE.sub("", s or "")


# ─── Étape 1 : generate_concepts ───
def load_concepts_template() -> dict:
    return yaml.safe_load(IMAGE_PROMPTS.read_text(encoding="utf-8"))["prompts"]["generate_concepts"]


def generate_concepts(theme: str, count: int) -> list[dict]:
    tpl = load_concepts_template()
    sys_p = apply_no_think_system(MODEL, tpl["system"])
    user_p = tpl["user"].format(theme=theme, taxonomy_context="", count=count)
    raw = call_ollama_sync(user_p, sys_p, model=MODEL, temperature=0.5, timeout=180)
    parsed = parse_json_response(raw)
    if isinstance(parsed, dict):
        for v in parsed.values():
            if isinstance(v, list):
                parsed = v
                break
    return parsed if isinstance(parsed, list) else []


# ─── Étape 2 : génération contenu éditorial par locale ───
PROMPT_EN_TPL = """The image subject is: "{concept_en}".

Generate editorial content in English for this children's coloring page.

Strict rules:
- Plain prose, no markdown
- No diacritics in any field

Return ONLY a valid JSON with these fields:
{{"title": "...", "title_card": "...", "description": "...", "keywords": ["...", "...", "...", "...", "..."]}}

Length constraints:
- title : 40 to 60 characters
- title_card : 30 characters maximum
- description : 80 to 130 characters
- keywords : exactly 5 keywords"""

PROMPT_FR_TPL = """Le sujet de l'image est : "{concept_en}" ({concept_fr}).

Génère le contenu éditorial en français pour cette page de coloriage pour enfants.

Règles strictes :
- Prose pure, pas de markdown
- Pas de caractères latins parasites

Retourne UNIQUEMENT un JSON valide avec ces champs :
{{"title": "...", "title_card": "...", "description": "...", "keywords": ["...", "...", "...", "...", "..."]}}

Contraintes de longueur :
- title : 40 à 60 caractères
- title_card : 30 caractères maximum
- description : 80 à 130 caractères
- keywords : exactement 5 mots-clés"""

PROMPT_AR_TPL = """Le sujet de l'image est : "{concept_en}".
Le thème principal en arabe est : {term_ar} ({term_en}).

Génère le contenu éditorial en arabe standard (fusha/MSA) pour cette page de coloriage.

Règles strictes :
- Pas de harakat (signes diacritiques)
- Pas de caractères latins
- Arabe standard uniquement, pas de dialecte

Retourne UNIQUEMENT un JSON valide avec ces champs :
{{"title": "...", "title_card": "...", "description": "...", "keywords": ["...", "...", "...", "...", "..."]}}

Contraintes de longueur :
- title : 30 à 50 caractères
- title_card : 25 caractères maximum
- description : 55 à 90 caractères
- keywords : exactement 5 mots-clés"""


def gen_locale(concept: dict, locale: str) -> dict:
    if locale == "en":
        prompt = PROMPT_EN_TPL.format(concept_en=concept["name_en"])
    elif locale == "fr":
        prompt = PROMPT_FR_TPL.format(concept_en=concept["name_en"], concept_fr=concept.get("name_fr", ""))
    elif locale == "ar":
        prompt = PROMPT_AR_TPL.format(concept_en=concept["name_en"], term_ar=TERM_AR, term_en=TERM_EN)
    else:
        raise ValueError(f"locale {locale}")
    sys_p = apply_no_think_system(MODEL, "")
    t0 = time.time()
    try:
        raw = call_ollama_sync(prompt, sys_p, model=MODEL, temperature=0.0, timeout=120)
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {exc}", "latency_s": time.time() - t0}
    dt = time.time() - t0
    try:
        parsed = parse_json_response(raw)
    except Exception as exc:
        return {"raw": raw, "json_ok": False, "json_error": str(exc), "latency_s": dt}
    if not isinstance(parsed, dict):
        return {"raw": raw, "json_ok": False, "json_error": "not a dict", "latency_s": dt}

    title = (parsed.get("title") or "").strip()
    card = (parsed.get("title_card") or "").strip()
    desc = (parsed.get("description") or "").strip()
    kw = parsed.get("keywords") or []
    kw_strs = [k for k in kw if isinstance(k, str)] if isinstance(kw, list) else []

    if locale == "ar":
        # post-process strip harakat (recommandation POC volume)
        title_pre = title
        desc_pre = desc
        card_pre = card
        kw_pre = list(kw_strs)
        title = strip_harakat(title)
        card = strip_harakat(card)
        desc = strip_harakat(desc)
        kw_strs = [strip_harakat(k) for k in kw_strs]
        return {
            "json_ok": True, "raw": raw, "latency_s": dt,
            "title": title, "title_card": card, "description": desc, "keywords": kw_strs,
            "title_len": len(title), "title_card_len": len(card),
            "description_len": len(desc), "keywords_count": len(kw_strs),
            "harakat_stripped": (title != title_pre or desc != desc_pre or card != card_pre or kw_strs != kw_pre),
            "title_pre_strip": title_pre, "description_pre_strip": desc_pre,
        }

    return {
        "json_ok": True, "raw": raw, "latency_s": dt,
        "title": title, "title_card": card, "description": desc, "keywords": kw_strs,
        "title_len": len(title), "title_card_len": len(card),
        "description_len": len(desc), "keywords_count": len(kw_strs),
    }


def main() -> int:
    print("=" * 100)
    print(f'POC qualitatif Mickey Mouse — {MODEL} — 20 concepts + 5 détaillés (EN/FR/AR)')
    print("=" * 100)

    print(f"\n[Étape 1] generate_concepts theme={THEME!r} count={N_CONCEPTS}")
    t0 = time.time()
    concepts = generate_concepts(THEME, N_CONCEPTS)
    dt = time.time() - t0
    print(f"  → {len(concepts)} concepts en {dt:.1f}s")
    for i, c in enumerate(concepts, 1):
        print(f"  [{i:>2}] {c.get('name_en', '?'):<60} | {c.get('name_fr', '?')}")

    print(f"\n[Étape 2] Génération i18n EN+FR+AR pour les {N_DETAILED} premiers concepts")
    detailed = []
    for i, concept in enumerate(concepts[:N_DETAILED], 1):
        print(f"\n  --- {i}/{N_DETAILED}: {concept.get('name_en')} ---")
        record = {"concept": concept, "locales": {}}
        for locale in ("en", "fr", "ar"):
            print(f"    [{locale}] …", end=" ", flush=True)
            res = gen_locale(concept, locale)
            record["locales"][locale] = res
            if res.get("json_ok"):
                print(f"OK title={res['title_len']}c desc={res['description_len']}c ({res['latency_s']:.1f}s)")
            else:
                print(f"FAIL {res.get('error') or res.get('json_error')}")
        detailed.append(record)

    payload = {
        "poc": "qualitative-mickey",
        "date": "2026-05-05",
        "model": MODEL,
        "theme": THEME,
        "term_ar": TERM_AR,
        "term_en": TERM_EN,
        "concepts": concepts,
        "detailed_first_n": detailed,
    }
    REPORT_JSON.parent.mkdir(parents=True, exist_ok=True)
    REPORT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"\nJSON brut → {REPORT_JSON}")

    # ─── Étape 3 : rapport markdown lisible ───
    md = []
    md.append(f"# POC qualitatif — Mickey Mouse ({MODEL})")
    md.append("Date : 2026-05-05")
    md.append("")
    md.append("## Contexte")
    md.append(f"Test qualitatif de **{MODEL}** en conditions réelles sur le thème *\"{THEME}\"*. Étape 1 : génération de **{N_CONCEPTS} sujets** (concepts) via le template `generate_concepts` du projet. Étape 2 : génération du contenu éditorial complet (title / title_card / description / keywords) dans les **3 locales (EN / FR / AR)** pour les **{N_DETAILED} premiers concepts**, avec ancrage AR sur `{TERM_AR}` ({TERM_EN}) et strip harakat post-process. **Aucune métrique automatique** — la qualité linguistique est laissée à l'évaluation humaine.")
    md.append("")
    md.append(f"## Étape 1 — {len(concepts)} sujets de coloriage générés")
    md.append("")
    md.append("| # | name_en | name_fr |")
    md.append("|---|---|---|")
    for i, c in enumerate(concepts, 1):
        nen = c.get("name_en", "—")
        nfr = c.get("name_fr", "—")
        md.append(f"| {i} | {nen} | {nfr} |")
    md.append("")

    md.append(f"## Étape 2 — contenu éditorial i18n complet pour les {N_DETAILED} premiers")
    md.append("")
    md.append("Bornes SOFT pipeline :")
    md.append("- **EN / FR** : title [40, 60] · title_card ≤ 30 · description [80, 130]")
    md.append("- **AR** : title [25, 55] · title_card ≤ 25 · description [40, 100] · post-process strip harakat")
    md.append("")

    for i, rec in enumerate(detailed, 1):
        c = rec["concept"]
        md.append(f"### {i}. {c.get('name_en')} ({c.get('name_fr')})")
        md.append("")
        md.append(f"_Concept description EN_ : {c.get('description_en', '—')}")
        md.append("")

        # Tableau côte à côte des 3 locales
        md.append("| Champ | EN | FR | AR |")
        md.append("|---|---|---|---|")
        for field in ("title", "title_card", "description"):
            cells = []
            for loc in ("en", "fr", "ar"):
                rl = rec["locales"].get(loc, {})
                if not rl.get("json_ok"):
                    cells.append(f"❌ {rl.get('error') or rl.get('json_error') or 'fail'}")
                else:
                    val = rl.get(field, "")
                    n = len(val)
                    cells.append(f"`{val}` *({n}c)*")
            md.append(f"| **{field}** | {cells[0]} | {cells[1]} | {cells[2]} |")
        # keywords sur une ligne dédiée
        kw_cells = []
        for loc in ("en", "fr", "ar"):
            rl = rec["locales"].get(loc, {})
            if not rl.get("json_ok"):
                kw_cells.append("❌")
            else:
                kw = rl.get("keywords", [])
                kw_cells.append(", ".join(f"`{k}`" for k in kw))
        md.append(f"| **keywords** | {kw_cells[0]} | {kw_cells[1]} | {kw_cells[2]} |")
        md.append("")

        # Note harakat strip
        ar_rl = rec["locales"].get("ar", {})
        if ar_rl.get("json_ok") and ar_rl.get("harakat_stripped"):
            md.append("> ℹ Harakat détectés et strippés en post-process (cf. recommandation `2026-05-05_poc-qwen35-volume.md`).")
            md.append(f"> - title pré-strip : `{ar_rl.get('title_pre_strip')}`")
            md.append(f"> - desc pré-strip  : `{ar_rl.get('description_pre_strip')}`")
            md.append("")

    md.append("## Annexes")
    md.append("")
    md.append(f"- Données brutes : `2026-05-05_poc-qualitative-mickey.json` (concepts + locales + harakat avant/après strip)")
    md.append(f"- Script : `scripts/poc_qualitative_mickey.py`")
    md.append(f"- Modèle : `{MODEL}` (T=0.5 pour concepts, T=0 pour locales)")
    md.append(f"- Bornes : cf. `CLAUDE.md` section *Validation de contenu*")

    REPORT_MD.write_text("\n".join(md), encoding="utf-8")
    print(f"Rapport MD → {REPORT_MD}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
