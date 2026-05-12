"""Calibration des seuils QC déterministes (brief 2026-05-10).

Exécute les 5 métriques QC sur N PNG du dossier ``data/outputs/`` et
affiche la distribution + un mini-tableau (filename → métriques + tags
posés). Sortie ASCII, pas de DB, pas de réseau.

Utilisation :
    python scripts/calibrate_qc_thresholds.py [N=20]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from workers.qc_worker import compute_qc_metrics, evaluate_qc_tags  # noqa: E402


def main() -> int:
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 20
    outputs_dir = PROJECT_ROOT / "data" / "outputs"
    pngs = sorted(outputs_dir.glob("*.png"))
    if not pngs:
        print(f"Aucun PNG dans {outputs_dir}")
        return 1
    sample = pngs[:n]
    rows: list[dict] = []
    for p in sample:
        m = compute_qc_metrics(p)
        leaf = p.stem.split("_job_")[0] if "_job_" in p.stem else p.stem
        # Cas: le nom de fichier ne correspond pas exactement à un leaf_id ;
        # on l'utilise juste pour tester la règle qc_color_intrinsic
        # (rainbow_*, etc.) — la plupart des samples ne matcheront pas.
        tags = evaluate_qc_tags(m, leaf)
        row = {
            "file": p.name,
            **m,
            "leaf_guess": leaf,
            "tags": tags,
        }
        rows.append(row)

    # Distribution des métriques
    if any(r.get("readable") for r in rows):
        cr = sorted(r["color_ratio"] for r in rows if r.get("readable"))
        ist = sorted(r["intensity_std"] for r in rows if r.get("readable"))
        ec = sorted(r["edge_count"] for r in rows if r.get("readable"))
        br = sorted(r["black_ratio"] for r in rows if r.get("readable"))

        def stats(name: str, xs: list) -> None:
            if not xs:
                print(f"  {name}: aucune valeur")
                return
            print(
                f"  {name}: min={xs[0]:.4f} median={xs[len(xs)//2]:.4f} "
                f"p90={xs[int(len(xs)*0.9)]:.4f} max={xs[-1]:.4f}"
            )

        print(f"== Calibration QC sur {len(rows)} images ==")
        print("Distribution :")
        stats("color_ratio", cr)
        stats("intensity_std", ist)
        stats("edge_count", ec)
        stats("black_ratio", br)

    # Tag occurrence
    tag_counts: dict[str, int] = {}
    for r in rows:
        for t in r["tags"]:
            tag_counts[t] = tag_counts.get(t, 0) + 1
    print("\nFréquence des tags posés :")
    for tag, c in sorted(tag_counts.items(), key=lambda x: -x[1]):
        print(f"  {tag}: {c}/{len(rows)}")

    # Detail
    print("\nDetail (file -> tags) :")
    for r in rows:
        if not r.get("readable"):
            print(f"  {r['file']} : UNREADABLE ({r.get('error')})")
            continue
        print(
            f"  {r['file']} : color_ratio={r['color_ratio']:.4f} "
            f"std={r['intensity_std']:.2f} edges={r['edge_count']} "
            f"black={r['black_ratio']:.3f} -> {r['tags']}"
        )

    # Dump JSON pour le rapport
    out_json = PROJECT_ROOT / "docs" / "reports" / "2026-05-10_qc-auto-worker.json"
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(
        json.dumps(rows, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\nDump JSON : {out_json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
