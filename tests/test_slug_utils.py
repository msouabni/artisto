"""Tests pour ``src/services/slug_utils.py``.

Couverture :
- ``r2_slug`` ASCII kebab strict (≥10 cas tests, accents, ponctuation,
  edge cases ValueError).
- ``post_slug`` FR / EN / AR (≥10 cas, dont 5 AR avec ancres réelles de la
  taxonomie + 5 FR/EN), translittération AR via corpus + fallback char.
- Idempotence / déterminisme.
- Strip harakat AR.
- Aucune dépendance pip nouvelle.
"""
from __future__ import annotations

import pytest

from services.slug_utils import ASCII_KEBAB_RE, post_slug, r2_slug


# ────────────────────────────────────────────────────────────────────────────
# r2_slug — ASCII kebab strict (regex ^[a-z][a-z0-9-]*[a-z0-9]$, min 2 chars)
# ────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "name_en,expected",
    [
        ("Lion in Savanna", "lion-in-savanna"),
        ("Birthday Cake with Candles", "birthday-cake-with-candles"),
        ("Éid al-Adha Sheep", "eid-al-adha-sheep"),
        ("Cat in Library", "cat-in-library"),
        ("Astronaut on the Moon", "astronaut-on-the-moon"),
        ("dog_with_ball", "dog-with-ball"),  # underscores → dashes
        ("Hello!!!World___test", "hello-world-test"),  # ponctuation compressée
        ("  Lion   Savanna  ", "lion-savanna"),  # espaces multiples + trim
        ("café-noir", "cafe-noir"),  # accent latin
        ("Naïve Strategy", "naive-strategy"),  # diérèse
        ("Œuf de Pâques", "uf-de-paques"),  # ligature œ → décomposée, accent é dépouillé
        ("Mickey & Friends", "mickey-friends"),  # esperluette
        ("Lion (Savanna)", "lion-savanna"),  # parenthèses
        ("Bird's Nest", "bird-s-nest"),  # apostrophe → tiret
    ],
)
def test_r2_slug_valid_inputs(name_en: str, expected: str) -> None:
    """r2_slug couvre les cas standards : accents, ponctuation, casing."""
    result = r2_slug(name_en)
    assert result == expected, f"r2_slug({name_en!r}) → {result!r}, attendu {expected!r}"
    # Le résultat doit toujours matcher la regex Zod publique
    assert ASCII_KEBAB_RE.match(result), f"{result!r} ne matche pas la regex Zod"


@pytest.mark.parametrize(
    "bad_input",
    [
        "42 Apples",           # commence par chiffre
        "",                    # vide
        "   ",                 # whitespace only
        "!!!",                 # ponctuation only
        "a",                   # trop court (1 char)
        "1",                   # chiffre seul
        "---",                 # tirets seuls
    ],
)
def test_r2_slug_raises_on_invalid_input(bad_input: str) -> None:
    """r2_slug lève ValueError quand le slug ne peut être valide."""
    with pytest.raises(ValueError):
        r2_slug(bad_input)


def test_r2_slug_raises_on_none() -> None:
    """r2_slug lève ValueError sur None (pas de TypeError)."""
    with pytest.raises(ValueError):
        r2_slug(None)  # type: ignore[arg-type]


def test_r2_slug_idempotent() -> None:
    """r2_slug appliqué deux fois donne le même résultat."""
    slug = r2_slug("Lion in Savanna")
    assert r2_slug(slug) == slug


# ────────────────────────────────────────────────────────────────────────────
# post_slug FR / EN — kebab ASCII strict
# ────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "name,locale,expected",
    [
        ("Lion in Savanna", "en", "lion-in-savanna"),
        ("Cat in Library", "en", "cat-in-library"),
        ("Astronaut on the Moon", "en", "astronaut-on-the-moon"),
        ("Birthday Cake", "en", "birthday-cake"),
        ("Pumpkin and Witch", "en", "pumpkin-and-witch"),
        ("Lion dans la Savane", "fr", "lion-dans-la-savane"),
        ("Chat à la bibliothèque", "fr", "chat-a-la-bibliotheque"),
        ("Œuf de Pâques", "fr", "uf-de-paques"),
        ("Père Noël en hiver", "fr", "pere-noel-en-hiver"),
        ("Forêt enchantée", "fr", "foret-enchantee"),
    ],
)
def test_post_slug_en_fr(name: str, locale: str, expected: str) -> None:
    """post_slug FR/EN : NFKD + ASCII fold + kebab."""
    result = post_slug(name, locale)
    assert result == expected, f"post_slug({name!r}, {locale!r}) → {result!r}, attendu {expected!r}"
    assert ASCII_KEBAB_RE.match(result), f"{result!r} ne matche pas la regex Zod"


