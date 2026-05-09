"""POC jetable : translittération AR → ASCII kebab.

Stratégie : table custom DIN 31635 + ASCII fold + nettoyage regex.
Pas de python-slugify (test direct de la table custom pour cerner les limites).

Usage :
    python scripts/poc_ar_transliteration.py
"""
from __future__ import annotations

import csv
import io
import re
import sys
from pathlib import Path

# Force UTF-8 stdout (Windows console est cp1252 par défaut)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
else:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CORPUS_PATH = PROJECT_ROOT / "docs" / "xchange" / "ar_slug_corpus.csv"

# Table DIN 31635 (forme scientifique avec diacritiques)
DIN_31635 = {
    "ا": "a",      # alif (vocalique long ā en position non-initiale)
    "أ": "a",      # alif + hamza au-dessus
    "إ": "i",      # alif + hamza en-dessous
    "آ": "a",      # alif + madda
    "ٱ": "a",      # alif wasla
    "ب": "b",
    "ت": "t",
    "ث": "th",
    "ج": "j",
    "ح": "ḥ",
    "خ": "kh",
    "د": "d",
    "ذ": "dh",
    "ر": "r",
    "ز": "z",
    "س": "s",
    "ش": "sh",
    "ص": "ṣ",
    "ض": "ḍ",
    "ط": "ṭ",
    "ظ": "ẓ",
    "ع": "ʿ",
    "غ": "gh",
    "ف": "f",
    "ق": "q",
    "ك": "k",
    "ل": "l",
    "م": "m",
    "ن": "n",
    "ه": "h",
    "و": "w",      # consonne w / vocalique ū selon contexte
    "ي": "y",      # consonne y / vocalique ī selon contexte
    "ى": "a",      # alif maqsura
    "ة": "a",      # tāʾ marbūṭa (final → a)
    "ء": "ʾ",
    "ؤ": "ʾ",
    "ئ": "ʾ",
    # Harakat (si l'entrée est vocalisée)
    "َ": "a",       # fatha
    "ُ": "u",       # damma
    "ِ": "i",       # kasra
    "ْ": "",        # sukun
    "ً": "an",      # fathatan
    "ٌ": "un",      # dammatan
    "ٍ": "in",      # kasratan
    "ـ": "",        # tatweel
}

# Caractères harakat (vocalisation)
FATHA = "َ"
DAMMA = "ُ"
KASRA = "ِ"
SUKUN = "ْ"
SHADDA = "ّ"
DAGGER_ALIF = "ٰ"
TANWIN_FATH = "ً"
TANWIN_DAMM = "ٌ"
TANWIN_KASR = "ٍ"
TANWIN = {TANWIN_FATH, TANWIN_DAMM, TANWIN_KASR}
HARAKAT_SET = {FATHA, DAMMA, KASRA, SUKUN, SHADDA, DAGGER_ALIF, TANWIN_FATH, TANWIN_DAMM, TANWIN_KASR, "ـ"}

# Caractères structurels
ALIF = "ا"
ALIF_MAQSURA = "ى"
WAW = "و"
YA = "ي"
TA_MARBUTA = "ة"

# Hamza-bearing : valeur par défaut quand non suivi de harakat
HAMZA_BEARING_DEFAULT = {"أ": "a", "إ": "i", "آ": "a", "ٱ": "a", "ء": "", "ؤ": "", "ئ": ""}

# Fold ASCII conformément à la spec
ASCII_FOLD = {
    "ā": "a", "ū": "u", "ī": "i",
    "ḥ": "h", "ṣ": "s", "ṭ": "t", "ḍ": "d", "ẓ": "z",
    "ġ": "gh", "ḫ": "kh",
    "ʿ": "", "ʾ": "",
}

SLUG_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


