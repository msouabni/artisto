"""Migration des annotations fichier (``docs/reports/poc-*/annotations.json``)
vers la table polymorphe ``annotation`` (target_type=``benchmark_file``).

Brief : ``docs/architect/briefs/2026-05-12_brief-mep-v0-C1-migration-annotations-db.md``.

Contexte
--------
Décision archi 2026-05-10 : toutes les annotations doivent être en DB pour la
pipeline MEP v0. Cette migration prépare Brief C3 (export) qui filtrera
``publishable=true`` depuis DB. Les fichiers ``annotations.json`` restent en
place comme legacy (mode benchmark sur disque préservé).

Usage
-----
::

    # Dry-run (défaut explicite — compte uniquement, ne touche pas la DB)
    python scripts/migrate_annotations_to_db.py --dry-run

    # Migration réelle (UPSERT)
    python scripts/migrate_annotations_to_db.py

    # Ciblage par pattern glob (relatif à ``docs/reports``)
    python scripts/migrate_annotations_to_db.py --source 'poc-scale-benchmark'

Comportement
------------
- Parcourt ``docs/reports/<dir>/annotations.json`` (filtre ``--source``
  optionnel : glob simple sur le nom du sous-dossier, défaut ``poc-*``).
- Pour chaque entrée ``annotations[filename]`` :

  * ``target_type``  = ``'benchmark_file'``
  * ``target_id``    = ``f'{dir}/{filename}'``
  * ``score``, ``image_tags``, ``prompt_tags``, ``custom_tags``, ``pattern``,
    ``pattern_note``, ``sample``, ``publishable``, ``updated_at`` recopiés.

- UPSERT cross-dialect : tente UPDATE, si 0 ligne touchée → INSERT.
  Compatible SQLite (tests) et Postgres (prod). Pas d'opérateur JSONB.
- Idempotent : un second run ne crée pas de doublon (UPDATE pur).
- Anomalies (non bloquantes, listées dans le rapport) :

  * tag inconnu (hors ``IMAGE_TAGS_VOCAB`` / ``PROMPT_TAGS_VOCAB``) → warning.
  * score hors plage [1, 6] → warning.
  * entrée non-dict → skip + warning.

- Rapport synthétique imprimé en stdout (à la fin).

Output
------
Stats finales (nb fichiers, entrées totales, INSERT, UPDATE, anomalies) et
détail par dir. Le rapport markdown ``docs/reports/2026-05-12_migration-
annotations-fichier-vers-db.md`` est produit en mode normal (pas en dry-run).
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import sys
from datetime import datetime, timezone

# Console Windows par défaut cp1252 → les caractères Unicode du docstring
# (``→`` etc.) plantent ``--help`` et les ``print``. On force utf-8 si
# possible. Sans effet sur les consoles déjà utf-8 (Linux / Windows Terminal).
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPORTS_DIR = PROJECT_ROOT / "docs" / "reports"
REPORT_PATH = REPORTS_DIR / "2026-05-12_migration-annotations-fichier-vers-db.md"

# Ajout de ``src/`` au path pour import api.* sans dépendre du cwd. Idem
# pratique pour scripts/init_db.py, scripts/seed_data.py, etc.
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from api.annotation_vocab import IMAGE_TAGS_VOCAB, PROMPT_TAGS_VOCAB  # noqa: E402
from api.db import DBConnAdapter, SessionLocal  # noqa: E402

TARGET_TYPE = "benchmark_file"


# ── Helpers ──────────────────────────────────────────────────────────────────


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def find_annotation_files(source_pattern: str | None) -> list[Path]:
    """Liste les ``annotations.json`` candidats.

    ``source_pattern`` : pattern glob simple (``fnmatch``) sur le **nom** du
    sous-dossier (pas du chemin complet). ``None`` ou vide → ``poc-*`` par
    défaut.
    """
    if not REPORTS_DIR.is_dir():
        return []
    pattern = source_pattern or "poc-*"
    out: list[Path] = []
    for sub in sorted(REPORTS_DIR.iterdir()):
        if not sub.is_dir():
            continue
        if not fnmatch.fnmatch(sub.name, pattern):
            continue
        ap = sub / "annotations.json"
        if ap.is_file():
            out.append(ap)
    return out


def parse_entry(
    raw: Any,
    *,
    target_id: str,
) -> tuple[dict | None, list[str]]:
    """Normalise une entrée ``annotations[filename]`` en payload DB.

    Retourne ``(payload, anomalies)``. ``payload`` est ``None`` si l'entrée
    n'est pas exploitable (non-dict). Sinon, c'est un dict prêt pour UPSERT.

    Les anomalies sont consignées **sans bloquer** : valeur conservée telle
    quelle. La validation stricte est côté ``POST /api/annotation`` ; ici on
    migre l'existant, y compris ses imperfections.
    """
    anomalies: list[str] = []
    if not isinstance(raw, dict):
        anomalies.append(f"entry not dict: {type(raw).__name__}")
        return None, anomalies

    # score : Optional[int], plage [1, 6]
    score = raw.get("score")
    if score is not None:
        if not isinstance(score, int) or isinstance(score, bool):
            anomalies.append(f"score wrong type: {score!r}")
            score = None
        elif not (1 <= score <= 6):
            anomalies.append(f"score out of [1,6]: {score}")
            # On garde quand même la valeur (informational).

    # image_tags / prompt_tags / custom_tags : listes de strings
    image_tags = list(raw.get("image_tags") or [])
    prompt_tags = list(raw.get("prompt_tags") or [])
    custom_tags = list(raw.get("custom_tags") or [])

    for t in image_tags:
        if not isinstance(t, str):
            anomalies.append(f"image_tag not str: {t!r}")
        elif t not in IMAGE_TAGS_VOCAB:
            anomalies.append(f"unknown image_tag: {t}")
    for t in prompt_tags:
        if not isinstance(t, str):
            anomalies.append(f"prompt_tag not str: {t!r}")
        elif t not in PROMPT_TAGS_VOCAB:
            anomalies.append(f"unknown prompt_tag: {t}")

    flags = raw.get("flags") or {}
    if not isinstance(flags, dict):
        anomalies.append(f"flags not dict: {type(flags).__name__}")
        flags = {}

    pattern = bool(flags.get("pattern", False))
    pattern_note = str(flags.get("pattern_note") or "")
    if not pattern:
        pattern_note = ""
    sample = bool(flags.get("sample", False))
    publishable_raw = flags.get("publishable")
    publishable = (
        bool(publishable_raw) if publishable_raw is not None else None
    )

    updated_at = raw.get("updated_at") or _now_iso()
    if not isinstance(updated_at, str):
        anomalies.append(f"updated_at not str: {updated_at!r}")
        updated_at = _now_iso()

    payload = {
        "target_type": TARGET_TYPE,
        "target_id": target_id,
        "score": score,
        "image_tags": image_tags,
        "prompt_tags": prompt_tags,
        "custom_tags": custom_tags,
        "pattern": pattern,
        "pattern_note": pattern_note,
        "sample": sample,
        "publishable": publishable,
        "updated_at": updated_at,
    }
    return payload, anomalies


def upsert_annotation(conn: DBConnAdapter, payload: dict) -> str:
    """UPSERT cross-dialect (SQLite / Postgres) sur ``(target_type, target_id)``.

    Retourne ``'INSERT'`` ou ``'UPDATE'``. Pas d'opérateur JSONB Postgres-only :
    on sérialise les listes en JSON texte (la colonne accepte le cast implicite
    côté psycopg pour les colonnes JSONB ; et côté SQLite c'est du TEXT natif).

    Note : on s'aligne sur le pattern utilisé par ``src/api/routes/review.py``
    (``POST /api/annotation``) — SELECT d'existence puis branche INSERT/UPDATE.
    Pas d'``ON CONFLICT`` (Postgres-only) ni d'``INSERT OR REPLACE`` (SQLite-
    only) pour rester portable.
    """
    image_tags_json = json.dumps(payload["image_tags"], ensure_ascii=False)
    prompt_tags_json = json.dumps(payload["prompt_tags"], ensure_ascii=False)
    custom_tags_json = json.dumps(payload["custom_tags"], ensure_ascii=False)
    now = _now_iso()

    existing = conn.execute(
        "SELECT id, created_at FROM annotation"
        " WHERE target_type = ? AND target_id = ?",
        [payload["target_type"], payload["target_id"]],
    ).fetchone()

    if existing is None:
        conn.execute(
            """
            INSERT INTO annotation (
                target_type, target_id, score,
                image_tags, prompt_tags, custom_tags,
                pattern, pattern_note, sample, publishable,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                payload["target_type"], payload["target_id"], payload["score"],
                image_tags_json, prompt_tags_json, custom_tags_json,
                payload["pattern"], payload["pattern_note"],
                payload["sample"], payload["publishable"],
                payload["updated_at"] or now, now,
            ],
        )
        return "INSERT"

    conn.execute(
        """
        UPDATE annotation SET
            score = ?,
            image_tags = ?,
            prompt_tags = ?,
            custom_tags = ?,
            pattern = ?,
            pattern_note = ?,
            sample = ?,
            publishable = ?,
            updated_at = ?
        WHERE target_type = ? AND target_id = ?
        """,
        [
            payload["score"],
            image_tags_json, prompt_tags_json, custom_tags_json,
            payload["pattern"], payload["pattern_note"],
            payload["sample"], payload["publishable"],
            now,
            payload["target_type"], payload["target_id"],
        ],
    )
    return "UPDATE"


