"""S2 - Assemble s2_stats.json a partir des sorties des 2 branches + install_log.

Fusionne :
  - s2a_sam2_stats.json     (S2a SAM 2 sur manga : n_regions par sujet)
  - s2b_infodraw_stats.json (S2b infodraw : couverture/proprete encre)
  - s2b_compare_stats.json  (S2b 4 sources : metriques comparatives)
  - s1_out/s1_stats.json    (baseline k-means / L<25 POC 1 pour reference)
Et y ajoute l'install_log (commandes exactes, versions, frottements).
"""
from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT_DIR = HERE / "s2_out"
S1_OUT = HERE / "s1_out"

SUBJECTS = ["dog", "castle", "peacock"]


def main() -> int:
    sam = json.loads((OUT_DIR / "s2a_sam2_stats.json").read_text(encoding="utf-8"))
    infodraw = json.loads((OUT_DIR / "s2b_infodraw_stats.json").read_text(encoding="utf-8"))
    compare = json.loads((OUT_DIR / "s2b_compare_stats.json").read_text(encoding="utf-8"))
    s1 = json.loads((S1_OUT / "s1_stats.json").read_text(encoding="utf-8"))
    s1_by_id = {r["id"]: r for r in s1["images"]}

    # ---- S2a : k-means vs SAM 2 par sujet manga ----
    s2a = {"branch": "S2a", "style": "manga",
           "model": sam["model"], "config": sam["config"],
           "device": sam["device"], "amg_params": sam["amg_params"],
           "per_subject": {}}
    for subj in SUBJECTS:
        rid = f"manga_{subj}"
        s2a["per_subject"][rid] = {
            "n_regions_kmeans_poc1": s1_by_id[rid]["n_regions_final"],
            "n_sam_masks": sam["results"][rid]["n_sam_masks"],
            "n_regions_sam2_raw": sam["results"][rid]["n_regions_sam_raw"],
            "n_regions_sam2_final": sam["results"][rid]["n_regions_final"],
            "smooth_merges": sam["results"][rid]["smooth_merges"],
            "time_sam_s": sam["results"][rid]["time_sam_s"],
        }

    # ---- S2b : 4 sources d'encre par sujet 3d ----
    s2b = {"branch": "S2b", "style": "3d",
           "model": infodraw["model"], "infer_size": infodraw["infer_size"],
           "bin_threshold": infodraw["bin_threshold"], "device": infodraw["device"],
           "per_subject": {}}
    for subj in SUBJECTS:
        rid = f"3d_{subj}"
        cmp = compare["per_subject"][rid]
        s2b["per_subject"][rid] = {
            "L25_poc1": {
                "pct_ink": s1_by_id[rid]["pct_ink_mask"],
                "n_ink_components": cmp["L25_poc1"]["n_ink_components"],
            },
            "infodraw_anime": {
                "pct_ink": cmp["infodraw_anime"]["pct_ink"],
                "n_ink_components": cmp["infodraw_anime"]["n_ink_components"],
                "time_s": infodraw["results"][rid]["anime_style"]["time_s"],
            },
            "infodraw_contour": {
                "pct_ink": cmp["infodraw_contour"]["pct_ink"],
                "n_ink_components": cmp["infodraw_contour"]["n_ink_components"],
                "time_s": infodraw["results"][rid]["contour_style"]["time_s"],
            },
            "fallback_2weight_partition": cmp["fallback_2weight"],
        }
    s2b["ink_metric_notes"] = (
        "pct_ink = %% pixels encre (couverture). n_ink_components = nb composantes "
        "connexes 8-conn de l'encre (proxy continuite : moins = plus continu/propre, "
        "plus = morcele/bruite). fallback_2weight : n_thick/thin_arcs = nb d'arcs "
        "topologiques classes sujet/fond (epais) vs internes (fin)."
    )

    install_log = {
        "platform": "Windows 11, Python 3.11.9, pip-only (pas de conda), torch CPU.",
        "gpu_note": (
            "torch installe = 2.12.0+cpu : CUDA NON disponible dans ce Python. "
            "SAM 2 et informative-drawings ont donc tourne en CPU. ComfyUI tourne "
            "sur le GPU dans un autre environnement, non partage avec ce Python."
        ),
        "S2a_sam2": {
            "status": "OK",
            "commands": [
                "pip install torchvision  (-> torchvision 0.27.0+cpu, prerequis manquant)",
                "pip install \"SAM-2 @ git+https://github.com/facebookresearch/sam2.git\"  (build wheel local OK)",
                "download checkpoint : https://dl.fbaipublicfiles.com/segment_anything_2/092824/sam2.1_hiera_small.pt (184 MB) via urllib",
                "config bundlee dans le package : configs/sam2.1/sam2.1_hiera_s.yaml",
            ],
            "versions": {
                "torch": "2.12.0+cpu", "torchvision": "0.27.0+cpu",
                "sam2": "sam_2-1.0", "hydra-core": "1.3.2", "omegaconf": "2.3.0",
                "checkpoint": "sam2.1_hiera_small.pt (184 MB)",
            },
            "frictions": [
                "torchvision n'etait pas installe (torch CPU seul) : pip install torchvision requis avant SAM 2.",
                "Warning a l'execution : \"cannot import name '_C' from 'sam2'\" -> extension CUDA C++ optionnelle non compilee (normal en pip-only Windows). SAM 2 skip le post-processing des masques mais les resultats AMG sont valides (cf. https://github.com/facebookresearch/sam2 INSTALL.md). AUCUN impact bloquant.",
                "AMG en CPU : ~41 s/image (1024x1024, points_per_side=32). Acceptable pour 3 images.",
            ],
        },
        "S2b_infodraw": {
            "status": "OK",
            "commands": [
                "git clone --depth 1 https://github.com/carolineec/informative-drawings.git",
                "pip install gdown",
                "python -m gdown 1MIdHzecxz-z0uY3ARL_R40DlKcuQxiDk -O model.zip  (47.7 MB, weights officiels)",
                "unzip -> checkpoints/model/{anime_style,contour_style,opensketch_style}/netG_A_latest.pth",
            ],
            "versions": {"gdown": "6.1.0", "repo": "carolineec/informative-drawings (depth 1)"},
            "frictions": [
                "test.py officiel est cuda-only (.cuda() en dur) : on importe Generator (model.py) et on l'execute en CPU via un script maison (s2b_infodraw.py). Aucune modif du repo.",
                "Pas de frottement reseau : gdown a recupere le zip Google Drive directement (confirm token auto).",
            ],
            "fallback_anime2sketch": "NON utilise : informative-drawings a fonctionne du premier coup (anime_style + contour_style). Branche fallback non declenchee.",
        },
    }

    out = {
        "gate": "S2",
        "scope": "SPIKE CIBLE : S2a (SAM 2 / manga) + S2b (traits appris / 3D) uniquement. Pas de S3, pas d'autres styles.",
        "no_verdict": "Comparaisons produites, verdict humain par branche/style sur les planches.",
        "planches": {
            "s2a_manga": "s2_out/planche_s2a_manga.png",
            "s2b_3d": "s2_out/planche_s2b_3d.png",
        },
        "S2a": s2a,
        "S2b": s2b,
        "install_log": install_log,
    }
    (OUT_DIR / "s2_stats.json").write_text(
        json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print("OK s2_stats.json")
    # Petit recap console
    print("\n--- S2a manga : k-means POC1 -> SAM 2 (n_regions) ---")
    for subj in SUBJECTS:
        rid = f"manga_{subj}"
        d = s2a["per_subject"][rid]
        print(f"  {rid:14s} k-means {d['n_regions_kmeans_poc1']:4d}  ->  "
              f"SAM2 {d['n_regions_sam2_final']:4d}  ({d['n_sam_masks']} masks)")
    print("\n--- S2b 3d : 4 sources d'encre (pct_ink / n_cc) ---")
    for subj in SUBJECTS:
        rid = f"3d_{subj}"
        d = s2b["per_subject"][rid]
        print(f"  {rid:12s} L25 {d['L25_poc1']['pct_ink']:5.2f}%  "
              f"anime {d['infodraw_anime']['pct_ink']:5.2f}%  "
              f"contour {d['infodraw_contour']['pct_ink']:5.2f}%  "
              f"2w {d['fallback_2weight_partition']['pct_ink']:5.2f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
