"""POC bench garde-fou T25 — script verdict (étape 3 du brief 2026-05-10).

Brief source : docs/architect/briefs/2026-05-10_brief-bench-gardefou-T25.md

Charge `docs/reports/poc-bench-T25-postPivot/annotations.json`, calcule le taux
post-pivot des tags `image_pas_coherente` + `image_incomprehensible`, le compare
à la baseline (53.8 %) et émet un verdict PROMOTION ou RETRAIT T25, écrit dans
`docs/reports/2026-05-10_bench-T25-gardefou-postPivot.md`.

Critère (formule §84 du brief) :
    taux_post = (n_pas_coherente + n_incomprehensible) / (2 × N_annoté)
    seuil    = 0.70 × 0.538 = 0.3766
    si taux_post < seuil  → PROMOTION T25
    sinon                 → RETRAIT T25 (switch flag _T2T3T23_GRID_AVAILABLE = False)

Si N_annoté < N_MIN_ANNOTATED (15), on émet un rapport "EN ATTENTE D'ANNOTATION"
plutôt qu'un verdict.

Usage :
    python scripts/poc_bench_T25_verdict.py
    python scripts/poc_bench_T25_verdict.py --annotations <path> --report <path>
    python scripts/poc_bench_T25_verdict.py --index <path>   # pour lister les 20 leaves
"""

from __future__ import annotations

import argparse
import io
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Force UTF-8 sur stdout/stderr Windows (cp1252 par défaut casse sur les émojis et symboles math)
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except Exception:
        # Fallback : wrappe stdout en TextIOWrapper utf-8 (Py 3.6 style)
        try:
            sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
            sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
        except Exception:
            pass

# ─── Constantes ─────────────────────────────────────────────────────────────

REPO_ROOT = Path(__file__).resolve().parents[1]

DEFAULT_ANNOTATIONS = (
    REPO_ROOT / "docs" / "reports" / "poc-bench-T25-postPivot" / "annotations.json"
)
DEFAULT_INDEX = (
    REPO_ROOT / "docs" / "reports" / "poc-bench-T25-postPivot" / "index-bench-T25.json"
)
DEFAULT_REPORT = (
    REPO_ROOT / "docs" / "reports" / "2026-05-10_bench-T25-gardefou-postPivot.md"
)

# Baseline calculée dans le brief §16-29 :
#   14 occurrences `image_pas_coherente` + 14 `image_incomprehensible` sur 26 leaves
#   taux_baseline = (14 + 14) / (2 × 26) = 28 / 52 = 0.5384615…
N_BASELINE_PAS_COHERENTE = 14
N_BASELINE_INCOMPREHENSIBLE = 14
N_BASELINE_LEAVES = 26
TAUX_BASELINE = (N_BASELINE_PAS_COHERENTE + N_BASELINE_INCOMPREHENSIBLE) / (
    2 * N_BASELINE_LEAVES
)  # = 0.5384615384615384

# Seuil retrait : 70 % du taux baseline (formule §84 du brief)
SEUIL_RATIO = 0.70
SEUIL_TAUX = SEUIL_RATIO * TAUX_BASELINE  # ≈ 0.3769

# N annotés minimum pour émettre un verdict (brief §134 garde-fou ComfyUI)
N_MIN_ANNOTATED = 15

# Tags à compter
TAGS_DEFAUT = ("image_pas_coherente", "image_incomprehensible")


# ─── Helpers NULL-safe ──────────────────────────────────────────────────────


def _safe_int(value: Any, default: int = 0) -> int:
    """Convertit en int en gérant None / NULL."""
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_list(value: Any) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return []


# ─── Lecture annotations ────────────────────────────────────────────────────


def load_annotations(path: Path) -> dict[str, Any]:
    """Charge le JSON annotations. Retourne dict vide si fichier absent ou vide."""
    if not path.exists():
        return {"annotations": {}, "_status": "FILE_NOT_FOUND", "_path": str(path)}

    try:
        raw = path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        return {
            "annotations": {},
            "_status": "READ_ERROR",
            "_path": str(path),
            "_error": str(exc),
        }

    if not raw:
        return {"annotations": {}, "_status": "EMPTY_FILE", "_path": str(path)}

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        return {
            "annotations": {},
            "_status": "JSON_ERROR",
            "_path": str(path),
            "_error": str(exc),
        }

    if not isinstance(data, dict):
        return {"annotations": {}, "_status": "BAD_SHAPE", "_path": str(path)}

    if "annotations" not in data or not isinstance(data["annotations"], dict):
        # cas où le fichier serait directement un dict d'annotations sans wrapper
        if all(isinstance(v, dict) for v in data.values()):
            return {"annotations": data, "_status": "OK_FLAT", "_path": str(path)}
        return {"annotations": {}, "_status": "NO_ANNOTATIONS_KEY", "_path": str(path)}

    return {**data, "_status": "OK", "_path": str(path)}


