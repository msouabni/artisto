"""Tests pour ``scripts/migrate_annotations_to_db.py``.

Brief : ``2026-05-12_brief-mep-v0-C1-migration-annotations-db.md``.

Couverture :

1. Entrée nouvelle : INSERT propre dans la table ``annotation``.
2. Entrée déjà présente : UPSERT (UPDATE) sans doublon ni crash.
3. Tag inconnu : anomalie consignée, valeur conservée (non bloquant).
4. Score hors plage [1, 6] : anomalie consignée, valeur conservée.
5. Trois schémas d'index POC supportés en lecture (subjects /
   results-by-leaf-id / results-legacy) : la migration ne lit que
   ``annotations.json`` mais on vérifie qu'elle fonctionne quelles que
   soient les structures voisines (indices) — l'existence de différents
   fichiers d'index dans le dir n'altère pas la migration.
6. Idempotence globale : un second run consécutif produit 0 INSERT, N UPDATE.
7. ``--dry-run`` : aucune écriture DB (compte INSERT/UPDATE estimé).

Les tests utilisent une SQLite en mémoire (cross-dialect — la même logique
UPSERT s'exécutera côté Postgres en prod). Pas d'opérateur JSONB.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# Le conftest pose déjà DATABASE_URL=sqlite:memory et ARTISTE_LOG_TO_FILE=0.
# On s'aligne sur le pattern test_review_routes.py pour l'import path.
sys.path.insert(0, "src")

from api.db import DBConnAdapter  # noqa: E402
from api.models import Base  # noqa: E402

# Import du script comme module — Path = repo/scripts, on ajoute au path.
SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import migrate_annotations_to_db as mig  # noqa: E402


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def mem_session():
    """Session SQLite mémoire isolée avec table ``annotation`` créée."""
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(
        bind=engine, autoflush=False, autocommit=False, future=True,
    )
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture
def mem_conn(mem_session) -> DBConnAdapter:
    return DBConnAdapter(mem_session)


@pytest.fixture
def fake_reports(tmp_path, monkeypatch):
    """Crée un faux ``docs/reports`` isolé sous tmp_path et monkeypatche le
    module pour qu'il pointe dessus. Retourne le Path racine.
    """
    reports = tmp_path / "reports"
    reports.mkdir()
    monkeypatch.setattr(mig, "REPORTS_DIR", reports)
    monkeypatch.setattr(
        mig, "REPORT_PATH", reports / "2026-05-12_migration-test.md",
    )
    # PROJECT_ROOT sert uniquement à calculer .relative_to() → on l'ajuste
    # pour éviter une ValueError dans process_file().
    monkeypatch.setattr(mig, "PROJECT_ROOT", tmp_path)
    return reports


def _write_annotations(
    reports_root: Path, dir_name: str, annotations: dict,
    *, schema_version: str = "v2", extra_files: dict[str, dict] | None = None,
) -> Path:
    """Crée ``<reports>/<dir>/annotations.json`` avec le payload donné.

    ``extra_files`` permet d'ajouter des fichiers d'index voisins pour
    simuler les 3 schémas d'index POC (subjects / results-by-leaf-id /
    results-legacy) — la migration ne doit pas être perturbée.
    """
    sub = reports_root / dir_name
    sub.mkdir(parents=True, exist_ok=True)
    payload = {
        "dir": dir_name,
        "schema_version": schema_version,
        "annotations": annotations,
    }
    (sub / "annotations.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    for name, content in (extra_files or {}).items():
        (sub / name).write_text(
            json.dumps(content, ensure_ascii=False), encoding="utf-8",
        )
    return sub


def _v2_entry(
    *, score: int | None = 5, image_tags=None, prompt_tags=None,
    custom_tags=None, publishable: bool | None = True,
    pattern: bool = False, pattern_note: str = "",
    sample: bool = False, updated_at: str = "2026-05-10T12:00:00+00:00",
) -> dict:
    return {
        "score": score,
        "score_legacy": None,
        "image_tags": image_tags or [],
        "prompt_tags": prompt_tags or [],
        "custom_tags": custom_tags or [],
        "flags": {
            "pattern": pattern,
            "pattern_note": pattern_note,
            "sample": sample,
            "publishable": publishable,
        },
        "updated_at": updated_at,
    }


# ── 1. Entrée nouvelle → INSERT ──────────────────────────────────────────────


def test_insert_new_entry(mem_conn, fake_reports):
    """Une entrée inédite produit un INSERT propre dans ``annotation``."""
    _write_annotations(
        fake_reports, "poc-demo",
        {"lion_1024x1024_euler8s.png": _v2_entry(
            score=6,
            image_tags=["image_coherente"],
            prompt_tags=["prompt_interessant"],
            custom_tags=["beau coloriage"],
            publishable=True,
        )},
    )

    path = fake_reports / "poc-demo" / "annotations.json"
    summary = mig.process_file(path, conn=mem_conn, dry_run=False)

    assert summary["total"] == 1
    assert summary["inserts"] == 1
    assert summary["updates"] == 0
    assert summary["anomalies"] == []

    row = mem_conn.execute(
        "SELECT target_type, target_id, score, image_tags, prompt_tags,"
        " custom_tags, pattern, sample, publishable"
        " FROM annotation WHERE target_id = ?",
        ["poc-demo/lion_1024x1024_euler8s.png"],
    ).fetchone()
    assert row is not None
    assert row[0] == "benchmark_file"
    assert row[1] == "poc-demo/lion_1024x1024_euler8s.png"
    assert row[2] == 6
    # Listes JSON sérialisées en TEXT côté SQLite.
    assert json.loads(row[3]) == ["image_coherente"]
    assert json.loads(row[4]) == ["prompt_interessant"]
    assert json.loads(row[5]) == ["beau coloriage"]
    assert bool(row[6]) is False
    assert bool(row[7]) is False
    assert bool(row[8]) is True


# ── 2. Entrée existante → UPDATE (idempotence) ───────────────────────────────


def test_upsert_existing_entry_no_duplicate(mem_conn, fake_reports):
    """Un second run sur la même entrée produit un UPDATE (pas un doublon)."""
    _write_annotations(
        fake_reports, "poc-demo",
        {"cat.png": _v2_entry(score=4, publishable=False)},
    )
    path = fake_reports / "poc-demo" / "annotations.json"

    s1 = mig.process_file(path, conn=mem_conn, dry_run=False)
    assert s1["inserts"] == 1
    assert s1["updates"] == 0

    # Réécriture du fichier avec un nouveau score → run 2 doit UPDATE.
    _write_annotations(
        fake_reports, "poc-demo",
        {"cat.png": _v2_entry(score=6, publishable=True)},
    )
    s2 = mig.process_file(path, conn=mem_conn, dry_run=False)
    assert s2["inserts"] == 0
    assert s2["updates"] == 1

    # Aucun doublon en table.
    rows = mem_conn.execute(
        "SELECT id, score, publishable FROM annotation"
        " WHERE target_id = ?",
        ["poc-demo/cat.png"],
    ).fetchall()
    assert len(rows) == 1
    assert rows[0][1] == 6
    assert bool(rows[0][2]) is True


# ── 3. Tag inconnu → anomalie (non bloquant) ─────────────────────────────────


def test_unknown_tag_is_anomaly_not_blocking(mem_conn, fake_reports):
    """Un tag hors vocab est consigné en anomalie ; l'entrée passe quand même."""
    _write_annotations(
        fake_reports, "poc-demo",
        {"img.png": _v2_entry(
            score=5,
            image_tags=["image_coherente", "ce_tag_n_existe_pas"],
            prompt_tags=["prompt_inventé"],
        )},
    )
    path = fake_reports / "poc-demo" / "annotations.json"
    summary = mig.process_file(path, conn=mem_conn, dry_run=False)

    assert summary["total"] == 1
    assert summary["inserts"] == 1
    # Au moins 2 anomalies (image + prompt) — exactes inconnues.
    msgs = " | ".join(m for _, m in summary["anomalies"])
    assert "unknown image_tag: ce_tag_n_existe_pas" in msgs
    assert "unknown prompt_tag: prompt_inventé" in msgs

    # La ligne est bien insérée avec les tags d'origine (non bloquant).
    row = mem_conn.execute(
        "SELECT image_tags, prompt_tags FROM annotation WHERE target_id = ?",
        ["poc-demo/img.png"],
    ).fetchone()
    assert "ce_tag_n_existe_pas" in json.loads(row[0])
    assert "prompt_inventé" in json.loads(row[1])


