"""
prompt_filters.py — Filtres pre-processing couleur / surfaces / 3D pour les prompts ComfyUI.

Transfert prophylactique des règles T5 + T6 (+ extension T6) + T7 du skill
``prompt-taxonomy-ecosystem`` (cf. ``references/techniques.md``).

Contexte (CLAUDE.md / brief 2026-05-10) :
- Aucun paramètre sampler / steps / cfg ne corrige les couleurs résiduelles.
- Le negative prompt est inefficace contre les ancres chromatiques explicites
  ou implicites et contre les ancres 3D (matières brillantes / réfléchissantes).
- Seul le strip / remplacement upstream (sur le texte injecté dans le template)
  fait disparaître ces priors.

Volume corpus actuel faible (1 occurrence ``image_gris_residuel``) : la
mesure post-transfert est optionnelle, le but est prophylactique pour rester
sous ``cr < 0.001`` à grande échelle.

Hors scope :
- ``NEGATIVE_V3`` (déjà couvert).
- Filtres AR (``services/ollama_json.py``).

Vocabulaires figés ci-dessous selon les listes du skill — toute extension
DOIT citer la section ``techniques.md`` correspondante.
"""

from __future__ import annotations

import re
from typing import Iterable, List, Tuple

# ===================================================================
# T5 — Couleur résiduelle : ancres chromatiques EXPLICITES
# Source skill : techniques.md §T5 (l. 175-187)
# « Les noms de couleur dans le prompt positif activent le prior couleur.
#   Le negative prompt ne corrige pas ce défaut.
#   Fix : Supprimer tous les noms de couleur du positif. »
# ===================================================================
_COLOR_NOUNS: frozenset[str] = frozenset(
    {
        # couleurs de base
        "red", "orange", "yellow", "green", "blue", "purple", "violet",
        "pink", "brown", "black", "white", "grey", "gray",
        # nuances / intensités usuelles
        "scarlet", "crimson", "ruby", "magenta", "fuchsia", "rose",
        "amber", "ochre", "tan", "beige", "cream", "ivory",
        "lime", "olive", "emerald", "teal", "turquoise", "cyan",
        "azure", "navy", "indigo", "lavender", "lilac",
        "maroon", "burgundy", "chestnut",
        # métaux nommés couleur (T5 stricte — la matière brillante part en T7)
        "golden", "silver", "bronze", "copper", "brass",
        # luminosité
        "dark", "light", "bright", "pale", "deep", "vivid", "vibrant",
        "neon", "fluorescent",
        # « colorful / colored » : pas filtrés ici (servent justement
        # de remplaçant générique pour T6 ``rainbow`` → ``colorful``).
    }
)

# ===================================================================
# T6 — Couleur résiduelle : ancres chromatiques IMPLICITES (conceptuelles)
# Source skill : techniques.md §T6 (l. 189-202) + Extension T6 (l. 731-754).
# « Certains termes conceptuels activent le prior couleur sans nommer
#   de couleur explicitement. ``rainbow`` en est l'exemple le plus fort.
#   Fix : Remplacer par le terme générique neutre. »
#
# NB : on garde uniquement le sous-ensemble explicitement listé dans le skill ;
# les ancres ``sandcastle / beach / brick / wood / grass / sky`` sont du ressort
# des templates / overrides et ne sont PAS strippées globalement (risque de
# casser les descriptions naturelles d'objets).
# ===================================================================
_COLOR_ANCHOR_REPLACEMENTS: Tuple[Tuple[str, str], ...] = (
    ("rainbow", "colorful"),
    ("sunset", "sky scene"),
    ("autumn", "seasonal scene"),
    ("fall season", "seasonal scene"),
    ("tropical", "exotic"),
    ("fire", "flame shape"),  # garde la silhouette sans prior couleur chaud
    ("flame", "flame shape"),
)
# Ensemble brut pour les tests / introspection
_COLOR_ANCHORS: frozenset[str] = frozenset(src for src, _ in _COLOR_ANCHOR_REPLACEMENTS)

# ===================================================================
# Extension T6 — Surfaces brillantes / matières → activent prior 3D & couleur
# Source skill : techniques.md §T7 (l. 204-216) — ancres listées explicitement :
#   ``shiny``, ``glossy``, ``metallic``, ``chrome``, ``glass``, ``wet``, ``chocolate``
# Le brief 2026-05-10 §1 reprend cette liste sous le label « extension T6 ».
# ===================================================================
_GLOSSY_TERMS: frozenset[str] = frozenset(
    {
        "shiny", "glossy", "metallic", "chrome", "glass", "wet", "chocolate",
        # variantes morphologiques rencontrées dans les name_en
        "shining", "polished", "lacquered", "reflective", "mirrored",
    }
)