def load_index(path: Path) -> list[dict[str, Any]]:
    """Charge l'index-bench-T25.json. Retourne [] si absent."""
    if not path.exists():
        return []

    try:
        raw = path.read_text(encoding="utf-8").strip()
    except OSError:
        return []

    if not raw:
        return []

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []

    if isinstance(data, dict) and "subjects" in data:
        subjects = data["subjects"]
        if isinstance(subjects, list):
            return subjects
    if isinstance(data, list):
        return data
    return []


# ─── Calcul verdict ─────────────────────────────────────────────────────────


def compute_stats(annotations: dict[str, Any]) -> dict[str, Any]:
    """Calcule N_annoté + comptage des tags défaut.

    Une entrée est considérée "annotée" si elle a un score numérique non-null.
    """
    n_annotated = 0
    n_pas_coherente = 0
    n_incomprehensible = 0
    rows = []

    for filename, entry in sorted(annotations.items()):
        if not isinstance(entry, dict):
            continue
        score_raw = entry.get("score")
        score = _safe_int(score_raw, default=0)
        is_scored = score_raw is not None and score > 0
        image_tags = _safe_list(entry.get("image_tags"))

        if is_scored:
            n_annotated += 1
        has_pas_coherente = "image_pas_coherente" in image_tags
        has_incomprehensible = "image_incomprehensible" in image_tags
        if is_scored:
            if has_pas_coherente:
                n_pas_coherente += 1
            if has_incomprehensible:
                n_incomprehensible += 1

        rows.append(
            {
                "filename": filename,
                "score": score if is_scored else None,
                "image_tags": image_tags,
                "is_scored": is_scored,
            }
        )

    if n_annotated > 0:
        taux_post = (n_pas_coherente + n_incomprehensible) / (2 * n_annotated)
    else:
        taux_post = None

    return {
        "n_annotated": n_annotated,
        "n_pas_coherente": n_pas_coherente,
        "n_incomprehensible": n_incomprehensible,
        "taux_post": taux_post,
        "rows": rows,
    }


def decide_verdict(stats: dict[str, Any]) -> dict[str, Any]:
    """Décide PROMOTION / RETRAIT / EN_ATTENTE selon la formule §84."""
    n_annotated = _safe_int(stats.get("n_annotated"), default=0)
    taux_post = stats.get("taux_post")

    if n_annotated == 0:
        return {
            "status": "EN_ATTENTE",
            "reason": "Aucune annotation présente.",
            "verdict": None,
        }

    if n_annotated < N_MIN_ANNOTATED:
        return {
            "status": "EN_ATTENTE",
            "reason": (
                f"N_annoté = {n_annotated} < seuil minimal {N_MIN_ANNOTATED} "
                f"(brief §134). Manque {N_MIN_ANNOTATED - n_annotated} annotations."
            ),
            "verdict": None,
        }

    if taux_post is None:
        return {
            "status": "EN_ATTENTE",
            "reason": "taux_post non calculable (N_annoté = 0).",
            "verdict": None,
        }

    if taux_post < SEUIL_TAUX:
        return {
            "status": "DECIDED",
            "verdict": "PROMOTION",
            "reason": (
                f"taux_post = {taux_post:.4f} < seuil {SEUIL_TAUX:.4f} "
                f"(70 % x baseline {TAUX_BASELINE:.4f})"
            ),
        }
    return {
        "status": "DECIDED",
        "verdict": "RETRAIT",
        "reason": (
            f"taux_post = {taux_post:.4f} >= seuil {SEUIL_TAUX:.4f} "
            f"(70 % x baseline {TAUX_BASELINE:.4f})"
        ),
    }


# ─── Rendu rapport markdown ─────────────────────────────────────────────────


def _fmt_pct(value: float | None) -> str:
    if value is None:
        return "N/A"
    return f"{value * 100:.2f} %"


