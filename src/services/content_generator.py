"""Service P2 — génération de contenu éditorial i18n (EN + FR + AR).

Architecture :
- 3 appels LLM séquentiels : EN d'abord, puis FR (guidé par concept_name_fr),
  puis AR (ancré sur term.name_ar).
- Sortie AR : strip_harakat post-process + validate (bornes SOFT, ancre, latin).
- Validate-regen loop sur AR uniquement (max_retries appels max). EN/FR : 1 essai.
- Review flags : surface les écarts non bloquants pour l'admin (anchor missing,
  desc retried, etc.).

Bornes SOFT (cf. CLAUDE.md "Validation de contenu") :
- EN/FR : title [40, 60], title_card ≤ 30, description [80, 130]
- AR    : title [25, 55], title_card ≤ 25, description [40, 115]

Routing LLM par défaut : qwen3.5:4b (cf. décision 2026-05-05_decision-llm-finale).
"""
from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import asdict, dataclass, field
from typing import Any

from services.ollama_json import (
    HARAKAT_RE,
    apply_no_think_system,
    call_ollama_sync,
    parse_json_response,
    strip_harakat,
)

logger = logging.getLogger(__name__)


# ─── Bornes SOFT ──────────────────────────────────────────────────────────────
BOUNDS_EN_FR = {
    "title": (40, 60),
    "title_card_max": 30,
    "description": (80, 130),
}
BOUNDS_AR = {
    "title": (25, 55),
    "title_card_max": 25,
    "description": (40, 115),
}

LATIN_RE = re.compile(r"[a-zA-Z]")
AL_PREFIX_RE = re.compile(r"^(ال|وال|فال|بال|كال|لل)")


# ─── Dataclasses ──────────────────────────────────────────────────────────────
@dataclass
class LocaleContent:
    title: str = ""
    title_card: str = ""
    description: str = ""
    keywords: list[str] = field(default_factory=list)


@dataclass
class ContentResult:
    en: LocaleContent
    fr: LocaleContent
    ar: LocaleContent
    review_flags: list[str] = field(default_factory=list)
    retries_ar: int = 0
    latency_ms: int = 0


# ─── Prompt templates ────────────────────────────────────────────────────────
_PROMPT_EN_TPL = """The image subject is: "{concept_name_en}".

Generate editorial content in English for this children's coloring page.

Strict rules:
- Plain prose, no markdown
- No diacritics in any field
- Keywords are short (1-3 words each)

Return ONLY a valid JSON with these fields:
{{"title": "...", "title_card": "...", "description": "...", "keywords": ["...", "...", "...", "...", "..."]}}

Length constraints:
- title : 40 to 60 characters
- title_card : 30 characters maximum
- description : 80 to 130 characters
- keywords : exactly 5 keywords"""


_PROMPT_FR_TPL = """Le sujet de l'image est : "{concept_name_en}" ({concept_name_fr}).

Génère le contenu éditorial en français pour cette page de coloriage pour enfants.

Règles strictes :
- Prose pure, pas de markdown
- Pas de mots anglais dans les champs (traduire ou paraphraser)
- Mots-clés courts (1-3 mots chacun)

Retourne UNIQUEMENT un JSON valide avec ces champs :
{{"title": "...", "title_card": "...", "description": "...", "keywords": ["...", "...", "...", "...", "..."]}}

Contraintes de longueur :
- title : 40 à 60 caractères
- title_card : 30 caractères maximum
- description : 80 à 130 caractères
- keywords : exactement 5 mots-clés"""


_PROMPT_AR_TPL = """Le sujet de l'image est : "{concept_name_en}".
Le thème principal en arabe est : {term_name_ar} ({concept_name_en}).

Génère le contenu éditorial en arabe standard (fusha/MSA) pour cette page de coloriage.

Règles strictes :
- Pas de harakat (signes diacritiques)
- Pas de caractères latins
- Arabe standard uniquement, pas de dialecte
- Le contenu doit ré-utiliser l'ancre AR ci-dessus comme racine lexicale du sujet

Retourne UNIQUEMENT un JSON valide avec ces champs :
{{"title": "...", "title_card": "...", "description": "...", "keywords": ["...", "...", "...", "...", "..."]}}

Contraintes de longueur :
- title : 25 à 55 caractères
- title_card : 25 caractères maximum
- description : 40 à 115 caractères
- keywords : exactement 5 mots-clés"""


