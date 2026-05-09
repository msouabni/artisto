"""Import des 24 annotations du benchmark v1 (poc-sampler-benchmark).

Appelle ``POST /api/benchmark/annotate`` une fois par image, puis verifie
que ``docs/reports/poc-sampler-benchmark/annotations.json`` contient bien
24 entrees.

Prerequis : l'API doit tourner sur http://127.0.0.1:8000
  python start.py --no-comfy --no-reload   # plus simple
  ou : cd src && python -m uvicorn api.main:app --host 127.0.0.1 --port 8000

Usage :
    python scripts/import_benchmark_annotations.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import httpx

PROJECT_ROOT = Path(__file__).resolve().parents[1]
API_BASE = "http://127.0.0.1:8000"
DIR = "poc-sampler-benchmark"
ANNOTATIONS_FILE = PROJECT_ROOT / "docs" / "reports" / DIR / "annotations.json"

ANNOTATIONS = [
    # SOCCER
    {"filename": "soccer_04s_normal_euler_cfg10_074319.png", "score": 3, "defects": [], "publishable": False, "notes": "qualité médiocre"},
    {"filename": "soccer_04s_karras_euler_cfg10_074319.png", "score": 2, "defects": ["2_objets", "3_jambes", "traits_flous"], "publishable": False, "notes": "deux ballons et trois jambes, le traçage du terrain est flou"},
    {"filename": "soccer_08s_normal_euler_cfg10_074319.png", "score": 2, "defects": ["2_objets", "3_jambes", "traits_flous", "traits_discontinus"], "publishable": False, "notes": "2 ballons + trois jambes + flou + 1 seul oeil, traits discontinus"},
    {"filename": "soccer_08s_karras_euler_cfg10_074319.png", "score": 8, "defects": ["traits_discontinus"], "publishable": True, "notes": "parfait : cheveux non colorié, beaucoup de détails à colorier. Traçage terrain correct avec quelques discontinuités près du personnage. 8/10 publiable"},
    {"filename": "soccer_12s_normal_euler_cfg10_074319.png", "score": 2, "defects": ["2_objets", "3_jambes", "traits_flous", "traits_discontinus"], "publishable": False, "notes": "2 ballons + trois jambes + flou + 1 seul oeil, traits discontinus"},
    {"filename": "soccer_12s_karras_euler_cfg10_074319.png", "score": 5, "defects": ["3_jambes"], "publishable": False, "notes": "ressemble à soccer_08s_karras mais troisième jambe non connectée au corps"},
    {"filename": "soccer_20s_normal_euler_cfg10_074319.png", "score": 9, "defects": ["gris_résiduel"], "publishable": False, "notes": "parfaite 9/10. Cheveux plus longs. Gris sur ombres et zone de marquage terrain devant le but. On y est presque"},
    {"filename": "soccer_20s_karras_euler_cfg10_074319.png", "score": 1, "defects": ["2_objets", "3_jambes"], "publishable": False, "notes": "2 ballons trois jambes, pas de flou, inexploitable"},
    # REFRIGERATOR
    {"filename": "refrigerator_04s_normal_euler_cfg10_42002.png", "score": 2, "defects": ["traits_doubles", "couleurs_résiduelles"], "publishable": False, "notes": "approximatif, trait en double, inexploitable, banane bleue, coeur inexpliqué"},
    {"filename": "refrigerator_04s_karras_euler_cfg10_42002.png", "score": 1, "defects": [], "publishable": False, "notes": "catastrophique"},
    {"filename": "refrigerator_08s_normal_euler_cfg10_42002.png", "score": 3, "defects": ["couleurs_résiduelles", "perspective_KO"], "publishable": False, "notes": "lignes déformées du plan de travail, banane bleue, perspective frigo incompréhensible, fenêtre OK"},
    {"filename": "refrigerator_08s_karras_euler_cfg10_42002.png", "score": 1, "defects": ["traits_doubles", "couleurs_résiduelles"], "publishable": False, "notes": "catastrophique, lignes en double, formes déformées, couleurs"},
    {"filename": "refrigerator_12s_normal_euler_cfg10_42002.png", "score": 5, "defects": ["2_objets", "couleurs_résiduelles"], "publishable": False, "notes": "pas mal sauf frigo fermé + porte ouverte en double. Banane bleue, coeur hors du plan de travail, perspective changée"},
    {"filename": "refrigerator_12s_karras_euler_cfg10_42002.png", "score": 1, "defects": [], "publishable": False, "notes": "catastrophique"},
    {"filename": "refrigerator_20s_normal_euler_cfg10_42002.png", "score": 5, "defects": ["2_objets", "couleurs_résiduelles"], "publishable": False, "notes": "pas mal, banane bleue, porte en double, plus de table"},
    {"filename": "refrigerator_20s_karras_euler_cfg10_42002.png", "score": 1, "defects": [], "publishable": False, "notes": "catastrophique"},
    # DRAGON
    {"filename": "dragon_04s_normal_euler_cfg10_42003.png", "score": 6, "defects": ["couleurs_résiduelles"], "publishable": False, "notes": "pas mal, beaucoup de détails, juste les drapeaux en rouge"},
    {"filename": "dragon_04s_karras_euler_cfg10_42003.png", "score": 1, "defects": [], "publishable": False, "notes": "catastrophique"},
    {"filename": "dragon_08s_normal_euler_cfg10_42003.png", "score": 8, "defects": ["couleurs_résiduelles"], "publishable": False, "notes": "parfaite à part les drapeaux en rouge"},
    {"filename": "dragon_08s_karras_euler_cfg10_42003.png", "score": 1, "defects": [], "publishable": False, "notes": "catastrophique"},
    {"filename": "dragon_12s_normal_euler_cfg10_42003.png", "score": 8, "defects": ["couleurs_résiduelles"], "publishable": False, "notes": "parfaite à part les drapeaux en rouge"},
    {"filename": "dragon_12s_karras_euler_cfg10_42003.png", "score": 1, "defects": [], "publishable": False, "notes": "catastrophique"},
    {"filename": "dragon_20s_normal_euler_cfg10_42003.png", "score": 9, "defects": ["couleurs_résiduelles"], "publishable": False, "notes": "parfaite, plus de détails, mais les drapeaux en rouge"},
    {"filename": "dragon_20s_karras_euler_cfg10_42003.png", "score": 1, "defects": [], "publishable": False, "notes": "catastrophique"},
]


def main() -> int:
    print(f"Import {len(ANNOTATIONS)} annotations -> {API_BASE}/api/benchmark/annotate")
    print(f"Dir : {DIR}\n")

    # Ping API
    try:
        with httpx.Client(timeout=5.0) as c:
            r = c.get(f"{API_BASE}/api/benchmark/images?dir={DIR}")
            if r.status_code != 200:
                print(f"X API repond mais GET /images echoue : HTTP {r.status_code} -- {r.text[:200]}", file=sys.stderr)
                return 1
            print(f"API OK ({r.json().get('count')} images dans le dir)\n")
    except httpx.ConnectError:
        print(
            f"X API injoignable sur {API_BASE}.\n"
            f"  Lance d'abord : python start.py --no-comfy --no-reload\n"
            f"  Ou : cd src && python -m uvicorn api.main:app --host 127.0.0.1 --port 8000",
            file=sys.stderr,
        )
        return 1

    n_ok = 0
    n_ko = 0
    with httpx.Client(timeout=15.0) as client:
        for i, a in enumerate(ANNOTATIONS, 1):
            payload = {
                "dir": DIR,
                "filename": a["filename"],
                "score": a["score"],
                "defects": a["defects"],
                "notes": a["notes"],
                "publishable": a["publishable"],
            }
            try:
                r = client.post(f"{API_BASE}/api/benchmark/annotate", json=payload)
                if r.status_code == 200:
                    n_ok += 1
                    print(f"  [{i:02d}/{len(ANNOTATIONS)}] OK  {a['filename']}  score={a['score']} defects={len(a['defects'])} pub={a['publishable']}")
                else:
                    n_ko += 1
                    print(f"  [{i:02d}/{len(ANNOTATIONS)}] X   {a['filename']}  HTTP {r.status_code} -- {r.text[:160]}")
            except Exception as exc:
                n_ko += 1
                print(f"  [{i:02d}/{len(ANNOTATIONS)}] X   {a['filename']}  {type(exc).__name__}: {exc}")

    print(f"\nResultat : {n_ok} OK / {n_ko} KO")

    # Verification finale : lire le fichier ecrit par l'API
    if not ANNOTATIONS_FILE.is_file():
        print(f"X Fichier {ANNOTATIONS_FILE} introuvable", file=sys.stderr)
        return 1
    data = json.loads(ANNOTATIONS_FILE.read_text(encoding="utf-8"))
    written = (data.get("annotations") or {})
    print(f"\nFichier {ANNOTATIONS_FILE.relative_to(PROJECT_ROOT)} : {len(written)} entrees")

    expected = {a["filename"] for a in ANNOTATIONS}
    actual = set(written.keys())
    missing = sorted(expected - actual)
    extra = sorted(actual - expected)
    if missing:
        print(f"  Manquantes : {missing}", file=sys.stderr)
    if extra:
        print(f"  En trop    : {extra}")

    if len(written) == len(ANNOTATIONS) and not missing:
        print("OK -- 24/24 annotations presentes dans annotations.json")
        return 0
    print("X -- mismatch", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