# ── 4. Score hors plage → anomalie ───────────────────────────────────────────


def test_score_out_of_range_is_anomaly(mem_conn, fake_reports):
    """Un ``score`` hors [1, 6] est consigné en anomalie ; l'entrée est insérée."""
    _write_annotations(
        fake_reports, "poc-demo",
        {
            "low.png": _v2_entry(score=0),    # < 1
            "high.png": _v2_entry(score=10),  # > 6
            "ok.png": _v2_entry(score=3),     # OK (témoin)
        },
    )
    path = fake_reports / "poc-demo" / "annotations.json"
    summary = mig.process_file(path, conn=mem_conn, dry_run=False)

    assert summary["total"] == 3
    assert summary["inserts"] == 3
    msgs = sorted(m for _, m in summary["anomalies"])
    assert any("score out of [1,6]: 0" in m for m in msgs)
    assert any("score out of [1,6]: 10" in m for m in msgs)
    # L'entrée ok.png ne déclenche pas d'anomalie.
    assert not any("score out of [1,6]: 3" in m for m in msgs)

    # Toutes les lignes insérées avec leur score d'origine.
    rows = mem_conn.execute(
        "SELECT target_id, score FROM annotation ORDER BY target_id",
    ).fetchall()
    by_id = {r[0]: r[1] for r in rows}
    assert by_id["poc-demo/low.png"] == 0
    assert by_id["poc-demo/high.png"] == 10
    assert by_id["poc-demo/ok.png"] == 3


