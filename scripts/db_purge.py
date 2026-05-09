"""Purge intégrale de la base PostgreSQL — données uniquement (schéma préservé).

Ordre FK strict (enfants avant parents) :
    image_taxonomy_tag → coverage_stats → site_taxonomy → collection_image
    → export → image_output → job → image → term → vocabulary → taxonomy → site

Conservés intacts : alembic_version (état migrations), job_type_config (config types).

Le script lit l'état BEFORE depuis scripts/_inv_before.json (généré par
_inv_pre_purge.py) si présent, sinon le calcule lui-même. À l'issue, écrit
scripts/_inv_after.json pour exploitation par le rapport.

ATTENTION : opération destructive. Ne lancer qu'après validation du backup.

Usage :
    python scripts/db_purge.py
"""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(PROJECT_ROOT / ".env")

from sqlalchemy import inspect, text  # noqa: E402

from api.db import ENGINE  # noqa: E402

# Ordre de suppression (enfants → parents). Note : term DOIT être supprimé
# AVANT vocabulary (term.vocabulary_id FK), inverse de l'ordre suggéré dans le
# brief utilisateur.
PURGE_ORDER = [
    "image_taxonomy_tag",
    "coverage_stats",
    "site_taxonomy",
    "collection_image",
    "export",
    "image_output",
    "job",
    "image",
    "term",
    "vocabulary",
    "taxonomy",
    "site",
]

# Tables à NE PAS toucher
PRESERVE = {"alembic_version", "job_type_config"}


def count_all_tables() -> dict[str, int]:
    insp = inspect(ENGINE)
    counts = {}
    with ENGINE.connect() as conn:
        for t in sorted(insp.get_table_names()):
            try:
                r = conn.execute(text(f'SELECT COUNT(*) FROM "{t}"')).scalar()
                counts[t] = int(r) if r is not None else 0
            except Exception as exc:
                counts[t] = f"ERROR: {exc}"
    return counts


def main() -> int:
    print("=" * 80)
    print("PURGE INTÉGRALE — données seulement, schéma préservé")
    print("=" * 80)

    # Charger l'état BEFORE (depuis script précédent ou recalculer)
    before_path = PROJECT_ROOT / "scripts" / "_inv_before.json"
    if before_path.exists():
        before = json.loads(before_path.read_text(encoding="utf-8"))
        print(f"\nÉtat BEFORE chargé depuis {before_path.name}")
    else:
        print("\n[BEFORE] Comptage initial…")
        before = count_all_tables()
        before_path.write_text(json.dumps(before, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n[BEFORE] Comptages :")
    for t, c in sorted(before.items()):
        marker = " (PRESERVE)" if t in PRESERVE else ""
        print(f"  {t:<35} {c}{marker}")

    # Vérifier qu'aucune table de PURGE_ORDER n'est inconnue
    insp = inspect(ENGINE)
    existing = set(insp.get_table_names())
    missing = [t for t in PURGE_ORDER if t not in existing]
    if missing:
        print(f"\n⚠ Tables listées mais inexistantes : {missing}")

    # Purge
    print("\n[PURGE] Suppression en ordre FK strict…")
    deleted_per_table: dict[str, int] = {}
    with ENGINE.begin() as conn:
        for t in PURGE_ORDER:
            if t not in existing:
                print(f"  {t:<35} — table inexistante, skip")
                continue
            before_count = conn.execute(text(f'SELECT COUNT(*) FROM "{t}"')).scalar() or 0
            if before_count == 0:
                print(f"  {t:<35} — déjà vide, skip")
                deleted_per_table[t] = 0
                continue
            conn.execute(text(f'DELETE FROM "{t}"'))
            after_count = conn.execute(text(f'SELECT COUNT(*) FROM "{t}"')).scalar() or 0
            deleted = before_count - after_count
            deleted_per_table[t] = deleted
            status = "✓" if after_count == 0 else "⚠"
            print(f"  {status} {t:<33} {before_count} → {after_count} (deleted {deleted})")

    # Inventaire AFTER
    print("\n[AFTER] Recomptage de toutes les tables…")
    after = count_all_tables()
    after_path = PROJECT_ROOT / "scripts" / "_inv_after.json"
    after_path.write_text(json.dumps(after, ensure_ascii=False, indent=2), encoding="utf-8")
    for t, c in sorted(after.items()):
        b = before.get(t, "?")
        marker = " (PRESERVE)" if t in PRESERVE else ""
        flag = "✓" if (t in PRESERVE and c == b) or (t in PURGE_ORDER and c == 0) or (t not in PRESERVE and t not in PURGE_ORDER and c == 0) else "⚠"
        print(f"  {flag} {t:<35} {b} → {c}{marker}")

    # Validation finale
    print("\n[VALIDATION]")
    purge_ok = all(after.get(t, 0) == 0 for t in PURGE_ORDER if t in existing)
    preserve_ok = all(after.get(t) == before.get(t) for t in PRESERVE)
    print(f"  Tables purgées toutes à 0  : {'✓' if purge_ok else '⚠'}")
    print(f"  Tables préservées intactes : {'✓' if preserve_ok else '⚠'}")

    summary = {
        "before": before,
        "after": after,
        "deleted_per_table": deleted_per_table,
        "purge_order_used": PURGE_ORDER,
        "preserved_tables": list(PRESERVE),
        "purge_ok": purge_ok,
        "preserve_ok": preserve_ok,
    }
    out = PROJECT_ROOT / "scripts" / "_purge_summary.json"
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"\nRécap → {out}")
    return 0 if (purge_ok and preserve_ok) else 1


if __name__ == "__main__":
    sys.exit(main())