# ---------------------------------------------------------------------------
# Overrides lexicaux : substitution sur le titre brut avant vocalisation Mishkal.
# Cibles : cas où Mishkal vocalise différemment du choix éditorial du corpus.
# ---------------------------------------------------------------------------
OVERRIDES: dict[str, str | None] = {
    "أسد": "أَسَد",          # évite le shadda parasite de Mishkal
    "قط": "قِطّ",             # qiṭṭ (chat) au lieu de qaṭṭ
    "ضفدع": "ضَفْدَع",        # ḍafda‘ au lieu de ḍifda‘
    "عصفور": "عُصْفُور",      # ‘uṣfūr au lieu de ‘aṣfūr
    "حوت": "حُوت",            # ḥūt (nom "baleine") au lieu de ḥawat (verbe)
    "سلحفاة": "سُلْحَفَاة",    # sukun sur le lām (sulḥafa)
    "مخطط": "مُخَطِّط",        # participe actif "rayant"
    "أخطبوط": "أُخْطَبُوط",    # ukhṭabūṭ (a après ṭ, pas u)
    "دلفين": "دَلْفِين",      # dalfīn au lieu de dulfīn
    "وفي": "وَفِي",            # Mishkal omet la fatha sur وَ
    "مع": "مَعَ",              # vocalisation complète /ma‘a/
    "يحلق": "يُحَلِق",          # sans shadda (choix corpus)
    "مرج": "مَرْج",            # marj (sukun sur ر)
    "المرج": "الْمَرْج",        # variante avec article (la regex de remplacement ne traverse pas ال)
    "وزهرة": "وَ زَهْرَة",      # split du wāw conjonctif "et"
}


def apply_overrides_pre(titre: str) -> str:
    """Substitue les clés OVERRIDES dans le titre brut (avant Mishkal)."""
    out = titre
    for key, val in OVERRIDES.items():
        if val is None:
            continue
        pattern = r"(^|\s)" + re.escape(key) + r"(\s|$)"
        out = re.sub(pattern, lambda m, v=val: m.group(1) + v + m.group(2), out)
    return out


def _strip_harakat(s: str) -> str:
    return "".join(c for c in s if c not in HARAKAT_SET)


def apply_overrides_post(vocalized: str) -> str:
    """Re-applique OVERRIDES après Mishkal par skeleton match.

    Filet de sécurité : Mishkal re-vocalise parfois les mots déjà pré-vocalisés
    (cf. أسد → أَسَدٌّ avec shadda parasite). Match consonne-skeleton mot-à-mot
    contre les clés OVERRIDES ; remplace par la valeur pré-vocalisée si match.
    """
    if not OVERRIDES:
        return vocalized
    words = vocalized.split()
    out: list[str] = []
    i = 0
    # Construire les keys par longueur (mots), pour gérer les clés multi-mots
    keys_by_len: dict[int, list[tuple[list[str], str]]] = {}
    for k, v in OVERRIDES.items():
        if v is None:
            continue
        ksplit = k.split()
        keys_by_len.setdefault(len(ksplit), []).append((ksplit, v))
    max_len = max(keys_by_len.keys()) if keys_by_len else 0

    while i < len(words):
        matched = False
        # Tester en priorité les clés les plus longues (greedy)
        for length in range(max_len, 0, -1):
            if length not in keys_by_len:
                continue
            if i + length > len(words):
                continue
            window_skeletons = [_strip_harakat(w) for w in words[i:i + length]]
            for ksplit, v in keys_by_len[length]:
                if window_skeletons == ksplit:
                    out.append(v)
                    i += length
                    matched = True
                    break
            if matched:
                break
        if not matched:
            out.append(words[i])
            i += 1
    return " ".join(out)


def _split_al_prefix(word: str) -> str:
    """Détache l'article ال (vocalisé ou non) en token "al " séparé.

    Gère aussi l'assimilation lettre solaire : السَّمَاء → al + (drop shadda) + سَمَاء.
    """
    if not word or not word.startswith(ALIF):
        return word
    chars = list(word)
    n = len(chars)
    # Trouver le ل de l'article (juste après ا, en sautant un éventuel harakat)
    pos_lam = None
    for k in range(1, min(n, 4)):
        if chars[k] == "ل":
            pos_lam = k
            break
        if chars[k] not in HARAKAT_SET:
            return word  # le caractère après ا n'est pas ل → pas l'article
    if pos_lam is None:
        return word
    # Sauter les harakat sur le lām (typiquement sukun de l'article)
    end = pos_lam + 1
    while end < n and chars[end] in HARAKAT_SET:
        end += 1
    if end >= n:
        return word
    rest = "".join(chars[end:])
    # Lettre solaire : si la 1re consonne du reste porte une shadda d'assimilation,
    # la supprimer (le redoublement vient de l'article, pas de la racine).
    rest_chars = list(rest)
    k = 0
    while k < len(rest_chars) and rest_chars[k] in HARAKAT_SET:
        k += 1
    if k + 1 < len(rest_chars) and rest_chars[k + 1] == SHADDA:
        rest_chars.pop(k + 1)
    return "al " + "".join(rest_chars)