# ===================================================================
# T7 — Rendu 3D involontaire (ombres / volumes / textures réalistes)
# Source skill : techniques.md §T7 (l. 204-216) + brief 2026-05-10 §1.
# « Décrire l'objet sans sa matière ni son rendu de surface. »
# ===================================================================
_3D_TERMS: Tuple[str, ...] = (
    # multi-mots d'abord (priorité dans le strip)
    "realistic textures",
    "realistic texture",
    "depth shading",
    "volumetric lighting",
    "volumetric shading",
    "soft shading",
    "drop shadow",
    "drop shadows",
    # mots simples
    "shaded",
    "shading",
    "volumetric",
    "3d",
    "rendered",
    "photorealistic",
)


# ===================================================================
# Helpers internes
# ===================================================================
def _word_boundary_pattern(words: Iterable[str]) -> re.Pattern[str]:
    """Compile un pattern « mot entier » insensible à la casse pour une liste.

    Préserve l'ordre (les expressions multi-mots doivent être passées avant
    leurs sous-mots pour éviter les strips partiels).
    """
    # On échappe et on autorise un espace normal ou multiple entre les tokens.
    parts = [re.escape(w).replace(r"\ ", r"\s+") for w in words]
    pattern = r"(?<![A-Za-z])(?:" + "|".join(parts) + r")(?![A-Za-z])"
    return re.compile(pattern, flags=re.IGNORECASE)


def _collapse_whitespace(text: str) -> str:
    """Normalise les espaces multiples et nettoie la ponctuation orpheline.

    Ex : ``"a  ,  red ball"`` → ``"a, red ball"`` ; ``" , ,"`` → ``","``.
    """
    # Supprime les virgules orphelines créées par le strip (« , , » → « , »).
    text = re.sub(r"\s*,(\s*,)+", ",", text)
    # Espace multiple → un seul.
    text = re.sub(r"[ \t]+", " ", text)
    # Espace avant ponctuation.
    text = re.sub(r"\s+([,.;:!?])", r"\1", text)
    # Virgule en début / fin de chaîne.
    text = re.sub(r"^\s*,\s*", "", text)
    text = re.sub(r"\s*,\s*$", "", text)
    return text.strip()


_COLOR_NOUNS_RE = _word_boundary_pattern(sorted(_COLOR_NOUNS, key=len, reverse=True))
_GLOSSY_TERMS_RE = _word_boundary_pattern(sorted(_GLOSSY_TERMS, key=len, reverse=True))
_3D_TERMS_RE = _word_boundary_pattern(_3D_TERMS)  # ordre déjà multi-mots first

# T6 — un seul pattern compilé pour tous les anchors avec map de remplacement.
# Cette approche évite la double-substitution (ex. fire → flame shape → flame
# shape shape si on bouclait avec sub() en série).
_COLOR_ANCHOR_MAP: dict[str, str] = {src.lower(): dst for src, dst in _COLOR_ANCHOR_REPLACEMENTS}
_COLOR_ANCHORS_RE = _word_boundary_pattern(
    sorted(_COLOR_ANCHOR_MAP.keys(), key=len, reverse=True)
)


