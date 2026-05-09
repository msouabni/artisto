"""POC jetable : Ollama vocalise-t-il l'arabe de façon fiable ?

Sonde 10 titres du corpus, demande à Ollama d'ajouter les harakat (T=0),
puis passe le résultat dans la fonction ar_to_slug du POC translittération.

Usage :
    python scripts/poc_ar_vocalisation.py
"""
from __future__ import annotations

import io
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
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from services.ollama_json import OLLAMA_MODEL, call_ollama_sync  # noqa: E402
from poc_ar_transliteration import SLUG_RE, ar_to_slug  # noqa: E402

TITRES = [
    "أسد في الغابة",
    "قط في المكتبة",
    "دب صغير",
    "فراشة ملونة",
    "حصان يركض",
    "سمكة في البحر",
    "زهرة جميلة",
    "فيل كبير",
    "كلب وفي",
    "غزال رشيق",
]

PROMPT_TPL = (
    "Vocalise ce titre arabe en ajoutant les harakat (tashkil) complets. "
    "Réponds uniquement avec le titre vocalisé, rien d'autre.\n"
    "Titre : {titre}"
)

# Caractères harakat (pour mesurer la densité de vocalisation)
HARAKAT = set("ًٌٍَُِّْٰ")
# fathatan, dammatan, kasratan, fatha, damma, kasra, shadda, sukun, dagger alif


def _harakat_density(text: str) -> tuple[int, int]:
    """Retourne (nb_harakat, nb_consonnes_arabes)."""
    h = sum(1 for c in text if c in HARAKAT)
    consonnes = sum(1 for c in text if "ء" <= c <= "ي" and c not in HARAKAT)
    return h, consonnes


def _clean_response(raw: str) -> str:
    """Retire balises think et lignes vides ; garde la première ligne non vide."""
    text = re.sub(r"<think>[\s\S]*?</think>", "", raw, flags=re.IGNORECASE).strip()
    for line in text.splitlines():
        line = line.strip().strip("«»\"'`")
        if line:
            return line
    return ""


def main() -> int:
    print(f"Modèle : {OLLAMA_MODEL}  ·  T=0  ·  {len(TITRES)} titres\n")

    rows: list[dict[str, str]] = []
    for titre in TITRES:
        prompt = PROMPT_TPL.format(titre=titre)
        t0 = time.time()
        try:
            raw = call_ollama_sync(prompt=prompt, system="", temperature=0.0)
            vocalise = _clean_response(raw)
            err = ""
        except Exception as exc:
            vocalise = ""
            err = f"{type(exc).__name__}: {exc}"
        dt = time.time() - t0

        slug = ar_to_slug(vocalise) if vocalise else ""
        regex_ok = bool(SLUG_RE.match(slug)) if slug else False
        h, cons = _harakat_density(vocalise)
        ratio = (h / cons) if cons else 0.0

        rows.append(
            {
                "titre": titre,
                "vocalise": vocalise,
                "slug": slug,
                "regex_ok": "OUI" if regex_ok else "non",
                "h_density": f"{h}/{cons} ({ratio:.2f})",
                "dt": f"{dt:.1f}s",
                "err": err,
            }
        )

    # Affichage tableau
    print(f"{'TITRE ORIGINAL':<25} | {'TITRE VOCALISÉ':<35} | {'SLUG PRODUIT':<25} | {'REGEX':<5} | {'HARAKAT':<14} | {'TEMPS':<6}")
    print("-" * 130)
    for r in rows:
        print(
            f"{r['titre']:<25} | {r['vocalise']:<35} | {r['slug']:<25} | {r['regex_ok']:<5} | {r['h_density']:<14} | {r['dt']:<6}"
        )
        if r["err"]:
            print(f"   ⚠ erreur : {r['err']}")

    print()
    nb_ok = sum(1 for r in rows if r["regex_ok"] == "OUI")
    nb_dense = sum(1 for r in rows if "/" in r["h_density"] and float(r["h_density"].split("(")[1].rstrip(")")) > 0.5)
    print(f"Slugs valides regex : {nb_ok}/{len(rows)}")
    print(f"Vocalisation dense (≥0.5 harakat/consonne) : {nb_dense}/{len(rows)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