def _normalize_harakat_dup(chars: list[str]) -> list[str]:
    """Collapse harakat consécutives identiques (artefact Mishkal type فِِي)."""
    out: list[str] = []
    prev = ""
    for c in chars:
        if c in HARAKAT_SET and c == prev:
            continue
        out.append(c)
        prev = c
    return out


def _translit_word(word: str) -> str:
    """Translittération mot-par-mot avec gestion vocalisation."""
    chars = _normalize_harakat_dup(list(word))
    n = len(chars)
    out: list[str] = []
    i = 0
    while i < n:
        c = chars[i]
        nxt = chars[i + 1] if i + 1 < n else ""
        prev_char = chars[i - 1] if i > 0 else ""
        is_end = (i == n - 1)

        # Règle 1 : tanwin terminal → drop (forme pause)
        if c in TANWIN:
            i += 1
            continue

        # Shadda → gémination de la consonne précédente.
        # Cas 1 (bogus Mishkal) : shadda adjacent à un tanwin (avant ou après) → drop.
        # Cas 2 (légitime, ordre kasra+shadda) : voyelle vient d'être émise mais
        # une vraie consonne est en out[-2] → réordonner (insérer doublée avant voyelle).
        # Cas 3 (bogus) : voyelle vient d'être émise et out[-2] est silent (ʿ/ʾ) → drop.
        # Cas 4 (standard) : out[-1] est une consonne → double directement.
        if c == SHADDA:
            if prev_char in TANWIN or nxt in TANWIN:
                i += 1
                continue
            if out and out[-1] and out[-1][-1] in "aiu":
                if len(out) >= 2 and out[-2] and out[-2][-1] not in "aiuʿʾ":
                    vowel = out.pop()
                    out.append(out[-1][-1])
                    out.append(vowel)
                # sinon : bogus, drop
                i += 1
                continue
            if out and out[-1]:
                out.append(out[-1][-1])
            i += 1
            continue

        # Sukun → silencieux
        if c == SUKUN:
            i += 1
            continue

        # Dagger alif → "a"
        if c == DAGGER_ALIF:
            out.append("a")
            i += 1
            continue

        # Tatweel → drop
        if c == "ـ":
            i += 1
            continue

        # Hamza-bearing : si harakat suit, drop (la harakat fournira la voyelle).
        # Sinon, valeur par défaut.
        if c in HAMZA_BEARING_DEFAULT:
            if nxt in HARAKAT_SET and nxt != SHADDA:
                pass  # emit nothing, harakat handles vowel
            else:
                out.append(HAMZA_BEARING_DEFAULT[c])
            i += 1
            continue

        # Règle 4 : voyelles longues (consume both).
        # Bonus : fatha+alif+ta_marbuta consomme les 3 (pause form).
        if c == FATHA and nxt in (ALIF, ALIF_MAQSURA):
            out.append("a")
            i += 2
            if i < n and chars[i] == TA_MARBUTA:
                i += 1
                while i < n and chars[i] in HARAKAT_SET:
                    i += 1
            continue
        if c == DAMMA and nxt == WAW:
            out.append("u")
            i += 2
            continue
        if c == KASRA and nxt == YA:
            out.append("i")
            i += 2
            continue

        # Règle 3 : ـَة (fatha + tāʾ marbūṭa) → "a" en pause, drop harakat suivant
        if c == FATHA and nxt == TA_MARBUTA:
            out.append("a")
            i += 2
            while i < n and chars[i] in HARAKAT_SET:
                i += 1
            continue

        # Règle 2 : i'rāb final → drop (damma et kasra uniquement).
        # La fatha finale n'est PAS dropée : elle peut être la voyelle structurelle
        # d'un particle (مَعَ, وَ, ...) — l'i'rāb fatha (accusatif) est rare en pause.
        if c in (DAMMA, KASRA) and is_end:
            i += 1
            continue

        # Voyelle courte standalone
        if c == FATHA:
            out.append("a")
            i += 1
            continue
        if c == DAMMA:
            out.append("u")
            i += 1
            continue
        if c == KASRA:
            out.append("i")
            i += 1
            continue

        # Tāʾ marbūṭa isolée → "a" (consume harakat after)
        if c == TA_MARBUTA:
            out.append("a")
            i += 1
            while i < n and chars[i] in HARAKAT_SET:
                i += 1
            continue

        # Alif standalone (long /ā/)
        if c == ALIF:
            out.append("a")
            i += 1
            continue
        # Alif maqsura
        if c == ALIF_MAQSURA:
            out.append("a")
            i += 1
            continue

        # Wāw / Yāʾ consonantiques (les cas vocaliques longs ont été consommés ci-dessus)
        if c == WAW:
            out.append("w")
            i += 1
            continue
        if c == YA:
            out.append("y")
            i += 1
            continue

        # Mapping DIN standard (consonnes)
        if c in DIN_31635:
            out.append(DIN_31635[c])
        elif c.isascii() and (c.isalnum() or c == "-"):
            out.append(c)
        i += 1
    return "".join(out)