def render_report(
    stats: dict[str, Any],
    decision: dict[str, Any],
    index_subjects: list[dict[str, Any]],
    annotations_status: str,
    annotations_path: Path,
) -> str:
    n_annotated = _safe_int(stats.get("n_annotated"), default=0)
    n_pc = _safe_int(stats.get("n_pas_coherente"), default=0)
    n_in = _safe_int(stats.get("n_incomprehensible"), default=0)
    taux_post = stats.get("taux_post")
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    lines: list[str] = []
    lines.append("# POC — Bench garde-fou T25 (verdict post-pivot)")
    lines.append(f"Date : {today}")
    lines.append("")
    lines.append("## Contexte")
    lines.append("")
    lines.append(
        "Verdict du bench garde-fou T25 mesurant l'impact du pivot 2026-05-10 "
        "(templates `template_frieze_1xN` + `template_grid_3x3_imagier` réécrits "
        "en BEFORE/AFTER + SPOT THE DIFFERENCE) sur le taux de défauts composition "
        "(`image_pas_coherente` + `image_incomprehensible`)."
    )
    lines.append("")
    lines.append(
        f"Brief source : `docs/architect/briefs/2026-05-10_brief-bench-gardefou-T25.md`."
    )
    lines.append("")
    lines.append(
        f"Annotations lues depuis : `{annotations_path.relative_to(REPO_ROOT) if annotations_path.is_absolute() and annotations_path.exists() else annotations_path}` "
        f"(statut : {annotations_status})."
    )
    lines.append("")

    # Liste des leaves testées (depuis index si dispo)
    lines.append("## Leaves testées (index-bench-T25.json)")
    lines.append("")
    if index_subjects:
        lines.append("| # | leaf_id | workflow_class | seed | output_file |")
        lines.append("|---|---|---|---|---|")
        for i, subj in enumerate(index_subjects, start=1):
            if not isinstance(subj, dict):
                continue
            leaf_id = subj.get("leaf_id") or subj.get("id") or "?"
            wf = subj.get("workflow_class") or "?"
            seed = subj.get("seed")
            seed_str = str(seed) if seed is not None else "?"
            out = subj.get("output_file") or subj.get("filename") or "?"
            lines.append(f"| {i} | `{leaf_id}` | {wf} | {seed_str} | `{out}` |")
        lines.append("")
    else:
        lines.append("*(index-bench-T25.json absent ou vide à l'heure du verdict)*")
        lines.append("")

    # Annotations
    lines.append("## Annotations utilisateur")
    lines.append("")
    rows = stats.get("rows") or []
    scored_rows = [r for r in rows if r.get("is_scored")]
    if scored_rows:
        lines.append("| filename | score | image_tags |")
        lines.append("|---|---|---|")
        for row in scored_rows:
            tags = row.get("image_tags") or []
            tags_str = ", ".join(f"`{t}`" for t in tags) if tags else "—"
            score = row.get("score")
            score_str = str(score) if score is not None else "—"
            lines.append(f"| `{row['filename']}` | {score_str} | {tags_str} |")
        lines.append("")
    else:
        lines.append("*(aucune entrée scorée pour le moment)*")
        lines.append("")

    # Calcul
    lines.append("## Calcul taux post-pivot vs baseline")
    lines.append("")
    lines.append("| Métrique | Baseline pré-pivot | Post-pivot |")
    lines.append("|---|---|---|")
    lines.append(
        f"| N (leaves annotées) | {N_BASELINE_LEAVES} | {n_annotated} |"
    )
    lines.append(
        f"| `image_pas_coherente` | {N_BASELINE_PAS_COHERENTE} | {n_pc} |"
    )
    lines.append(
        f"| `image_incomprehensible` | {N_BASELINE_INCOMPREHENSIBLE} | {n_in} |"
    )
    lines.append(
        f"| Taux ((pc+inc) / (2×N)) | {_fmt_pct(TAUX_BASELINE)} | {_fmt_pct(taux_post)} |"
    )
    lines.append("")
    lines.append(
        f"Seuil retrait (70 % × baseline) = **{_fmt_pct(SEUIL_TAUX)}** "
        f"(formule §84 du brief)."
    )
    lines.append("")

    # Verdict
    lines.append("## Décision / Action suivante")
    lines.append("")
    status = decision.get("status")
    if status == "EN_ATTENTE":
        lines.append(f"**EN ATTENTE D'ANNOTATION** — {decision.get('reason')}")
        lines.append("")
        lines.append(
            f"Relancer ce script (`python scripts/poc_bench_T25_verdict.py`) une "
            f"fois N_annoté ≥ {N_MIN_ANNOTATED}."
        )
    elif decision.get("verdict") == "PROMOTION":
        lines.append("**Verdict : PROMOTION T25** — pivot maintenu en prod.")
        lines.append("")
        lines.append(decision.get("reason", ""))
        lines.append("")
        lines.append(
            "Aucune action sur `src/services/prompt_generator.py`. Statu quo. "
            "Le pivot 2026-05-10 (`template_frieze_1xN` + `template_grid_3x3_imagier` "
            "BEFORE/AFTER + SPOT THE DIFFERENCE) reste actif."
        )
    elif decision.get("verdict") == "RETRAIT":
        lines.append(
            "**Verdict : RETRAIT T25** — pivot insuffisant, repli sur canal manuel."
        )
        lines.append("")
        lines.append(decision.get("reason", ""))
        lines.append("")
        lines.append(
            "Action : activer le switch flag `_T2T3T23_GRID_AVAILABLE = False` "
            "dans `src/services/prompt_generator.py` (1 ligne) puis reporter T19+ "
            "sur canal manuel (cf. brief §13)."
        )
    else:
        lines.append("*(aucun verdict — état indéterminé)*")
    lines.append("")

    # Points d'attention
    lines.append("## Points d'attention")
    lines.append("")
    notes: list[str] = []
    if status == "EN_ATTENTE":
        notes.append(
            f"N_annoté actuel = {n_annotated}, manquant = {max(0, N_MIN_ANNOTATED - n_annotated)} "
            f"pour atteindre le seuil minimal {N_MIN_ANNOTATED} (brief §134)."
        )
    if annotations_status not in {"OK", "OK_FLAT"}:
        notes.append(
            f"Statut annotations = `{annotations_status}` — vérifier le fichier "
            f"`{annotations_path}`."
        )
    if not index_subjects:
        notes.append(
            "`index-bench-T25.json` absent à l'heure du verdict — la liste des 20 "
            "leaves testées n'est pas reportée."
        )
    if not notes:
        notes.append("RAS.")
    for n in notes:
        lines.append(f"- {n}")
    lines.append("")

    return "\n".join(lines)