# ── 5. Trois schémas d'index POC : la migration est robuste ─────────────────


def test_schema_subjects_index_does_not_break_migration(
    mem_conn, fake_reports,
):
    """Schéma 1 : ``subjects-index.json`` (liste de subjects)."""
    _write_annotations(
        fake_reports, "poc-subjects",
        {"sub1.png": _v2_entry(score=5)},
        extra_files={
            "subjects-index.json": {
                "source": "skill",
                "subjects": [
                    {
                        "leaf_id": "leaf1",
                        "filename": "sub1.png",
                        "name_en": "Subject 1",
                    },
                ],
            },
        },
    )
    summary = mig.process_file(
        fake_reports / "poc-subjects" / "annotations.json",
        conn=mem_conn, dry_run=False,
    )
    assert summary["total"] == 1
    assert summary["inserts"] == 1
    assert summary["anomalies"] == []


def test_schema_results_by_leaf_id_does_not_break_migration(
    mem_conn, fake_reports,
):
    """Schéma 2 : ``index-*.json`` avec ``results`` keyed par leaf_id."""
    _write_annotations(
        fake_reports, "poc-by-leaf",
        {"img_leaf.png": _v2_entry(score=4)},
        extra_files={
            "index-by-leaf.json": {
                "results": {
                    "leaf42": {
                        "filename": "img_leaf.png",
                        "leaf_name_en": "Leaf 42",
                        "positive": "...",
                    },
                },
            },
        },
    )
    summary = mig.process_file(
        fake_reports / "poc-by-leaf" / "annotations.json",
        conn=mem_conn, dry_run=False,
    )
    assert summary["total"] == 1
    assert summary["inserts"] == 1
    assert summary["anomalies"] == []


def test_schema_results_legacy_does_not_break_migration(
    mem_conn, fake_reports,
):
    """Schéma 3 : ``<dir>/<dir>.json`` legacy keyed par filename."""
    _write_annotations(
        fake_reports, "poc-legacy",
        {"legacy.png": _v2_entry(score=2)},
        extra_files={
            "poc-legacy.json": {
                "results": {
                    "legacy.png": {
                        "qc": {"luminance_mean": 0.9},
                        "filename": "legacy.png",
                    },
                },
                "schema_version": 1,
            },
        },
    )
    summary = mig.process_file(
        fake_reports / "poc-legacy" / "annotations.json",
        conn=mem_conn, dry_run=False,
    )
    assert summary["total"] == 1
    assert summary["inserts"] == 1
    assert summary["anomalies"] == []