# ────────────────────────────────────────────────────────────────────────────
# post_slug AR — translittération via corpus + fallback char
# ────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "name_ar,expected",
    [
        # Cas du corpus (phrase complète présente)
        ("أسد في الغابة", "asad-fi-al-ghaba"),
        ("قط في المكتبة", "qitt-fi-al-maktaba"),
        ("دب صغير", "dubb-saghir"),
        ("فراشة ملونة", "farasha-mulawwana"),
        ("سمكة في البحر", "samaka-fi-al-bahr"),
        ("زهرة جميلة", "zahra-jamila"),
        ("أرنب أبيض", "arnab-abyad"),
        ("فيل كبير", "fil-kabir"),
        ("نمر مخطط", "namir-mukhattit"),
        ("حوت في المحيط", "hut-fi-al-muhit"),
    ],
)
def test_post_slug_ar_corpus(name_ar: str, expected: str) -> None:
    """post_slug AR : phrases du corpus → slug attendu (ancrage taxonomie)."""
    result = post_slug(name_ar, "ar")
    assert result == expected, f"post_slug({name_ar!r}, 'ar') → {result!r}, attendu {expected!r}"
    assert ASCII_KEBAB_RE.match(result), f"{result!r} ne matche pas la regex Zod"
    # Pas de harakat ni de caractère non-ASCII résiduel
    assert all(ord(c) < 128 for c in result), f"latin résiduel non-ASCII dans {result!r}"


def test_post_slug_ar_strips_harakat() -> None:
    """post_slug AR : harakat (fatha, kasra, damma, etc.) supprimés en amont."""
    # "أسد في الغابة" avec harakat ajoutés
    with_harakat = "أَسَدٌ فِي الْغَابَةِ"
    result = post_slug(with_harakat, "ar")
    assert result == "asad-fi-al-ghaba", f"harakat non strippés : {result!r}"


def test_post_slug_ar_strips_tatweel() -> None:
    """post_slug AR : tatweel (kashida) supprimé."""
    # "أسد" avec tatweel
    with_tatweel = "أســـد في الغابة"
    result = post_slug(with_tatweel, "ar")
    assert result == "asad-fi-al-ghaba", f"tatweel non strippé : {result!r}"


def test_post_slug_ar_fallback_char_table() -> None:
    """post_slug AR : mot inconnu du corpus → fallback table char-par-char.

    "كتاب" n'est pas dans le corpus → translit char-par-char : ك→k, ت→t,
    ا→a, ب→b → "ktab". Slug ASCII kebab valide.
    """
    result = post_slug("كتاب", "ar")
    assert result == "ktab"
    assert ASCII_KEBAB_RE.match(result)


def test_post_slug_ar_unknown_phrase_word_by_word() -> None:
    """post_slug AR : phrase inconnue, mais mots présents dans le corpus.

    "زهرة جميلة" est dans le corpus. "فيل ملون" (combinaison nouvelle) :
    fil + mulawwan via word-map.
    """
    result = post_slug("فيل ملون", "ar")
    assert result == "fil-mulawwan", f"got {result!r}"
    assert ASCII_KEBAB_RE.match(result)


def test_post_slug_ar_deterministic() -> None:
    """post_slug AR : même input → même output à chaque appel (déterminisme)."""
    inputs = ["أسد في الغابة", "كتاب", "فيل ملون", "قط في المكتبة"]
    for txt in inputs:
        r1 = post_slug(txt, "ar")
        r2 = post_slug(txt, "ar")
        r3 = post_slug(txt, "ar")
        assert r1 == r2 == r3, f"non-déterministe pour {txt!r}: {r1}, {r2}, {r3}"


# ────────────────────────────────────────────────────────────────────────────
# Validation locale + erreurs
# ────────────────────────────────────────────────────────────────────────────


def test_post_slug_invalid_locale() -> None:
    """post_slug : locale hors {en, fr, ar} → ValueError."""
    with pytest.raises(ValueError):
        post_slug("hello", "de")
    with pytest.raises(ValueError):
        post_slug("hello", "")


def test_post_slug_empty_after_normalization() -> None:
    """post_slug : input qui se réduit à du vide → ValueError."""
    with pytest.raises(ValueError):
        post_slug("!!!", "en")
    with pytest.raises(ValueError):
        post_slug("", "ar")


def test_post_slug_none() -> None:
    """post_slug : None → ValueError."""
    with pytest.raises(ValueError):
        post_slug(None, "en")  # type: ignore[arg-type]


# ────────────────────────────────────────────────────────────────────────────
# Sanity check : la regex Zod publique reste mirror du contrat
# ────────────────────────────────────────────────────────────────────────────


def test_ascii_kebab_regex_mirror_zod() -> None:
    """ASCII_KEBAB_RE doit matcher exactement le pattern Zod du contrat
    Alwan Books : ^[a-z0-9]+(-[a-z0-9]+)*$."""
    assert ASCII_KEBAB_RE.pattern == r"^[a-z0-9]+(-[a-z0-9]+)*$"

    # Cas valides
    assert ASCII_KEBAB_RE.match("lion-savane")
    assert ASCII_KEBAB_RE.match("a")
    assert ASCII_KEBAB_RE.match("a-b-c")
    assert ASCII_KEBAB_RE.match("42-apples")  # Zod accepte chiffres en tête (r2_slug, non)

    # Cas refusés
    assert not ASCII_KEBAB_RE.match("Lion-Savane")
    assert not ASCII_KEBAB_RE.match("lion_savane")
    assert not ASCII_KEBAB_RE.match("-lion")
    assert not ASCII_KEBAB_RE.match("lion-")
    assert not ASCII_KEBAB_RE.match("lion--savane")
    assert not ASCII_KEBAB_RE.match("lion à savane")