# ─── Validation helpers ──────────────────────────────────────────────────────
def _normalize_for_anchor(s: str) -> str:
    """Normalise pour matching anchor : enlève harakat éventuels, tatweel."""
    return HARAKAT_RE.sub("", (s or "").replace("ـ", "")).strip()


def anchor_present(term_name_ar: str, *texts: str) -> bool:
    """Vérifie si l'ancre (ou variante morphologique) apparaît dans un des textes."""
    haystack = " ".join(_normalize_for_anchor(t) for t in texts if t)
    needle = _normalize_for_anchor(term_name_ar)
    if not needle or not haystack:
        return False
    if needle in haystack:
        return True
    bare = AL_PREFIX_RE.sub("", needle).strip()
    if bare and bare in haystack:
        return True
    for token in needle.split():
        token_bare = AL_PREFIX_RE.sub("", token).strip()
        if len(token_bare) >= 3 and token_bare in haystack:
            return True
    if len(bare) >= 4 and bare[:4] in haystack:
        return True
    return False


def _has_latin(text: str) -> bool:
    return bool(LATIN_RE.search(text or ""))


def _bounds_violations(content: LocaleContent, bounds: dict) -> list[str]:
    issues = []
    t_min, t_max = bounds["title"]
    if not (t_min <= len(content.title) <= t_max):
        issues.append(f"title_len={len(content.title)} not in [{t_min},{t_max}]")
    if len(content.title_card) > bounds["title_card_max"]:
        issues.append(f"title_card_len={len(content.title_card)} > {bounds['title_card_max']}")
    d_min, d_max = bounds["description"]
    if not (d_min <= len(content.description) <= d_max):
        issues.append(f"description_len={len(content.description)} not in [{d_min},{d_max}]")
    if len(content.keywords) != 5:
        issues.append(f"keywords_count={len(content.keywords)} (expected 5)")
    return issues


def validate_ar(content: LocaleContent, term_name_ar: str) -> tuple[bool, list[str], list[str]]:
    """Retourne (ok, hard_issues, soft_issues).

    hard_issues : bornes / latin → déclenche regen.
    soft_issues : ancre absente → ne déclenche pas regen seul mais accumulé.
    """
    hard = _bounds_violations(content, BOUNDS_AR)
    if any(_has_latin(s) for s in [content.title, content.title_card, content.description, *content.keywords]):
        hard.append("latin_chars_in_ar")
    soft: list[str] = []
    if not anchor_present(term_name_ar, content.title, content.description):
        soft.append("ar_anchor_missing")
    return (not hard, hard, soft)


# ─── Generation per locale ───────────────────────────────────────────────────
def _to_locale_content(parsed: dict) -> LocaleContent:
    title = (parsed.get("title") or "").strip()
    card = (parsed.get("title_card") or "").strip()
    desc = (parsed.get("description") or "").strip()
    kw = parsed.get("keywords") or []
    kw_strs = [str(k).strip() for k in kw if isinstance(k, (str, int, float))] if isinstance(kw, list) else []
    return LocaleContent(title=title, title_card=card, description=desc, keywords=kw_strs)


def _gen_locale(prompt: str, model: str, temperature: float = 0.0, timeout: int = 180) -> LocaleContent:
    sys_p = apply_no_think_system(model, "")
    raw = call_ollama_sync(prompt, sys_p, model=model, temperature=temperature, timeout=timeout)
    parsed = parse_json_response(raw)
    if not isinstance(parsed, dict):
        raise ValueError(f"LLM did not return a JSON object: type={type(parsed).__name__}")
    return _to_locale_content(parsed)


def _gen_ar_with_strip(prompt: str, model: str, temperature: float = 0.0, timeout: int = 180) -> LocaleContent:
    """Génère AR + applique strip_harakat sur tous les champs."""
    content = _gen_locale(prompt, model, temperature, timeout)
    return LocaleContent(
        title=strip_harakat(content.title),
        title_card=strip_harakat(content.title_card),
        description=strip_harakat(content.description),
        keywords=[strip_harakat(k) for k in content.keywords],
    )


