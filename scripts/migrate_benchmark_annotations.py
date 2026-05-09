"""Migration des ``annotations.json`` v1 → v2 (grille structurée).

Usage::

    python scripts/migrate_benchmark_annotations.py            # dry-run sur tous
    python scripts/migrate_benchmark_annotations.py --apply    # écrit
    python scripts/migrate_benchmark_annotations.py --dir poc-sampler-benchmark
    python scripts/migrate_benchmark_annotations.py --apply --dir poc-scale-benchmark

Comportement :
- ``--dry-run`` (défaut) : aucune écriture, juste un diff résumé en stdout +
  rapport ``docs/reports/2026-05-09_migration-annotateur-grille-v2.md``.
- ``--apply`` : backup ``.bak`` puis réécriture en v2.
- ``--dir`` : ne traite qu'un seul sous-dossier.

Storage path : ``docs/reports/<dir>/annotations.json`` (cf. ``benchmark.py``).
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPORTS_DIR = PROJECT_ROOT / "docs" / "reports"
REPORT_PATH = REPORTS_DIR / "2026-05-09_migration-annotateur-grille-v2.md"

# ── Mappings v1 → v2 (synchros avec data/benchmark-annotator.html) ─────────
V1_DEFECTS_TO_V2_IMAGE: dict[str, str] = {
    "3_jambes":              "image_anatomie_pb",
    "2_objets":              "image_duplication",
    "couleurs_résiduelles":  "image_traces_couleur",
    "traits_flous":          "image_flou",
    "traits_doubles":        "image_traits_pb",
    "traits_discontinus":    "image_traits_pb",
    "perspective_KO":        "image_physique_pb",
    "gris_résiduel":         "image_gris_residuel",
    "prompt_incohérent":     "image_prompt_non_respecte",
}

# Notes v1 (JSON pills) → axe + clé v2
V1_NOTES_TO_V2: dict[str, tuple[str, str]] = {
    "prompt_trop_vague":         ("prompt", "prompt_ambigu"),
    "prompt_trop_complexe":      ("prompt", "prompt_complexe"),
    "sujet_hors_catégorie":      ("image",  "image_hors_sujet"),
    "sujet_tronqué":             ("image",  "image_compo_mauvaise"),
    "composition_déséquilibrée": ("image",  "image_compo_mauvaise"),
    "trop_chargé":               ("image",  "image_complexe"),
    "couleurs_persistantes":     ("image",  "image_traces_couleur"),
    "traits_incomplets":         ("image",  "image_traits_pb"),
    "concept_difficile":         ("prompt", "prompt_complexe"),
}

V1_SCORE_TO_V2: dict[int, int] = {
    1: 1, 2: 1, 3: 2, 4: 2, 5: 3, 6: 4, 7: 4, 8: 5, 9: 5, 10: 6,
}


def is_v2(entry: dict) -> bool:
    """Détecte un payload déjà v2 (par présence d'au moins un champ v2)."""
    return any(k in entry for k in ("image_tags", "prompt_tags", "flags", "score_legacy", "custom_tags"))


def migrate_entry(raw: dict) -> tuple[dict, list[str]]:
    """Convertit une annotation v1 en v2.

    Retourne ``(new_entry, anomalies)``. Si ``raw`` est déjà v2, le retourne
    tel quel (idempotent) et ``anomalies = []``.
    """
    anomalies: list[str] = []
    if not isinstance(raw, dict):
        anomalies.append(f"entry not dict: {type(raw).__name__}")
        return _empty_v2_entry(), anomalies

    if is_v2(raw):
        # Idempotence : on retourne tel quel mais on s'assure que la structure
        # est complète (pour repérer les artefacts de migration partielle).
        out = _empty_v2_entry()
        out["score"] = raw.get("score") if isinstance(raw.get("score"), int) else None
        out["score_legacy"] = raw.get("score_legacy") if isinstance(raw.get("score_legacy"), int) else None
        out["image_tags"] = list(raw.get("image_tags") or [])
        out["prompt_tags"] = list(raw.get("prompt_tags") or [])
        out["custom_tags"] = list(raw.get("custom_tags") or [])
        flags = raw.get("flags") or {}
        out["flags"] = {
            "pattern": bool(flags.get("pattern", False)),
            "pattern_note": str(flags.get("pattern_note") or ""),
            "sample": bool(flags.get("sample", False)),
            "publishable": flags.get("publishable") if isinstance(flags.get("publishable"), bool) else None,
        }
        out["updated_at"] = raw.get("updated_at") or datetime.now(timezone.utc).isoformat()
        return out, anomalies

    # ── v1 → v2 ─────────────────────────────────────────────────────────
    new_entry = _empty_v2_entry()

    # score
    old_score = raw.get("score")
    if isinstance(old_score, int):
        if 1 <= old_score <= 10:
            new_entry["score"] = V1_SCORE_TO_V2[old_score]
            new_entry["score_legacy"] = old_score
        else:
            anomalies.append(f"score out of [1,10]: {old_score}")
    elif old_score is not None:
        anomalies.append(f"score wrong type: {old_score!r}")

    # defects → image_tags
    image_tags: list[str] = []
    seen_img: set[str] = set()
    defects = raw.get("defects") or []
    if isinstance(defects, list):
        for d in defects:
            if not isinstance(d, str):
                anomalies.append(f"defect not str: {d!r}")
                continue
            mapped = V1_DEFECTS_TO_V2_IMAGE.get(d)
            if mapped:
                if mapped not in seen_img:
                    seen_img.add(mapped)
                    image_tags.append(mapped)
            else:
                anomalies.append(f"unknown defect: {d}")
    elif defects:
        anomalies.append(f"defects wrong type: {type(defects).__name__}")

    # notes → image_tags / prompt_tags / custom_tags
    prompt_tags: list[str] = []
    custom_tags: list[str] = []
    seen_prom: set[str] = set()
    seen_cust: set[str] = set()
    notes_raw = raw.get("notes")
    if isinstance(notes_raw, str) and notes_raw.strip():
        s = notes_raw.strip()
        parsed: Any = None
        if s.startswith("["):
            try:
                parsed = json.loads(s)
            except Exception:
                parsed = None
        if isinstance(parsed, list):
            for k in parsed:
                if not isinstance(k, str) or not k:
                    anomalies.append(f"note tag wrong: {k!r}")
                    continue
                m = V1_NOTES_TO_V2.get(k)
                if m is None:
                    if k not in seen_cust:
                        seen_cust.add(k)
                        custom_tags.append(k)
                else:
                    axis, key = m
                    if axis == "image":
                        if key not in seen_img:
                            seen_img.add(key)
                            image_tags.append(key)
                    else:
                        if key not in seen_prom:
                            seen_prom.add(key)
                            prompt_tags.append(key)
        else:
            # Texte libre → custom unique
            if s not in seen_cust:
                seen_cust.add(s)
                custom_tags.append(s)

    new_entry["image_tags"] = image_tags
    new_entry["prompt_tags"] = prompt_tags
    new_entry["custom_tags"] = custom_tags

    # publishable → flags.publishable
    pub = raw.get("publishable")
    if pub is True or pub is False:
        new_entry["flags"]["publishable"] = pub

    # updated_at conservé
    if raw.get("updated_at"):
        new_entry["updated_at"] = raw["updated_at"]
    else:
        new_entry["updated_at"] = datetime.now(timezone.utc).isoformat()

    return new_entry, anomalies


def _empty_v2_entry() -> dict:
    return {
        "score": None,
        "score_legacy": None,
        "image_tags": [],
        "prompt_tags": [],
        "custom_tags": [],
        "flags": {
            "pattern": False,
            "pattern_note": "",
            "sample": False,
            "publishable": None,
        },
        "updated_at": None,
    }


def process_file(path: Path, apply: bool) -> dict:
    """Traite un seul ``annotations.json``. Retourne un résumé exploitable.

    Le résumé contient ``file``, ``total``, ``already_v2``, ``migrated``,
    ``anomalies`` (liste de tuples ``(filename, msg)``), ``written`` (bool).
    """
    summary = {
        "file": str(path.relative_to(PROJECT_ROOT)),
        "total": 0,
        "already_v2": 0,
        "migrated": 0,
        "anomalies": [],
        "written": False,
    }
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        summary["anomalies"].append(("__file__", f"unreadable: {exc}"))
        return summary
    if not isinstance(data, dict):
        summary["anomalies"].append(("__file__", "top-level not dict"))
        return summary

    annotations = data.get("annotations") or {}
    if not isinstance(annotations, dict):
        summary["anomalies"].append(("__file__", "annotations key not dict"))
        return summary

    new_annotations: dict[str, dict] = {}
    for fname, entry in annotations.items():
        summary["total"] += 1
        if isinstance(entry, dict) and is_v2(entry):
            summary["already_v2"] += 1
            new_entry, anomalies = migrate_entry(entry)  # idempotent reformat
        else:
            new_entry, anomalies = migrate_entry(entry if isinstance(entry, dict) else {})
            summary["migrated"] += 1
        for msg in anomalies:
            summary["anomalies"].append((fname, msg))
        new_annotations[fname] = new_entry

    if apply:
        # Backup
        bak = path.with_suffix(path.suffix + ".bak")
        shutil.copy2(path, bak)
        out = dict(data)
        out["annotations"] = new_annotations
        out["schema_version"] = "v2"
        path.write_text(
            json.dumps(out, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        summary["written"] = True

    return summary


def find_annotation_files(target_dir: str | None) -> list[Path]:
    if not REPORTS_DIR.is_dir():
        return []
    if target_dir:
        sub = REPORTS_DIR / target_dir
        if not sub.is_dir():
            print(f"[err] dir not found: {sub}", file=sys.stderr)
            return []
        ap = sub / "annotations.json"
        return [ap] if ap.is_file() else []
    out: list[Path] = []
    for sub in sorted(REPORTS_DIR.iterdir()):
        if not sub.is_dir():
            continue
        ap = sub / "annotations.json"
        if ap.is_file():
            out.append(ap)
    return out


def write_report(summaries: list[dict], apply: bool, target_dir: str | None) -> None:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    total_files = len(summaries)
    total_entries = sum(s["total"] for s in summaries)
    total_already = sum(s["already_v2"] for s in summaries)
    total_migrated = sum(s["migrated"] for s in summaries)
    total_anomalies = sum(len(s["anomalies"]) for s in summaries)
    mode = "APPLY (écriture)" if apply else "DRY-RUN (lecture seule)"

    lines: list[str] = []
    lines.append("# Migration — Annotateur grille v2")
    lines.append(f"Date : 2026-05-09")
    lines.append("")
    lines.append("## Contexte")
    lines.append(
        "Migration des ``annotations.json`` v1 (defects/notes/score 1-10) "
        "vers le schéma v2 (image_tags / prompt_tags / custom_tags / flags / score 1-6). "
        "Cf. brief `2026-05-09_brief-annotateur-v2.md`."
    )
    lines.append("")
    lines.append("## Résultats")
    lines.append("")
    lines.append(f"- Mode : **{mode}**")
    if target_dir:
        lines.append(f"- Cible : un seul dir ``{target_dir}``")
    lines.append(f"- Fichiers traités : **{total_files}**")
    lines.append(f"- Annotations totales : **{total_entries}**")
    lines.append(f"- Déjà en v2 (idempotent) : {total_already}")
    lines.append(f"- Migrées v1 → v2 : **{total_migrated}**")
    lines.append(f"- Anomalies relevées : {total_anomalies}")
    lines.append("")
    lines.append("### Détail par fichier")
    lines.append("")
    lines.append("| Fichier | Total | v2 | Migrées | Anomalies | Écrit |")
    lines.append("|---|---:|---:|---:|---:|:---:|")
    for s in summaries:
        lines.append(
            f"| `{s['file']}` | {s['total']} | {s['already_v2']} | "
            f"{s['migrated']} | {len(s['anomalies'])} | "
            f"{'✅' if s['written'] else '—'} |"
        )
    lines.append("")
    if total_anomalies:
        lines.append("### Anomalies détaillées")
        lines.append("")
        for s in summaries:
            if not s["anomalies"]:
                continue
            lines.append(f"#### `{s['file']}`")
            lines.append("")
            for fname, msg in s["anomalies"]:
                lines.append(f"- `{fname}` — {msg}")
            lines.append("")
    lines.append("## Points d'attention")
    lines.append("")
    if not apply:
        lines.append("- **Mode dry-run** : aucun fichier n'a été modifié. Relancer "
                     "avec ``--apply`` pour écrire (un ``.bak`` est créé avant).")
    if total_anomalies:
        lines.append("- Anomalies présentes : généralement des tags inconnus dans les "
                     "``defects`` ou ``notes`` — listés ci-dessus pour décision manuelle.")
    else:
        lines.append("- Aucune anomalie détectée — toutes les valeurs v1 sont mappables.")
    lines.append("")
    lines.append("## Décision / Action suivante")
    lines.append("")
    if apply:
        lines.append(f"- Migration appliquée. Vérifier 1 ou 2 fichiers à la main puis supprimer les ``.bak`` quand tout est OK.")
    else:
        lines.append(f"- Vérifier le diff résumé ci-dessus puis lancer ``python scripts/migrate_benchmark_annotations.py --apply`` quand prêt.")
    lines.append("")
    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", default=False,
                        help="(défaut implicite) ne rien écrire — listé pour clarté.")
    parser.add_argument("--apply", action="store_true", default=False,
                        help="Écrit les fichiers (backup .bak avant).")
    parser.add_argument("--dir", default=None,
                        help="Cible un sous-dossier précis (ex. poc-sampler-benchmark).")
    args = parser.parse_args()

    apply = bool(args.apply)
    if args.dry_run and apply:
        print("[err] --dry-run et --apply mutuellement exclusifs", file=sys.stderr)
        return 2

    files = find_annotation_files(args.dir)
    if not files:
        print(f"[info] no annotations.json found under {REPORTS_DIR}")
        return 0

    print(f"[info] {len(files)} fichier(s) à traiter — mode {'APPLY' if apply else 'DRY-RUN'}")
    summaries = []
    for ap in files:
        s = process_file(ap, apply=apply)
        summaries.append(s)
        print(
            f"  {s['file']}: total={s['total']} v2={s['already_v2']} "
            f"migrated={s['migrated']} anomalies={len(s['anomalies'])} "
            f"{'WRITTEN' if s['written'] else 'noop'}"
        )

    write_report(summaries, apply=apply, target_dir=args.dir)
    print(f"[info] rapport écrit : {REPORT_PATH.relative_to(PROJECT_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
