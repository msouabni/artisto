"""Helpers de slugification pour le contrat MEP v0 / Alwan Books.

Deux fonctions publiques :

- ``r2_slug(name_en)`` : identifiant canonique du master image dans le bucket R2.
  ASCII kebab strict, mirror de la regex Zod côté Astro
  (``^[a-z0-9]+(-[a-z0-9]+)*$``).

- ``post_slug(name, locale)`` : slug par locale pour les fichiers Post
  (``src/content/posts/<locale>/<slug>.md``). ASCII kebab dans toutes les locales.
  Pour ``ar`` : translittération via ``docs/xchange/ar_slug_corpus.csv``
  (phrase puis mot) avec fallback table char-par-char.

Référence contrat : ``docs/xchange/PIPELINE-CONTRACT.md`` §3 et §5.
Routing LLM / regex harakat : voir ``CLAUDE.md`` §Routing LLM (codepoints
explicites ``[ؐ-ًؚ-ٟ]``, version inline littérale sensible au RTL trap au
copier-coller — on utilise donc les escapes ``\\u0610-\\u061A\\u064B-\\u065F``
ci-dessous, équivalents et stables).

Aucune dépendance externe (stdlib uniquement).
"""
from __future__ import annotations

import csv
import re
import unicodedata
from pathlib import Path

# ────────────────────────────────────────────────────────────────────────────
# Regex publiques (mirror Zod côté Astro)
# ────────────────────────────────────────────────────────────────────────────

#: Regex stricte ASCII kebab — mirror du Zod côté ``rimalab-v2``.
#: ``^[a-z0-9]+(-[a-z0-9]+)*$`` : groupes alphanumériques séparés par tirets
#: simples, pas de tiret en bord, pas de tiret double.
ASCII_KEBAB_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")

#: Regex r2_slug interne : interdit le départ par un chiffre.
#: ``r2_slug`` réutilise cette contrainte (cf. brief §spec : "commence par
#: chiffre" → raise ValueError).
_R2_SLUG_RE = re.compile(r"^[a-z][a-z0-9-]*[a-z0-9]$")

#: Harakat arabes (signes diacritiques) — codepoints explicites pour éviter le
#: RTL trap au copier-coller. Plage U+0610..U+061A (marques supplémentaires) +
#: U+064B..U+065F (fatha, kasra, damma, sukun, shadda, etc.).
_HARAKAT_RE = re.compile("[ؐ-ًؚ-ٟ]")

#: Caractère tatweel (kashida) U+0640 — élongation typographique, à supprimer.
_TATWEEL = "ـ"


# ────────────────────────────────────────────────────────────────────────────
# Table de translittération char-par-char (fallback si mot AR absent du corpus)
# ────────────────────────────────────────────────────────────────────────────

#: Mapping char-par-char arabe → ASCII (fallback). Aligné avec le brief
#: §spec.post_slug et avec l'usage courant des slugs AR translittérés.
_AR_CHAR_TABLE: dict[str, str] = {
    "ا": "a",
    "ب": "b",
    "ت": "t",
    "ث": "th",
    "ج": "j",
    "ح": "h",
    "خ": "kh",
    "د": "d",
    "ذ": "dh",
    "ر": "r",
    "ز": "z",
    "س": "s",
    "ش": "sh",
    "ص": "s",
    "ض": "d",
    "ط": "t",
    "ظ": "z",
    "ع": "",  # 'ayn — silencieux dans les slugs (cohérent avec corpus : usfur, dafda)
    "غ": "gh",
    "ف": "f",
    "ق": "q",
    "ك": "k",
    "ل": "l",
    "م": "m",
    "ن": "n",
    "ه": "h",
    "و": "w",
    "ي": "y",
    "ى": "a",   # alif maksura
    "ة": "a",   # ta marbuta
    "ء": "",    # hamza isolé
    "آ": "a",   # alif madda
    "أ": "a",   # alif + hamza dessus
    "إ": "i",   # alif + hamza dessous
    "ؤ": "w",   # waw + hamza
    "ئ": "y",   # ya + hamza
    # tatweel géré séparément, harakat strippés en amont
}


# ────────────────────────────────────────────────────────────────────────────
# Chargement du corpus AR (lazy, mémoïsé)
# ────────────────────────────────────────────────────────────────────────────

_CORPUS_PATH = Path(__file__).resolve().parents[2] / "docs" / "xchange" / "ar_slug_corpus.csv"

_PHRASE_MAP: dict[str, str] | None = None
_WORD_MAP: dict[str, str] | None = None


