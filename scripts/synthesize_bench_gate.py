"""Synthèse verdicts bench gate ERNIE — script post-annotation (Phase 5).

Brief source : ``docs/architect/briefs/2026-05-10_brief-bench-gate-ernie.md``.

Lit les ``annotations.json`` des 3 sous-dossiers transferts
(``poc-bench-gate-ernie-{T2T3T23|T25|pivot}``), compte les tags défaut par
transfert, applique le seuil garde-fou (30 %) et écrit le tableau verdict
dans ``docs/reports/2026-05-10_bench-gate-ernie-verdicts.md``.

Tags comptés (cf. brief §35) :
- ``image_pas_coherente`` + ``image_incomprehensible`` : tags principaux pour
  les 3 transferts garde-fou (T2T3T23, T25, pivot).
- ``image_duplication`` + ``image_anatomie_pb`` : tags additionnels comptés
  pour les transferts non-garde-fou bonus (ISO élargi, ANAT). Restent
  comptés/affichés à titre indicatif sur les transferts principaux.

Verdict (par transfert) :
    taux = (n_pas_coherente + n_incomprehensible) / (2 × N_annoté)
    Go ≤ 30 %   →  promotion prod (transfert maintenu / activé)
    No-Go > 30 % →  retrait T19+ canal manuel

Usage :
    python scripts/synthesize_bench_gate.py
    python scripts/synthesize_bench_gate.py --transferts T2T3T23,T25,pivot
    python scripts/synthesize_bench_gate.py --report custom_report.md

NULL-safe : les annotations sans ``score`` numérique > 0 ne sont pas comptées
comme annotées (cf. CLAUDE.md §NULL-safe).
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPORTS_DIR = PROJECT_ROOT / "docs" / "reports"

DEFAULT_REPORT = REPORTS_DIR / "2026-05-10_bench-gate-ernie-verdicts.md"
GLOBAL_INDEX = (REPORTS_DIR / "poc-bench-gate-ernie-2026-05-10"
                / "index-bench-gate.json")

# Seuil garde-fou (cf. brief §5 : 30%)
SEUIL_GARDEFOU = 0.30

# Mapping transfert_id → sous-dossier annotable
TRANSFERTS_DIRS = {
    "T2T3T23": "poc-bench-gate-ernie-T2T3T23",
    "T25":     "poc-bench-gate-ernie-T25",
    "pivot":   "poc-bench-gate-ernie-pivot",
    # Bonus
    "T9":      "poc-bench-gate-ernie-T9",
    "ISO":     "poc-bench-gate-ernie-ISO",
    "ANAT":    "poc-bench-gate-ernie-ANAT",
    "METEO":   "poc-bench-gate-ernie-METEO",
}

# Baselines (cf. brief §5 et §35)
BASELINES = {
    "T2T3T23": {"label": "T2T3T23 grille",
                "baseline_pct": 0.95,
                "baseline_note": "91-100 % `image_pas_coherente` + `image_incomprehensible` "
                                 "sur 4 workflow_classes (pré-transfert)"},
    "T25":     {"label": "T25 before/after",
                "baseline_pct": 0.89,
                "baseline_note": "89 % sur 2 workflow_classes Comparatif (pré-transfert)"},
    "pivot":   {"label": "Pivot T25 (frieze + grid)",
                "baseline_pct": None,
                "baseline_note": "Bench obligatoire — pas de baseline figée pré-pivot"},
    "T9":      {"label": "T9 orientation",
                "baseline_pct": None,
                "baseline_note": "Mesure bonus — non garde-fou"},
    "ISO":     {"label": "ISO élargi",
                "baseline_pct": None,
                "baseline_note": "Mesure bonus — non garde-fou"},
    "ANAT":    {"label": "ANAT overrides",
                "baseline_pct": None,
                "baseline_note": "Mesure bonus — non garde-fou"},
    "METEO":   {"label": "METEO scènes",
                "baseline_pct": None,
                "baseline_note": "Mesure bonus — non garde-fou"},
}

# Tags additionnels comptés pour transferts non-garde-fou
TAGS_PRIMARY = ("image_pas_coherente", "image_incomprehensible")
TAGS_SECONDARY = ("image_duplication", "image_anatomie_pb")


# ───────────── Helpers NULL-safe ─────────────
def _safe_int(value: Any, default: int = 0) -> int:
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


# ───────────── Lecture annotations ─────────────
def load_annotations(path: Path) -> tuple[dict[str, Any], str]:
    if not path.exists():
        return {}, "FILE_NOT_FOUND"
    try:
        raw = path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        return {}, f"READ_ERROR ({exc})"
    if not raw:
        return {}, "EMPTY_FILE"
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        return {}, f"JSON_ERROR ({exc})"
    if not isinstance(data, dict):
        return {}, "BAD_SHAPE"
    annotations = data.get("annotations") if "annotations" in data else data
    if not isinstance(annotations, dict):
        return {}, "NO_ANNOTATIONS_KEY"
    return annotations, "OK"


def compute_stats_for_dir(dir_path: Path) -> dict[str, Any]:
    annot_path = dir_path / "annotations.json"
    annotations, status = load_annotations(annot_path)

    n_annotated = 0
    n_pas_coherente = 0
    n_incomprehensible = 0
    n_duplication = 0
    n_anatomie = 0
    rows: list[dict[str, Any]] = []

    for filename, entry in sorted(annotations.items()):
        if not isinstance(entry, dict):
            continue
        score_raw = entry.get("score")
        score = _safe_int(score_raw, default=0)
        is_scored = score_raw is not None and score > 0
        image_tags = _safe_list(entry.get("image_tags"))
        if is_scored:
            n_annotated += 1
            if "image_pas_coherente" in image_tags:
                n_pas_coherente += 1
            if "image_incomprehensible" in image_tags:
                n_incomprehensible += 1
            if "image_duplication" in image_tags:
                n_duplication += 1
            if "image_anatomie_pb" in image_tags:
                n_anatomie += 1
        rows.append({
            "filename": filename,
            "score": score if is_scored else None,
            "image_tags": image_tags,
            "is_scored": is_scored,
        })

    if n_annotated > 0:
        taux_primary = (n_pas_coherente + n_incomprehensible) / (2 * n_annotated)
        taux_duplication = n_duplication / n_annotated
        taux_anatomie = n_anatomie / n_annotated
    else:
        taux_primary = None
        taux_duplication = None
        taux_anatomie = None

    return {
        "annotations_status": status,
        "annotations_path": str(annot_path),
        "n_annotated": n_annotated,
        "n_pas_coherente": n_pas_coherente,
        "n_incomprehensible": n_incomprehensible,
        "n_duplication": n_duplication,
        "n_anatomie_pb": n_anatomie,
        "taux_primary": taux_primary,
        "taux_duplication": taux_duplication,
        "taux_anatomie": taux_anatomie,
        "rows": rows,
    }


# ───────────── Verdict ─────────────
def decide_verdict(transfert_id: str, stats: dict[str, Any]) -> dict[str, Any]:
    n_annotated = _safe_int(stats.get("n_annotated"), default=0)
    taux = stats.get("taux_primary")
    baseline_pct = BASELINES.get(transfert_id, {}).get("baseline_pct")

    if n_annotated == 0:
        return {"status": "EN_ATTENTE", "verdict": None,
                "reason": "Aucune annotation présente."}
    if taux is None:
        return {"status": "EN_ATTENTE", "verdict": None,
                "reason": "taux_primary non calculable (N_annoté = 0)."}

    is_gardefou = transfert_id in {"T2T3T23", "T25", "pivot"}
    if not is_gardefou:
        # Transferts non-garde-fou : pas de Go/No-Go formel — on rapporte juste
        # les taux pour aider à prioriser un suivi.
        return {"status": "INFO", "verdict": "INFO",
                "reason": (f"Mesure bonus (non garde-fou). "
                           f"taux_primary = {taux:.2%}, "
                           f"duplication = {stats.get('taux_duplication') or 0:.2%}, "
                           f"anatomie = {stats.get('taux_anatomie') or 0:.2%}")}

    if taux <= SEUIL_GARDEFOU:
        return {"status": "DECIDED", "verdict": "Go",
                "reason": (f"taux_primary = {taux:.2%} ≤ seuil {SEUIL_GARDEFOU:.0%} "
                           f"(baseline {baseline_pct:.0%} si pré-transfert)")}
    else:
        return {"status": "DECIDED", "verdict": "No-Go",
                "reason": (f"taux_primary = {taux:.2%} > seuil {SEUIL_GARDEFOU:.0%} "
                           f"→ report T19+ canal manuel")}


# ───────────── Rendu Markdown ─────────────
def _fmt_pct(v: float | None) -> str:
    if v is None:
        return "N/A"
    return f"{v * 100:.2f} %"


def render_report(per_transfert: dict[str, dict], selected: list[str]) -> str:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    lines: list[str] = []
    lines.append("# Bench gate ERNIE — Verdicts par transfert")
    lines.append(f"Date : {today}")
    lines.append("")
    lines.append("## Contexte")
    lines.append("")
    lines.append(
        "Verdicts garde-fou ERNIE pour les 3 transferts à risque pivot "
        "(T2T3T23 grille, T25 before/after, Pivot T25 frieze+grid). "
        "Calculs depuis les annotations humaines, "
        f"seuil garde-fou : **{SEUIL_GARDEFOU:.0%}**."
    )
    lines.append("")
    lines.append("Brief source : `docs/architect/briefs/2026-05-10_brief-bench-gate-ernie.md`.")
    lines.append("")

    # Tableau verdicts (résumé) ────────────────────
    lines.append("## Résumé verdicts")
    lines.append("")
    lines.append("| Transfert | N annoté | `image_pas_coherente` | `image_incomprehensible` | "
                 "Taux principal | Baseline pré | Verdict |")
    lines.append("|---|---|---|---|---|---|---|")
    for tid in selected:
        block = per_transfert.get(tid) or {}
        stats = block.get("stats") or {}
        decision = block.get("decision") or {}
        baseline_pct = BASELINES.get(tid, {}).get("baseline_pct")
        baseline_str = f"{baseline_pct:.0%}" if baseline_pct is not None else "—"
        verdict = decision.get("verdict") or "EN_ATTENTE"
        lines.append(
            f"| **{tid}** | {stats.get('n_annotated', 0)} "
            f"| {stats.get('n_pas_coherente', 0)} "
            f"| {stats.get('n_incomprehensible', 0)} "
            f"| {_fmt_pct(stats.get('taux_primary'))} "
            f"| {baseline_str} "
            f"| **{verdict}** |"
        )
    lines.append("")

    # Détail par transfert ────────────────────
    for tid in selected:
        block = per_transfert.get(tid) or {}
        stats = block.get("stats") or {}
        decision = block.get("decision") or {}
        meta = BASELINES.get(tid, {})
        lines.append(f"## {tid} — {meta.get('label', tid)}")
        lines.append("")
        lines.append(f"- Sous-dossier : `docs/reports/{TRANSFERTS_DIRS.get(tid, '?')}/`")
        lines.append(f"- Statut annotations : `{stats.get('annotations_status', '?')}`")
        lines.append(f"- Baseline pré-transfert : {meta.get('baseline_note', '—')}")
        lines.append("")
        lines.append("| Métrique | Valeur |")
        lines.append("|---|---|")
        lines.append(f"| N images annotées | {stats.get('n_annotated', 0)} |")
        lines.append(f"| `image_pas_coherente` | {stats.get('n_pas_coherente', 0)} |")
        lines.append(f"| `image_incomprehensible` | {stats.get('n_incomprehensible', 0)} |")
        lines.append(f"| `image_duplication` | {stats.get('n_duplication', 0)} |")
        lines.append(f"| `image_anatomie_pb` | {stats.get('n_anatomie_pb', 0)} |")
        lines.append(f"| Taux principal (pc+inc)/(2N) | {_fmt_pct(stats.get('taux_primary'))} |")
        lines.append(f"| Taux duplication | {_fmt_pct(stats.get('taux_duplication'))} |")
        lines.append(f"| Taux anatomie | {_fmt_pct(stats.get('taux_anatomie'))} |")
        lines.append("")
        lines.append(f"**Verdict** : {decision.get('verdict', 'EN_ATTENTE')}")
        lines.append("")
        lines.append(f"_{decision.get('reason', '—')}_")
        lines.append("")

        rows = [r for r in (stats.get("rows") or []) if r.get("is_scored")]
        if rows:
            lines.append("Détail annotations :")
            lines.append("")
            lines.append("| Filename | Score | Tags |")
            lines.append("|---|---|---|")
            for r in rows:
                tags = r.get("image_tags") or []
                tags_str = ", ".join(f"`{t}`" for t in tags) if tags else "—"
                lines.append(f"| `{r.get('filename')}` | {r.get('score')} | {tags_str} |")
            lines.append("")

    # Décision finale (action archi) ────────────────────
    lines.append("## Décision / Action suivante")
    lines.append("")
    decisions_taken = [
        (tid, per_transfert[tid]["decision"]["verdict"])
        for tid in selected
        if per_transfert.get(tid, {}).get("decision", {}).get("status") == "DECIDED"
    ]
    en_attente = [
        tid for tid in selected
        if per_transfert.get(tid, {}).get("decision", {}).get("status") == "EN_ATTENTE"
    ]
    if en_attente:
        lines.append(f"- **EN ATTENTE D'ANNOTATION** : {', '.join(en_attente)}")
    if decisions_taken:
        lines.append("- Verdicts émis :")
        for tid, v in decisions_taken:
            lines.append(f"  - `{tid}` → **{v}**")
    if not en_attente and not decisions_taken:
        lines.append("- Aucun transfert exploitable (toutes annotations vides ou bonus seul).")
    lines.append("")
    lines.append("Pour les No-Go : activer le report sur canal manuel (T19+) selon le "
                 "transfert concerné. Cf. brief §13 et MEMORY.md cycle 2026-05-10.")
    lines.append("")

    return "\n".join(lines)


# ───────────── CLI ─────────────
def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument(
        "--transferts", default="T2T3T23,T25,pivot",
        help=("Liste de transferts à synthétiser, séparée par virgules. "
              f"Choix : {','.join(TRANSFERTS_DIRS.keys())}. "
              "Défaut : T2T3T23,T25,pivot."),
    )
    parser.add_argument(
        "--report", type=Path, default=DEFAULT_REPORT,
        help=f"Chemin du rapport markdown à écrire (def : {DEFAULT_REPORT}).",
    )
    parser.add_argument(
        "--quiet", action="store_true",
        help="N'affiche pas le résumé sur stdout.",
    )
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    selected = [t.strip() for t in args.transferts.split(",") if t.strip()]
    unknown = [t for t in selected if t not in TRANSFERTS_DIRS]
    if unknown:
        print(f"Transferts inconnus : {unknown}", file=sys.stderr)
        return 2

    per_transfert: dict[str, dict] = {}
    for tid in selected:
        dir_name = TRANSFERTS_DIRS[tid]
        dir_path = REPORTS_DIR / dir_name
        if not dir_path.is_dir():
            stats = {
                "annotations_status": "DIR_NOT_FOUND",
                "annotations_path": str(dir_path / "annotations.json"),
                "n_annotated": 0, "n_pas_coherente": 0,
                "n_incomprehensible": 0, "n_duplication": 0,
                "n_anatomie_pb": 0, "taux_primary": None,
                "taux_duplication": None, "taux_anatomie": None,
                "rows": [],
            }
        else:
            stats = compute_stats_for_dir(dir_path)
        decision = decide_verdict(tid, stats)
        per_transfert[tid] = {"stats": stats, "decision": decision}

    report_md = render_report(per_transfert, selected)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(report_md, encoding="utf-8")

    if not args.quiet:
        try:
            rel = args.report.relative_to(PROJECT_ROOT)
        except ValueError:
            rel = args.report
        print(f"[bench-gate] Rapport écrit : {rel}")
        for tid in selected:
            block = per_transfert[tid]
            stats = block["stats"]
            decision = block["decision"]
            taux_str = "N/A" if stats["taux_primary"] is None else f"{stats['taux_primary']:.2%}"
            print(f"  {tid:10} N={stats['n_annotated']:3}  taux={taux_str:>7}  "
                  f"verdict={decision.get('verdict') or 'EN_ATTENTE'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