def process_file(
    path: Path,
    *,
    conn: DBConnAdapter | None,
    dry_run: bool,
) -> dict:
    """Traite un ``annotations.json``. Retourne un résumé exploitable.

    ``conn`` peut être ``None`` en mode dry-run (mais on conserve la connexion
    pour permettre une vérification de cohérence si besoin futur — pas utilisé
    actuellement). Le résumé est compatible avec ``write_report``.
    """
    dir_name = path.parent.name
    summary = {
        "dir": dir_name,
        "file": str(path.relative_to(PROJECT_ROOT)),
        "total": 0,
        "inserts": 0,
        "updates": 0,
        "skipped": 0,
        "anomalies": [],  # list[tuple[filename, msg]]
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

    for filename, entry in annotations.items():
        summary["total"] += 1
        target_id = f"{dir_name}/{filename}"
        payload, anomalies = parse_entry(entry, target_id=target_id)
        for msg in anomalies:
            summary["anomalies"].append((filename, msg))
        if payload is None:
            summary["skipped"] += 1
            continue

        if dry_run or conn is None:
            # En dry-run on simule : on regarde si la ligne existe déjà pour
            # produire des stats INSERT/UPDATE réalistes (utile pour estimer
            # l'impact du run normal). Si ``conn`` est ``None`` (cas pur
            # offline), on compte tout comme INSERT par défaut.
            if conn is None:
                summary["inserts"] += 1
                continue
            existing = conn.execute(
                "SELECT 1 FROM annotation"
                " WHERE target_type = ? AND target_id = ?",
                [payload["target_type"], payload["target_id"]],
            ).fetchone()
            if existing is None:
                summary["inserts"] += 1
            else:
                summary["updates"] += 1
            continue

        op = upsert_annotation(conn, payload)
        if op == "INSERT":
            summary["inserts"] += 1
        else:
            summary["updates"] += 1

    return summary


def write_report(summaries: list[dict], *, dry_run: bool) -> None:
    """Écrit ``docs/reports/2026-05-12_migration-annotations-fichier-vers-db.md``.

    Suit la convention reporting projet (cf. CLAUDE.md §Reporting).
    """
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    total_files = len(summaries)
    total_entries = sum(s["total"] for s in summaries)
    total_inserts = sum(s["inserts"] for s in summaries)
    total_updates = sum(s["updates"] for s in summaries)
    total_skipped = sum(s["skipped"] for s in summaries)
    total_anomalies = sum(len(s["anomalies"]) for s in summaries)
    mode = "DRY-RUN (lecture seule)" if dry_run else "APPLY (UPSERT en DB)"

    lines: list[str] = []
    lines.append("# Migration annotations fichier → DB polymorphe")
    lines.append("Date : 2026-05-12")
    lines.append("")
    lines.append("## Contexte")
    lines.append("")
    lines.append(
        "Migration de toutes les annotations stockées sur disque "
        "(``docs/reports/poc-*/annotations.json``) vers la table polymorphe "
        "``annotation`` (``target_type='benchmark_file'``, "
        "``target_id='{dir}/{filename}'``). Prépare Brief C3 (export depuis DB)."
    )
    lines.append("")
    lines.append("## Résultats")
    lines.append("")
    lines.append(f"- Mode : **{mode}**")
    lines.append(f"- Fichiers parcourus : **{total_files}**")
    lines.append(f"- Entrées totales : **{total_entries}**")
    lines.append(f"- INSERT (nouveaux) : **{total_inserts}**")
    lines.append(f"- UPDATE (déjà présents) : **{total_updates}**")
    if total_skipped:
        lines.append(f"- Entrées skippées (non-dict) : {total_skipped}")
    lines.append(f"- Anomalies (non bloquantes) : {total_anomalies}")
    lines.append("")
    lines.append("### Détail par dir")
    lines.append("")
    lines.append("| Dir | Total | INSERT | UPDATE | Anomalies |")
    lines.append("|---|---:|---:|---:|---:|")
    for s in summaries:
        lines.append(
            f"| `{s['dir']}` | {s['total']} | {s['inserts']} | "
            f"{s['updates']} | {len(s['anomalies'])} |"
        )
    lines.append("")
    if total_anomalies:
        lines.append("### Anomalies détaillées (extrait, max 20 par dir)")
        lines.append("")
        for s in summaries:
            if not s["anomalies"]:
                continue
            lines.append(f"#### `{s['dir']}` ({len(s['anomalies'])} anomalies)")
            lines.append("")
            for fname, msg in s["anomalies"][:20]:
                lines.append(f"- `{fname}` — {msg}")
            if len(s["anomalies"]) > 20:
                lines.append(f"- … ({len(s['anomalies']) - 20} autres tronquées)")
            lines.append("")
    lines.append("## Points d'attention")
    lines.append("")
    if dry_run:
        lines.append(
            "- **Mode dry-run** : aucune écriture DB. Relancer sans "
            "``--dry-run`` pour appliquer."
        )
    if total_anomalies:
        lines.append(
            "- Anomalies tags inconnus / scores hors plage : conservés tels "
            "quels dans la DB (la validation stricte est côté "
            "``POST /api/annotation``). À nettoyer manuellement si besoin "
            "via un script séparé."
        )
    else:
        lines.append("- Aucune anomalie détectée — toutes les entrées sont conformes.")
    lines.append(
        "- Trois schémas d'index POC supportés en lecture (subjects, "
        "results-by-leaf-id, results-legacy) : sans impact ici car le "
        "fichier ``annotations.json`` est uniforme (dict ``annotations`` "
        "keyed par filename, schéma v2)."
    )
    lines.append(
        "- Les fichiers ``annotations.json`` ne sont pas modifiés (legacy "
        "préservé pour le mode benchmark sur disque)."
    )
    lines.append("")
    lines.append("## Décision / Action suivante")
    lines.append("")
    if dry_run:
        lines.append("- Vérifier les counts puis lancer sans ``--dry-run`` pour appliquer.")
    else:
        lines.append(
            "- Brief C3 (export) peut maintenant filtrer ``publishable=true`` "
            "depuis la table ``annotation`` au lieu de relire les fichiers."
        )
        lines.append(
            "- Un rerun de ce script est idempotent (UPDATE pur, 0 doublon)."
        )
    lines.append("")
    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")


def _print_summary(summaries: list[dict], *, dry_run: bool) -> None:
    total_files = len(summaries)
    total_entries = sum(s["total"] for s in summaries)
    total_inserts = sum(s["inserts"] for s in summaries)
    total_updates = sum(s["updates"] for s in summaries)
    total_skipped = sum(s["skipped"] for s in summaries)
    total_anomalies = sum(len(s["anomalies"]) for s in summaries)
    mode = "DRY-RUN" if dry_run else "APPLY"
    print(f"[{mode}] {total_files} fichiers, {total_entries} entrées, "
          f"{total_inserts} INSERT, {total_updates} UPDATE, "
          f"{total_skipped} skipped, {total_anomalies} anomalies")
    for s in summaries:
        print(
            f"  {s['dir']}: total={s['total']} inserts={s['inserts']} "
            f"updates={s['updates']} skipped={s['skipped']} "
            f"anomalies={len(s['anomalies'])}"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--dry-run", action="store_true", default=False,
        help="Compte uniquement, ne touche pas la DB.",
    )
    parser.add_argument(
        "--source", default=None,
        help=(
            "Pattern glob sur le NOM du sous-dossier de ``docs/reports``"
            " (défaut : ``poc-*``)."
        ),
    )
    args = parser.parse_args(argv)

    files = find_annotation_files(args.source)
    if not files:
        print(
            f"[info] aucun annotations.json trouvé sous {REPORTS_DIR}"
            f" (pattern={args.source or 'poc-*'})"
        )
        return 0

    # On ouvre la session DB même en dry-run pour produire des stats
    # INSERT/UPDATE réalistes (lecture seule sur ``annotation``). Si la DB
    # n'est pas dispo, on bascule en compteur pur sans crash.
    session = None
    conn: DBConnAdapter | None = None
    try:
        session = SessionLocal()
        conn = DBConnAdapter(session)
        # Smoke test de connectivité (en dry-run on tolère l'absence de DB).
        try:
            conn.execute("SELECT 1 FROM annotation WHERE 1 = 0")
        except Exception as exc:
            if args.dry_run:
                print(
                    f"[warn] DB indisponible en dry-run ({exc}) — "
                    f"tous les counts en INSERT par défaut",
                    file=sys.stderr,
                )
                session.close()
                session = None
                conn = None
            else:
                raise

        print(
            f"[info] {len(files)} fichier(s) — mode "
            f"{'DRY-RUN' if args.dry_run else 'APPLY'}"
        )
        summaries: list[dict] = []
        for ap in files:
            s = process_file(ap, conn=conn, dry_run=args.dry_run)
            summaries.append(s)

        if not args.dry_run and session is not None:
            session.commit()
    except Exception:
        if session is not None:
            session.rollback()
        raise
    finally:
        if session is not None:
            session.close()

    _print_summary(summaries, dry_run=args.dry_run)
    write_report(summaries, dry_run=args.dry_run)
    print(f"[info] rapport : {REPORT_PATH.relative_to(PROJECT_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