# ─── Main entrypoint ─────────────────────────────────────────────────────────
def generate_content(
    concept_name_en: str,
    concept_name_fr: str,
    term_name_ar: str,
    model: str = "qwen3.5:4b",
    max_retries: int = 3,
) -> ContentResult:
    """Génère le contenu éditorial i18n EN + FR + AR pour un concept.

    EN et FR : 1 appel chacun, pas de regen (les bornes EN/FR sont indicatives,
    rejet ne pas viable sans dégrader fortement le débit prod).
    AR : appel + validate-regen jusqu'à max_retries sur les bornes / latin.
        L'absence d'ancre ne déclenche pas regen seul mais est cumulée :
        si l'ancre manque sur 2+ retries, flag ``ar_anchor_missing``.
    """
    t0 = time.time()
    review_flags: list[str] = []

    # 1. EN
    prompt_en = _PROMPT_EN_TPL.format(concept_name_en=concept_name_en)
    en_content = _gen_locale(prompt_en, model)

    # 2. FR
    prompt_fr = _PROMPT_FR_TPL.format(concept_name_en=concept_name_en, concept_name_fr=concept_name_fr)
    fr_content = _gen_locale(prompt_fr, model)

    # 3. AR — avec regen loop
    prompt_ar = _PROMPT_AR_TPL.format(concept_name_en=concept_name_en, term_name_ar=term_name_ar)
    retries_ar = 0
    anchor_failures = 0
    last_hard_issues: list[str] = []
    ar_content: LocaleContent = LocaleContent()

    for attempt in range(max_retries):
        ar_content = _gen_ar_with_strip(prompt_ar, model)
        ok, hard, soft = validate_ar(ar_content, term_name_ar)
        last_hard_issues = hard
        if "ar_anchor_missing" in soft:
            anchor_failures += 1
        if ok:
            break
        retries_ar = attempt + 1
        # Si hard issues persist : on reboucle. Si purement soft (juste anchor),
        # on s'arrête pas sur soft seul — mais on a déjà sorti via ``ok`` plus haut.

    # Flags review
    if last_hard_issues:
        review_flags.append("ar_hard_issues:" + ",".join(last_hard_issues))
    if retries_ar > 0:
        # détailler quel champ a forcé les retries
        review_flags.append(f"ar_retried_{retries_ar}x")
    if anchor_failures >= 2:
        review_flags.append("ar_anchor_missing")
    elif anchor_failures == 1 and not anchor_present(term_name_ar, ar_content.title, ar_content.description):
        # Échec anchor au 1er essai et toujours absent au final → flag aussi
        review_flags.append("ar_anchor_missing")

    # EN / FR : flagger les violations bornes (sans regen — coût latence trop
    # élevé pour les locales non-AR ; les écarts sont surfacés à l'admin via
    # review_flags pour traitement en file d'exception).
    en_issues = _bounds_violations(en_content, BOUNDS_EN_FR)
    if en_issues:
        review_flags.append("en_bounds:" + ",".join(en_issues))
    fr_issues = _bounds_violations(fr_content, BOUNDS_EN_FR)
    if fr_issues:
        review_flags.append("fr_bounds:" + ",".join(fr_issues))
    # Note : on ne flagge pas la présence de caractères latins en FR (le français
    # est en script latin par nature). Pour détecter des mots anglais non traduits,
    # il faudrait un check lexical, hors scope ici.

    return ContentResult(
        en=en_content,
        fr=fr_content,
        ar=ar_content,
        review_flags=review_flags,
        retries_ar=retries_ar,
        latency_ms=int((time.time() - t0) * 1000),
    )


def content_result_to_dict(r: ContentResult) -> dict[str, Any]:
    return {
        "en": asdict(r.en),
        "fr": asdict(r.fr),
        "ar": asdict(r.ar),
        "review_flags": r.review_flags,
        "retries_ar": r.retries_ar,
        "latency_ms": r.latency_ms,
    }