# ===================================================================
# Whitelist FILT contextuelle — fruits / contenants comestibles
# Source : rapport `docs/reports/2026-05-10_transfert-skill-T2T3T23-grille-imagier.md`
#          §Découverte FILT × T2 + brief
#          `docs/architect/briefs/2026-05-10_brief-whitelist-filt-contextuelle.md`.
# Skill : `references/techniques.md` §T5 / §T6 (extension contextuelle dérivée).
#
# Problème observé : T2 grille imagier (fruits, vaisselle, météo) injecte des items
# nominaux où des tokens normalement filtrés (orange, glass, bright, dark…) sont
# sémantiquement importants (fruit, contenant, qualificatif sémantique non-couleur).
# Le strip global appauvrit le prompt (`round orange with leaf` → `round with leaf`).
#
# Stratégie : un strip est *court-circuité localement* si le token apparaît dans
# un contexte nominal protégé (regex compilée). On ne désactive PAS le strip
# global ; on le rend contextuel pour ~6-8 motifs ciblés. La whitelist est
# conservatrice — toute extension nécessite un test positif + négatif explicite.
# ===================================================================
_PROTECTED_NOMINAL_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    # --- Fruits ---
    # `round/fresh/peeled/whole/sliced/half orange with|on|in ...`
    # → contexte fruit (dimpled skin, leaf, segment, juice…). « orange car » non protégé.
    (
        "orange",
        re.compile(
            r"\b(round|fresh|peeled|whole|sliced|half)\s+orange\s+(with|on|in|and|of)\b",
            re.IGNORECASE,
        ),
    ),
    # « an orange/the orange » suivi d'un descripteur de fruit → fruit.
    (
        "orange",
        re.compile(
            r"\b(an|the)\s+orange\s+(slice|segment|peel|wedge|half)\b",
            re.IGNORECASE,
        ),
    ),
    # --- Contenants comestibles / vaisselle ---
    # `drinking|tall|small|empty|full|water|milk|juice + glass` → contenant, pas surface 3D.
    (
        "glass",
        re.compile(
            r"\b(drinking|tall|small|empty|full|water|milk|juice|wine)\s+glass\b",
            re.IGNORECASE,
        ),
    ),
    # `glass of <liquide>` → contenant. Ex. `glass of milk`.
    (
        "glass",
        re.compile(
            r"\bglass\s+of\s+(milk|water|juice|wine|lemonade)\b",
            re.IGNORECASE,
        ),
    ),
    # --- Adjectifs sémantiques non-luminosité ---
    # `bright + future|idea|side|child|smile|day` → sens figuré ou expression, pas "luminosité".
    (
        "bright",
        re.compile(
            r"\bbright\s+(future|idea|side|child|smile|day|eyes)\b",
            re.IGNORECASE,
        ),
    ),
    # `dark + age|side|secret|matter|knight` → expression, pas teinte/luminosité.
    (
        "dark",
        re.compile(
            r"\bdark\s+(age|ages|side|secret|matter|knight|chocolate)\b",
            re.IGNORECASE,
        ),
    ),
    # --- Couleurs nominales (rares mais utiles pour T2) ---
    # `red carpet` (cérémonie / institution) — nom propre composé.
    (
        "red",
        re.compile(
            r"\bred\s+(carpet|cross|panda|alert)\b",
            re.IGNORECASE,
        ),
    ),
]


def _protected_spans(text: str, token: str) -> list[tuple[int, int]]:
    """Renvoie la liste des (start, end) du `text` où le `token` est protégé.

    Les indices sont calculés sur la chaîne d'entrée. Plusieurs patterns peuvent
    couvrir le même `token` ; on collecte tous les spans (l'union des intervalles
    sera utilisée pour court-circuiter le strip).
    """
    if not text or not token:
        return []
    spans: list[tuple[int, int]] = []
    token_lc = token.lower()
    for protected_token, pattern in _PROTECTED_NOMINAL_PATTERNS:
        if protected_token.lower() != token_lc:
            continue
        for m in pattern.finditer(text):
            spans.append((m.start(), m.end()))
    return spans


def _strip_with_whitelist(
    text: str,
    pattern: re.Pattern[str],
    whitelisted_tokens: Iterable[str],
) -> str:
    """Applique `pattern.sub("", text)` sauf pour les matches dont le token est
    contenu dans un span protégé (cf. `_PROTECTED_NOMINAL_PATTERNS`).

    Implémentation : on calcule l'union des spans protégés pour chaque token
    whitelisté, puis on remplace itérativement les matches dont la position
    n'est PAS contenue dans un span protégé.
    """
    if not text:
        return text
    # Pré-calcul : pour chaque token whitelisté, ses spans protégés.
    protected_by_token: dict[str, list[tuple[int, int]]] = {}
    for token in whitelisted_tokens:
        spans = _protected_spans(text, token)
        if spans:
            protected_by_token[token.lower()] = spans

    if not protected_by_token:
        # Aucun token protégé présent → strip standard.
        return pattern.sub("", text)

    def _replace(match: re.Match[str]) -> str:
        matched = match.group(0).lower()
        spans = protected_by_token.get(matched)
        if not spans:
            return ""
        m_start = match.start()
        m_end = match.end()
        # Match contenu dans un span protégé → on garde l'original.
        for span_start, span_end in spans:
            if span_start <= m_start and m_end <= span_end:
                return match.group(0)
        return ""

    return pattern.sub(_replace, text)


# Tokens whitelistés connus, déduits de `_PROTECTED_NOMINAL_PATTERNS`.
_WHITELISTED_TOKENS: frozenset[str] = frozenset(
    token.lower() for token, _ in _PROTECTED_NOMINAL_PATTERNS
)