# ─── CLI ────────────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verdict bench garde-fou T25 — brief 2026-05-10"
    )
    parser.add_argument(
        "--annotations",
        type=Path,
        default=DEFAULT_ANNOTATIONS,
        help=f"Chemin annotations.json (def : {DEFAULT_ANNOTATIONS})",
    )
    parser.add_argument(
        "--index",
        type=Path,
        default=DEFAULT_INDEX,
        help=f"Chemin index-bench-T25.json (def : {DEFAULT_INDEX})",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=DEFAULT_REPORT,
        help=f"Chemin du rapport markdown à écrire (def : {DEFAULT_REPORT})",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="N'affiche pas le résumé sur stdout.",
    )
    args = parser.parse_args(argv)

    payload = load_annotations(args.annotations)
    annotations = payload.get("annotations") or {}
    annotations_status = payload.get("_status", "UNKNOWN")

    index_subjects = load_index(args.index)

    stats = compute_stats(annotations)
    decision = decide_verdict(stats)

    report_md = render_report(
        stats=stats,
        decision=decision,
        index_subjects=index_subjects,
        annotations_status=annotations_status,
        annotations_path=args.annotations,
    )

    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(report_md, encoding="utf-8")

    if not args.quiet:
        print(f"[verdict-T25] annotations={args.annotations} status={annotations_status}")
        print(
            f"[verdict-T25] N_annoté={stats['n_annotated']} "
            f"n_pas_coherente={stats['n_pas_coherente']} "
            f"n_incomprehensible={stats['n_incomprehensible']}"
        )
        if stats["taux_post"] is not None:
            print(
                f"[verdict-T25] taux_post={stats['taux_post']:.4f} "
                f"(seuil={SEUIL_TAUX:.4f}, baseline={TAUX_BASELINE:.4f})"
            )
        else:
            print("[verdict-T25] taux_post=N/A (pas de scoring exploitable)")
        if decision["status"] == "EN_ATTENTE":
            print(f"[verdict-T25] STATUS=EN_ATTENTE — {decision['reason']}")
        else:
            print(f"[verdict-T25] VERDICT={decision['verdict']} — {decision['reason']}")
        print(f"[verdict-T25] rapport écrit : {args.report}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