def _translit(text: str) -> str:
    """Wrapper mot par mot, préserve espaces et tirets."""
    parts = re.split(r"(\s+|-)", text)
    out: list[str] = []
    for part in parts:
        if not part:
            continue
        if part.isspace() or part == "-":
            out.append(part)
        else:
            out.append(_translit_word(part))
    return "".join(out)


def _ascii_fold(text: str) -> str:
    return "".join(ASCII_FOLD.get(c, c) for c in text)


def _clean(s: str) -> str:
    s = s.lower()
    s = re.sub(r"\s+", "-", s)
    s = re.sub(r"[^a-z0-9-]", "", s)
    s = re.sub(r"-+", "-", s)
    return s.strip("-")


def ar_to_slug(titre_ar: str) -> str:
    """Translittère un titre arabe (de préférence vocalisé) en slug ASCII kebab.

    Pour input vocalisé (ex. sortie Mishkal) :
      - drop tanwin terminal et i'rāb final
      - voyelles longues : fatha+alif/yāʾ_maqsura, damma+wāw, kasra+yāʾ → 1 voyelle
      - ـَة → "a" en forme pause
      - hamza-bearing → drop si harakat suit, sinon valeur défaut
    """
    words = titre_ar.strip().split()
    words = [_split_al_prefix(w) for w in words]
    text = " ".join(words)
    translit = _translit(text)
    folded = _ascii_fold(translit)
    return _clean(folded)


def main() -> int:
    if not CORPUS_PATH.exists():
        print(f"Corpus introuvable : {CORPUS_PATH}", file=sys.stderr)
        return 2

    rows: list[dict[str, str]] = []
    with CORPUS_PATH.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            rows.append(row)

    matches = 0
    mismatches: list[tuple[str, str, str, bool]] = []

    print(f"Corpus : {len(rows)} entrées\n")

    for row in rows:
        titre = row["titre_ar"]
        attendu = row["slug_attendu"]
        obtenu = ar_to_slug(titre)
        regex_ok = bool(SLUG_RE.match(obtenu)) if obtenu else False

        if obtenu == attendu:
            matches += 1
            print(f"OK   {titre:<25}  ->  {obtenu}")
        else:
            mismatches.append((titre, attendu, obtenu, regex_ok))
            print(f"FAIL {titre:<25}")
            print(f"       attendu : {attendu}")
            print(f"       obtenu  : {obtenu}  (regex_ok={regex_ok})")

    total = len(rows)
    print()
    print(f"Resultat : {matches}/{total} matchs ({100*matches/total:.1f}%)")
    print(f"Ecarts   : {len(mismatches)}")

    return 0 if matches == total else 1


if __name__ == "__main__":
    sys.exit(main())