# ===================================================================
# API publique
# ===================================================================
def strip_color_nouns(text: str) -> str:
    """T5 — supprime les noms de couleur explicites du texte.

    Court-circuit contextuel via `_PROTECTED_NOMINAL_PATTERNS` : un token
    color-noun protégé par un pattern nominal (ex. `round orange with leaf`,
    `red carpet`) reste préservé localement. Cf. rapport
    `2026-05-10_transfert-skill-T2T3T23-grille-imagier.md` §Découverte FILT × T2.

    >>> strip_color_nouns("a red apple on a blue plate")
    'a apple on a plate'
    >>> strip_color_nouns("simple line drawing")
    'simple line drawing'
    >>> strip_color_nouns("round orange with leaf")
    'round orange with leaf'
    """
    if not text:
        return text
    cleaned = _strip_with_whitelist(text, _COLOR_NOUNS_RE, _WHITELISTED_TOKENS)
    return _collapse_whitespace(cleaned)


def replace_color_anchors(text: str) -> str:
    """T6 — remplace les ancres chromatiques implicites par un terme neutre.

    Substitution **atomique** (un seul passage via lambda) pour éviter qu'une
    substitution ne réintroduise un token re-matchable (ex. ``fire → flame
    shape`` puis re-match de ``flame`` → ``flame shape shape``).

    >>> replace_color_anchors("a rainbow over the mountain")
    'a colorful over the mountain'
    >>> replace_color_anchors("simple line drawing")
    'simple line drawing'
    >>> replace_color_anchors("fire and flame")
    'flame shape and flame shape'
    """
    if not text:
        return text
    out = _COLOR_ANCHORS_RE.sub(
        lambda m: _COLOR_ANCHOR_MAP[m.group(0).lower()], text
    )
    return _collapse_whitespace(out)


def strip_glossy_terms(text: str) -> str:
    """Extension T6 — supprime les termes de surface brillante / matière réfléchissante.

    Court-circuit contextuel via `_PROTECTED_NOMINAL_PATTERNS` : `glass` reste
    préservé dans des contextes contenants (`drinking glass`, `glass of milk`).
    Cf. rapport `2026-05-10_transfert-skill-T2T3T23-grille-imagier.md` §Découverte FILT × T2.

    >>> strip_glossy_terms("a shiny metallic sphere")
    'a sphere'
    >>> strip_glossy_terms("a wooden box")
    'a wooden box'
    >>> strip_glossy_terms("tall drinking glass")
    'tall drinking glass'
    """
    if not text:
        return text
    cleaned = _strip_with_whitelist(text, _GLOSSY_TERMS_RE, _WHITELISTED_TOKENS)
    return _collapse_whitespace(cleaned)


def strip_3d_terms(text: str) -> str:
    """T7 — supprime les termes de rendu 3D / ombrage involontaire.

    >>> strip_3d_terms("a shaded volumetric ball with realistic textures")
    'a ball with'
    >>> strip_3d_terms("a simple ball")
    'a simple ball'
    """
    if not text:
        return text
    cleaned = _3D_TERMS_RE.sub("", text)
    return _collapse_whitespace(cleaned)


def apply_all_filters(text: str) -> str:
    """Composition T5 → T6 → ext T6 → T7.

    Ordre choisi pour que les remplacements T6 ne soient pas mangés par les
    strips T5 / T7. Les surfaces (ext T6) et le 3D (T7) terminent.

    >>> apply_all_filters("a shiny red rainbow chocolate egg with realistic textures")
    'a colorful egg with'
    >>> apply_all_filters("a simple line drawing of a cat")
    'a simple line drawing of a cat'
    """
    if not text:
        return text
    out = text
    out = replace_color_anchors(out)   # T6 d'abord (substitution → token neutre)
    out = strip_color_nouns(out)       # T5 strip noms couleur explicites
    out = strip_glossy_terms(out)      # ext T6 surfaces brillantes
    out = strip_3d_terms(out)          # T7 rendu 3D
    return out


# ===================================================================
# Introspection — utile pour debug / tests / rapport
# ===================================================================
def describe_filters() -> List[Tuple[str, int]]:
    """Retourne la taille des vocabulaires (utile au reporting du transfert)."""
    return [
        ("T5_color_nouns", len(_COLOR_NOUNS)),
        ("T6_color_anchors", len(_COLOR_ANCHORS)),
        ("T6_ext_glossy_terms", len(_GLOSSY_TERMS)),
        ("T7_3d_terms", len(_3D_TERMS)),
    ]


if __name__ == "__main__":  # pragma: no cover - smoke manuel
    samples = [
        "a shiny red rainbow chocolate egg with realistic textures",
        "a wooden box on a simple ground",
        "golden retriever in autumn forest",
        "a glossy metallic sports car",
    ]
    for s in samples:
        print(f"IN : {s}")
        print(f"OUT: {apply_all_filters(s)}")
        print("---")