def _normalize_ar_input(text: str) -> str:
    """Normalise un texte AR avant lookup ou translittération.

    - Strip harakat (codepoints explicites)
    - Supprime tatweel
    - Trim espaces multiples
    """
    if not text:
        return ""
    s = _HARAKAT_RE.sub("", text)
    s = s.replace(_TATWEEL, "")
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _align_phrase_to_words(src_words: list[str], slug_parts: list[str]) -> list[tuple[str, str]] | None:
    """Aligne mots AR sources avec parts du slug latin.

    Gère deux cas spéciaux :
    - mot AR commençant par ``ال`` (article défini) → consomme 2 parts ``al`` + ``<X>`` du slug
    - mot AR ``و`` (conjonction) seul → consomme 1 part commençant par ``wa``

    Retourne ``None`` si l'alignement échoue (longueurs incompatibles).
    """
    aligned: list[tuple[str, str]] = []
    i, j = 0, 0
    while i < len(src_words) and j < len(slug_parts):
        sw = src_words[i]
        if sw.startswith("ال") and j + 1 < len(slug_parts) and slug_parts[j] == "al":
            aligned.append((sw, "al-" + slug_parts[j + 1]))
            i += 1
            j += 2
        else:
            aligned.append((sw, slug_parts[j]))
            i += 1
            j += 1
    if i != len(src_words) or j != len(slug_parts):
        # mismatch — on n'utilise pas ce row pour le word-map
        return None
    return aligned


def _load_corpus() -> tuple[dict[str, str], dict[str, str]]:
    """Charge le corpus AR depuis le CSV xchange. Mémoïsé après premier appel.

    Retourne ``(phrase_map, word_map)`` :
    - ``phrase_map`` : titre AR normalisé → slug attendu (priorité 1)
    - ``word_map`` : mot AR normalisé → fragment de slug (priorité 2)
    """
    global _PHRASE_MAP, _WORD_MAP
    if _PHRASE_MAP is not None and _WORD_MAP is not None:
        return _PHRASE_MAP, _WORD_MAP

    phrase_map: dict[str, str] = {}
    word_map: dict[str, str] = {}

    if not _CORPUS_PATH.exists():
        _PHRASE_MAP = phrase_map
        _WORD_MAP = word_map
        return phrase_map, word_map

    with _CORPUS_PATH.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            titre = (row.get("titre_ar") or "").strip()
            slug = (row.get("slug_attendu") or "").strip()
            if not titre or not slug:
                continue
            titre_norm = _normalize_ar_input(titre)
            phrase_map[titre_norm] = slug

            src_words = titre_norm.split()
            slug_parts = slug.split("-")
            aligned = _align_phrase_to_words(src_words, slug_parts)
            if aligned is None:
                continue
            for sw, ow in aligned:
                # Conflit éventuel : conserver la première occurrence (déterministe).
                word_map.setdefault(sw, ow)

    _PHRASE_MAP = phrase_map
    _WORD_MAP = word_map
    return phrase_map, word_map


# ────────────────────────────────────────────────────────────────────────────
# Helpers internes (kebab ASCII)
# ────────────────────────────────────────────────────────────────────────────


def _ascii_fold(text: str) -> str:
    """NFKD + filtre des marques combinantes (accents). Stdlib uniquement."""
    if not text:
        return ""
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in nfkd if not unicodedata.combining(ch))


def _to_kebab(text: str) -> str:
    """Convertit un texte latin (déjà sans accents) en kebab ASCII strict.

    - Lower-case
    - Tous caractères non-[a-z0-9] → ``-``
    - Compresse tirets multiples
    - Trim tirets bord
    """
    if not text:
        return ""
    s = text.lower()
    # Remplacer tout caractère non ASCII alphanumérique par '-'
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = re.sub(r"-{2,}", "-", s)
    s = s.strip("-")
    return s


def _translit_ar(text: str) -> str:
    """Translittère un texte AR en slug ASCII kebab.

    Stratégie (priorité décroissante) :
    1. Phrase complète présente dans le corpus → réutilise le slug exact
    2. Mot par mot, lookup dans ``word_map``
    3. Mots inconnus → fallback table char-par-char ``_AR_CHAR_TABLE``

    Toujours déterministe pour un même input.
    """
    if not text:
        return ""
    phrase_map, word_map = _load_corpus()
    norm = _normalize_ar_input(text)
    if not norm:
        return ""

    # 1. Phrase complète
    if norm in phrase_map:
        return phrase_map[norm]

    # 2 / 3. Mot par mot
    parts: list[str] = []
    for word in norm.split():
        if word in word_map:
            parts.append(word_map[word])
            continue
        # Fallback char-par-char
        out_chars: list[str] = []
        for ch in word:
            if ch in _AR_CHAR_TABLE:
                out_chars.append(_AR_CHAR_TABLE[ch])
            elif ch.isascii() and (ch.isalnum() or ch == "-"):
                # Lettres/chiffres latins éventuellement présents
                out_chars.append(ch.lower())
            # tout autre caractère (ponctuation AR, etc.) → ignoré
        fragment = "".join(out_chars)
        if fragment:
            parts.append(fragment)

    # Joindre avec '-' puis nettoyer (au cas où certaines parts contiennent
    # déjà des tirets ou seraient vides)
    joined = "-".join(p for p in parts if p)
    return _to_kebab(joined)