# ── 6. Idempotence globale (rerun = 0 doublon) ───────────────────────────────


def test_full_rerun_is_idempotent(mem_conn, fake_reports):
    """Un second run consécutif produit 0 INSERT et N UPDATE, 0 doublon."""
    _write_annotations(
        fake_reports, "poc-idem",
        {
            "a.png": _v2_entry(score=5),
            "b.png": _v2_entry(score=6),
            "c.png": _v2_entry(score=3),
        },
    )
    path = fake_reports / "poc-idem" / "annotations.json"

    s1 = mig.process_file(path, conn=mem_conn, dry_run=False)
    assert s1["inserts"] == 3
    assert s1["updates"] == 0

    s2 = mig.process_file(path, conn=mem_conn, dry_run=False)
    assert s2["inserts"] == 0
    assert s2["updates"] == 3

    # Comptage final : exactement 3 lignes, pas une de plus.
    total = mem_conn.execute(
        "SELECT COUNT(*) FROM annotation WHERE target_type = ?",
        ["benchmark_file"],
    ).fetchone()
    assert total[0] == 3


# ── 7. Dry-run : aucune écriture DB ─────────────────────────────────────────


def test_dry_run_does_not_write_to_db(mem_conn, fake_reports):
    """En ``--dry-run``, ``process_file`` ne touche pas la table."""
    _write_annotations(
        fake_reports, "poc-dry",
        {"x.png": _v2_entry(score=5)},
    )
    path = fake_reports / "poc-dry" / "annotations.json"
    summary = mig.process_file(path, conn=mem_conn, dry_run=True)

    # Statistique : on a un INSERT estimé (ligne absente côté DB).
    assert summary["total"] == 1
    assert summary["inserts"] == 1
    assert summary["updates"] == 0

    # Mais la DB est intacte.
    n = mem_conn.execute(
        "SELECT COUNT(*) FROM annotation",
    ).fetchone()[0]
    assert n == 0


# ── 8. find_annotation_files : glob + filtrage ───────────────────────────────


def test_find_annotation_files_filters_by_pattern(fake_reports):
    """``--source`` filtre les dirs par fnmatch sur leur **nom**."""
    _write_annotations(fake_reports, "poc-aaa", {"a.png": _v2_entry()})
    _write_annotations(fake_reports, "poc-bbb", {"b.png": _v2_entry()})
    _write_annotations(fake_reports, "other-dir", {"o.png": _v2_entry()})

    # Défaut ``poc-*`` → 2 fichiers (other-dir exclu).
    files = mig.find_annotation_files(None)
    names = sorted(f.parent.name for f in files)
    assert names == ["poc-aaa", "poc-bbb"]

    # Pattern explicite.
    files = mig.find_annotation_files("poc-a*")
    names = sorted(f.parent.name for f in files)
    assert names == ["poc-aaa"]

    # Pattern qui matche tout.
    files = mig.find_annotation_files("*")
    names = sorted(f.parent.name for f in files)
    assert names == ["other-dir", "poc-aaa", "poc-bbb"]


# ── 9. parse_entry : non-dict → skip + anomalie ─────────────────────────────


def test_parse_entry_non_dict_is_skipped():
    """Une entrée non-dict produit ``(None, anomalies)`` (skip)."""
    payload, anomalies = mig.parse_entry("not a dict", target_id="x/y.png")
    assert payload is None
    assert any("entry not dict" in m for m in anomalies)


def test_parse_entry_missing_flags_uses_defaults():
    """Une entrée sans bloc ``flags`` retombe sur les valeurs par défaut."""
    payload, anomalies = mig.parse_entry(
        {"score": 4, "image_tags": [], "prompt_tags": [], "custom_tags": []},
        target_id="x/y.png",
    )
    assert payload is not None
    assert payload["pattern"] is False
    assert payload["sample"] is False
    assert payload["publishable"] is None
