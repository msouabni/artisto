"""POC jetable : vocalisation par Mishkal + ar_to_slug.

Charge le corpus, vocalise chaque titre via mishkal.tashkeel.TashkeelClass(),
puis passe le résultat dans ar_to_slug (version actuelle, non modifiée).

Usage :
    python scripts/poc_mishkal.py
"""
from __future__ import annotations

import csv
import io
import re
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
else:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

CORPUS_PATH = PROJECT_ROOT / "docs" / "xchange" / "ar_slug_corpus.csv"

try:
    from mishkal import tashkeel
except ImportError as exc:
    print(f"ERREUR import mishkal : {exc}", file=sys.stderr)
    sys.exit(2)

from poc_ar_transliteration import (  # noqa: E402
    SLUG_RE,
    apply_overrides_post,
    apply_overrides_pre,
    ar_to_slug,
)

# Catégories d'erreur
ERR_LEXICAL = "lexical"      # Mot mal vocalisé par Mishkal (mauvais sens / mauvaise voyelle)
ERR_ARTIFACT = "artifact"    # Vocalisation OK, mais ar_to_slug crée des artefacts (tanwin, voyelles doublées)
ERR_BOTH = "both"            # Les deux

# Heuristiques pour catégoriser
HARAKAT = set("ًٌٍَُِّْٰ")
TANWIN = set("ًٌٍ")  # fathatan, dammatan, kasratan


def _has_tanwin(s: str) -> bool:
    return any(c in TANWIN for c in s)


def _categorize_error(obtenu: str, attendu: str, vocalise: str) -> str:
    """Devine si l'écart vient de Mishkal ou de ar_to_slug."""
    has_tanwin = _has_tanwin(vocalise)
    # Doubled long vowels: aa, ii, uu adjacent in obtenu
    has_doubled = bool(re.search(r"(aa|ii|uu)", obtenu))
    artifact_signals = has_tanwin or has_doubled

    # Comparer squelettes consonantiques (drop voyelles courtes)
    def consonants_only(s: str) -> str:
        # Ne garde que les consonnes et les voyelles longues "structurelles"
        return re.sub(r"[aiu]", "", s)

    obt_skel = consonants_only(obtenu)
    att_skel = consonants_only(attendu)
    skel_match = obt_skel == att_skel

    if skel_match and artifact_signals:
        return ERR_ARTIFACT
    if not skel_match and artifact_signals:
        return ERR_BOTH
    return ERR_LEXICAL


def main() -> int:
    if not CORPUS_PATH.exists():
        print(f"Corpus introuvable : {CORPUS_PATH}", file=sys.stderr)
        return 2

    rows: list[dict[str, str]] = []
    with CORPUS_PATH.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            rows.append(row)

    print(f"Corpus : {len(rows)} entrées · vocalisation : Mishkal\n")

    print(f"{'TITRE':<22} | {'VOCALISÉ MISHKAL':<28} | {'SLUG OBTENU':<26} | {'SLUG ATTENDU':<22} | OK")
    print("-" * 130)

    vocaliser = tashkeel.TashkeelClass()
    matches: list[dict[str, str]] = []
    mismatches: list[dict[str, str]] = []

    for row in rows:
        titre = row["titre_ar"]
        attendu = row["slug_attendu"]
        # 1. OVERRIDES pré-Mishkal (mécanisme contrat)
        titre_pre = apply_overrides_pre(titre)
        try:
            mishkal_out = vocaliser.tashkeel(titre_pre).strip()
        except Exception as exc:
            print(f"⚠ {titre} → erreur Mishkal : {type(exc).__name__}: {exc}")
            continue
        # 2. OVERRIDES post-Mishkal (filet : Mishkal re-vocalise parfois)
        vocalise = apply_overrides_post(mishkal_out)

        slug = ar_to_slug(vocalise)
        regex_ok = bool(SLUG_RE.match(slug)) if slug else False
        ok = slug == attendu

        marker = "OK" if ok else "FAIL"
        print(f"{titre:<22} | {vocalise:<28} | {slug:<26} | {attendu:<22} | {marker}")

        record = {
            "titre": titre,
            "vocalise": vocalise,
            "slug": slug,
            "attendu": attendu,
            "regex_ok": str(regex_ok),
        }
        if ok:
            matches.append(record)
        else:
            record["err_type"] = _categorize_error(slug, attendu, vocalise)
            mismatches.append(record)

    total = len(rows)
    nb_ok = len(matches)
    nb_ko = len(mismatches)
    print()
    print(f"Score : {nb_ok}/{total} ({100*nb_ok/total:.1f}%)")
    print()

    if mismatches:
        # Compter par type
        by_type: dict[str, list[dict[str, str]]] = {ERR_LEXICAL: [], ERR_ARTIFACT: [], ERR_BOTH: []}
        for r in mismatches:
            by_type[r["err_type"]].append(r)
        print(f"Écarts : {nb_ko}")
        print(f"  - {len(by_type[ERR_LEXICAL])} lexicaux  (Mishkal vocalise mal)")
        print(f"  - {len(by_type[ERR_ARTIFACT])} artefacts (ar_to_slug à adapter)")
        print(f"  - {len(by_type[ERR_BOTH])} mixtes")
        print()
        for label, group in [
            ("LEXICAUX (Mishkal)", by_type[ERR_LEXICAL]),
            ("ARTEFACTS (ar_to_slug)", by_type[ERR_ARTIFACT]),
            ("MIXTES", by_type[ERR_BOTH]),
        ]:
            if not group:
                continue
            print(f"== {label} ==")
            for r in group:
                print(f"  {r['titre']:<22} | voc={r['vocalise']:<26} | obtenu={r['slug']:<22} | attendu={r['attendu']}")
            print()

    return 0 if nb_ok == total else 1


if __name__ == "__main__":
    sys.exit(main())