# ────────────────────────────────────────────────────────────────────────────
# API publique
# ────────────────────────────────────────────────────────────────────────────


def r2_slug(name_en: str) -> str:
    """Génère le R2 slug canonique d'un master image à partir d'un nom EN.

    ASCII kebab strict, validé contre ``^[a-z][a-z0-9-]*[a-z0-9]$``.

    Règles :
    - Normalisation Unicode NFKD → ASCII (supprime accents et signes)
    - Lower-case
    - Espaces, underscores, ponctuation → ``-``
    - Compresse tirets multiples, trim tirets bord
    - Validation finale : doit commencer par ``[a-z]`` et longueur ≥ 2

    **Décision archi** : si l'input ne peut produire un slug valide (commence
    par chiffre, slug vide, longueur < 2, etc.), ``ValueError`` est levé.
    L'appelant doit corriger le ``name_en`` source (ex. ``"42 Apples"`` →
    renommer en ``"forty-two-apples"`` ou ``"apples-42"``).

    Args:
        name_en: nom anglais source (ex. ``"Lion in Savanna"``).

    Returns:
        slug ASCII kebab (ex. ``"lion-in-savanna"``).

    Raises:
        ValueError: si le slug résultant est vide, commence par un chiffre,
            ou ne respecte pas la regex stricte ``^[a-z][a-z0-9-]*[a-z0-9]$``.

    Examples:
        >>> r2_slug("Lion in Savanna")
        'lion-in-savanna'
        >>> r2_slug("Birthday Cake with Candles")
        'birthday-cake-with-candles'
        >>> r2_slug("Éid al-Adha Sheep")
        'eid-al-adha-sheep'
    """
    if name_en is None:
        raise ValueError("r2_slug: name_en is None")
    folded = _ascii_fold(name_en)
    slug = _to_kebab(folded)
    if not slug:
        raise ValueError(f"r2_slug: empty slug for input {name_en!r}")
    if len(slug) < 2:
        raise ValueError(f"r2_slug: slug too short ({slug!r}) for input {name_en!r}")
    if not _R2_SLUG_RE.match(slug):
        raise ValueError(
            f"r2_slug: slug {slug!r} doesn't match strict regex "
            f"^[a-z][a-z0-9-]*[a-z0-9]$ (commence par chiffre ou format invalide) "
            f"for input {name_en!r}"
        )
    return slug


def post_slug(name: str, locale: str) -> str:
    """Génère le Post slug pour une locale donnée.

    ASCII kebab dans toutes les locales (contrat Alwan Books, regex Zod
    ``^[a-z0-9]+(-[a-z0-9]+)*$``, max 50 chars).

    Stratégie par locale :
    - ``en`` / ``fr`` : NFKD + ASCII fold + lower + kebab
    - ``ar`` : translittération via corpus ``ar_slug_corpus.csv`` (phrase puis
      mot), fallback table char-par-char. Strip harakat + tatweel en amont.

    Déterministe : même input → même output à chaque appel.

    Args:
        name: nom dans la locale considérée. Pour ``ar``, accepte le titre
            arabe natif (ex. ``"أسد في الغابة"``).
        locale: code locale ``'en'``, ``'fr'`` ou ``'ar'``.

    Returns:
        slug ASCII kebab strict (ex. ``"lion-in-savanna"``,
        ``"asad-fi-al-ghaba"``).

    Raises:
        ValueError: si ``locale`` n'est pas dans ``{'en', 'fr', 'ar'}`` ou si
            le slug résultant ne respecte pas la regex Zod stricte.

    Examples:
        >>> post_slug("Lion dans la Savane", "fr")
        'lion-dans-la-savane'
        >>> post_slug("Lion in Savanna", "en")
        'lion-in-savanna'
        >>> post_slug("أسد في الغابة", "ar")
        'asad-fi-al-ghaba'
    """
    if name is None:
        raise ValueError("post_slug: name is None")
    if locale not in ("en", "fr", "ar"):
        raise ValueError(
            f"post_slug: locale {locale!r} invalide — attendu 'en', 'fr' ou 'ar'"
        )

    if locale == "ar":
        slug = _translit_ar(name)
    else:
        slug = _to_kebab(_ascii_fold(name))

    if not slug:
        raise ValueError(f"post_slug: empty slug for input {name!r} (locale={locale!r})")
    if not ASCII_KEBAB_RE.match(slug):
        raise ValueError(
            f"post_slug: slug {slug!r} doesn't match Zod regex "
            f"^[a-z0-9]+(-[a-z0-9]+)*$ for input {name!r} (locale={locale!r})"
        )
    return slug


__all__ = ["r2_slug", "post_slug", "ASCII_KEBAB_RE"]
