"""Smoke test du service vectorisation (VTracer).

Genere 3 PNG line-art synthetiques (gris + speckle) dans un tmpdir, lance le
CLI ``report`` sur les 4 presets et verifie :
  (1) SVG non vides ;
  (2) HTML auto-contenu produit pour chaque preset ;
  (3) tmp interne nettoye.

Lancer depuis la racine du repo :
    python scripts/_vectorize_smoketest.py
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import cv2
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _make_test_pngs(out_dir: Path) -> list[Path]:
    """Genere 3 line-art synthetiques 512x512 avec degrades gris + speckle."""
    out_dir.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(42)
    paths: list[Path] = []

    # 1) Cercles concentriques + traits gris + poivre
    img = np.full((512, 512), 245, dtype=np.uint8)
    cv2.circle(img, (256, 256), 180, 0, 3)
    cv2.circle(img, (256, 256), 120, 110, 2)
    cv2.line(img, (90, 256), (422, 256), 50, 2)
    img[rng.random(img.shape) < 0.005] = 0
    p = out_dir / "circle_gris.png"
    cv2.imwrite(str(p), img)
    paths.append(p)

    # 2) Carres concentriques + diagonale discontinue + bruit gaussien
    img = np.full((512, 512), 250, dtype=np.uint8)
    for size in (60, 130, 200):
        cv2.rectangle(img, (256 - size, 256 - size), (256 + size, 256 + size), 0, 2)
    for x in range(40, 472, 40):
        cv2.line(img, (x, 40), (x + 25, 65), 0, 2)
    noise = rng.normal(0, 12, img.shape)
    img = np.clip(img.astype(np.int16) + noise.astype(np.int16), 0, 255).astype(np.uint8)
    p = out_dir / "carres_speckle.png"
    cv2.imwrite(str(p), img)
    paths.append(p)

    # 3) Triangle + courbe + bande grise (test seuillage Otsu)
    img = np.full((512, 512), 230, dtype=np.uint8)
    pts = np.array([[256, 80], [80, 432], [432, 432]], np.int32)
    cv2.polylines(img, [pts], isClosed=True, color=0, thickness=3)
    cv2.ellipse(img, (256, 300), (140, 70), 0, 0, 180, 80, 2)
    img[100:140, :] = np.clip(img[100:140, :].astype(np.int16) - 35, 0, 255).astype(np.uint8)
    img[rng.random(img.shape) < 0.003] = 0
    p = out_dir / "triangle_courbe.png"
    cv2.imwrite(str(p), img)
    paths.append(p)

    return paths


def _check_html(path: Path, expected_min_svgs: int) -> tuple[bool, str]:
    if not path.exists():
        return False, f"HTML manquant : {path}"
    text = path.read_text(encoding="utf-8")
    n_svg = text.count("<svg")
    n_path = text.count("<path")
    if n_svg < expected_min_svgs:
        return False, f"trop peu de <svg> ({n_svg} < {expected_min_svgs})"
    if n_path < expected_min_svgs:
        return False, f"trop peu de <path> ({n_path} < {expected_min_svgs})"
    return True, f"{len(text) // 1024} KB, {n_svg} <svg>, {n_path} <path>"


def _run_cli(workspace: Path, preset: str, pre_clean: bool = False) -> tuple[bool, str]:
    out_html = workspace / f"report_{preset}{'_preclean' if pre_clean else ''}.html"
    cmd = [
        sys.executable,
        str(PROJECT_ROOT / "scripts" / "vectorize_cli.py"),
        "report",
        str(workspace / "inputs"),
        "--out",
        str(out_html),
        "--preset",
        preset,
    ]
    if pre_clean:
        cmd.append("--pre-clean")
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(PROJECT_ROOT))
    if result.returncode != 0:
        return False, (result.stderr or result.stdout).strip()

    ok, detail = _check_html(out_html, expected_min_svgs=3)
    return ok, detail


def main() -> int:
    workspace = Path(tempfile.mkdtemp(prefix="vectorize_smoke_"))
    inputs = workspace / "inputs"
    print(f"=== smoketest workspace = {workspace} ===")
    results: list[tuple[str, bool, str]] = []
    try:
        _make_test_pngs(inputs)
        print(f"[setup] 3 PNG synthetiques dans {inputs}")

        # Boucle sur les 4 presets + un cas pre-clean.
        for preset in ("bw_default", "bw_clean", "bw_detail", "bw_polygon"):
            ok, detail = _run_cli(workspace, preset, pre_clean=False)
            results.append((f"preset={preset}", ok, detail))
            print(f"  [{'OK ' if ok else 'FAIL'}] preset={preset:<12}  {detail}")

        ok, detail = _run_cli(workspace, "bw_default", pre_clean=True)
        results.append(("preset=bw_default + pre_clean", ok, detail))
        print(f"  [{'OK ' if ok else 'FAIL'}] preset=bw_default + pre_clean  {detail}")

        # Verifie qu'aucun tmp 'vectorize_report_*' ne traine.
        tmp_root = Path(tempfile.gettempdir())
        leftovers = [p for p in tmp_root.glob("vectorize_report_*") if p.is_dir()]
        tmp_ok = len(leftovers) == 0
        results.append((
            "tmp interne nettoye",
            tmp_ok,
            "OK" if tmp_ok else f"leftovers : {leftovers}",
        ))
        print(f"  [{'OK ' if tmp_ok else 'WARN'}] tmp interne nettoye  {results[-1][2]}")

        print()
        print("=" * 60)
        all_ok = all(ok for _, ok, _ in results)
        for label, ok, detail in results:
            print(f"  {'OK  ' if ok else 'FAIL'}  {label}  -  {detail}")
        print("=" * 60)
        print(f"VERDICT : {'PASS' if all_ok else 'FAIL'}")
        return 0 if all_ok else 1
    finally:
        if os.environ.get("VECTORIZE_KEEP_WORKSPACE"):
            print(f"(workspace preserved : {workspace})")
        else:
            shutil.rmtree(workspace, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
