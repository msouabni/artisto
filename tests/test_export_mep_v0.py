"""Tests pour ``scripts/export_mep_v0.py``.

Brief : ``docs/architect/briefs/2026-05-10_brief-mep-v0-C-export-data.md``.

Couverture :

1. Filtre HARD caps Zod (gate contractuelle, soft caps tolérés).
2. Filtre `publishable=true` depuis la table `annotation` (post C1).
3. Sélection de la meilleure annotation par leaf (score DESC).
4. Calcul des 3 slugs (r2 + post fr/en/ar) via slug_utils.
5. UPSERT `image` + `image_publication` × 3 par leaf.
6. Transition `mark_image_ready_for_export` (helper Brief A).
7. Écriture des frontmatter Post × 3 locales + manifest.
8. Détection des collisions slug intra-export.
9. Rerun idempotent (UPSERT pur, 0 doublon).
10. `--dry-run` sans aucune écriture.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.insert(0, "src")

from api.db import DBConnAdapter  # noqa: E402
from api.models import Base  # noqa: E402

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import export_mep_v0 as exp  # noqa: E402


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def mem_engine_session():
    """Session SQLite mémoire avec tous les schemas via metadata.create_all()."""
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(bind=engine)
    SL = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    session = SL()
    yield engine, SL, session
    session.close()
    engine.dispose()


@pytest.fixture
def fake_export(tmp_path, monkeypatch, mem_engine_session):
    """Setup complet : DB mémoire patchée, paths d'export sous tmp_path.

    Crée un mini ``_i18n_batch.json`` minimal et des annotations publishable
    en DB. Retourne ``(tmp_path, conn, session)``.
    """
    engine, SL, session = mem_engine_session
    conn = DBConnAdapter(session)

    # Reset le cache module-level (filename → leaf_id) entre tests, sinon
    # un précédent test pollue la résolution.
    exp._LEAFID_FROM_FILENAME_CACHE.clear()

    # 1. Patch des paths d'export du module
    export_dir = tmp_path / "data" / "export"
    images_dir = export_dir / "images"
    posts_dir = export_dir / "posts"
    reports_dir = tmp_path / "docs" / "reports"
    export_dir.mkdir(parents=True)
    reports_dir.mkdir(parents=True)
    i18n_path = export_dir / "_i18n_batch.json"

    monkeypatch.setattr(exp, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(exp, "REPORTS_DIR", reports_dir)
    monkeypatch.setattr(exp, "EXPORT_DIR", export_dir)
    monkeypatch.setattr(exp, "EXPORT_IMAGES_DIR", images_dir)
    monkeypatch.setattr(exp, "EXPORT_POSTS_DIR", posts_dir)
    monkeypatch.setattr(exp, "I18N_BATCH_PATH", i18n_path)
    monkeypatch.setattr(
        exp, "REPORT_PATH", reports_dir / "2026-05-12_phase-mep-v0-C-export-data.md",
    )
    monkeypatch.setattr(exp, "MANIFEST_PATH", export_dir / "manifest.json")

    # 2. Patch SessionLocal pour utiliser la mémoire SQLite
    monkeypatch.setattr(exp, "SessionLocal", SL)

    return {
        "tmp_path": tmp_path,
        "conn": conn,
        "session": session,
        "i18n_path": i18n_path,
        "export_dir": export_dir,
        "images_dir": images_dir,
        "posts_dir": posts_dir,
        "reports_dir": reports_dir,
    }


def _make_leaf(
    leaf_id: str, *,
    name_en: str = "Lion in Savanna",
    name_fr: str = "Lion dans la Savane",
    name_ar: str = "أسد في الغابة",
    title_en: str = "Coloring page of a brave lion roaming the savanna",
    title_fr: str = "Coloriage d'un lion courageux dans la savane africaine",
    title_ar: str = "تلوين أسد شجاع في السافانا",
    description_en: str = "Color this majestic lion under the African sun with acacia trees in the background.",
    description_fr: str = "Colorie ce lion majestueux sous le soleil africain avec des acacias en arrière-plan ici.",
    description_ar: str = "لون هذا الأسد الرائع تحت الشمس الأفريقية مع الأشجار الجميلة في الخلفية.",
    status: str = "ok",
) -> dict:
    return {
        "leaf_id": leaf_id,
        "name_en": name_en, "name_fr": name_fr, "name_ar": name_ar,
        "title_en": title_en, "title_fr": title_fr, "title_ar": title_ar,
        "title_card_en": "Lion", "title_card_fr": "Lion", "title_card_ar": "أسد",
        "description_en": description_en,
        "description_fr": description_fr,
        "description_ar": description_ar,
        "keywords_en": ["lion", "savanna", "wildlife"],
        "keywords_fr": ["lion", "savane", "afrique"],
        "keywords_ar": ["أسد", "سافانا"],
        "status": status,
    }


def _write_i18n_batch(path: Path, leaves: list[dict]) -> None:
    path.write_text(
        json.dumps(
            {"schema_version": "v1", "generated_at": "2026-05-12T00:00:00Z",
             "leaves": leaves},
            ensure_ascii=False, indent=2,
        ),
        encoding="utf-8",
    )


def _insert_publishable(
    conn: DBConnAdapter, target_id: str, score: int = 6,
    updated_at: str = "2026-05-12T10:00:00+00:00",
) -> None:
    conn.execute(
        """
        INSERT INTO annotation (target_type, target_id, score,
            image_tags, prompt_tags, custom_tags,
            pattern, pattern_note, sample, publishable,
            created_at, updated_at)
        VALUES ('benchmark_file', ?, ?, '[]', '[]', '[]',
                FALSE, '', FALSE, TRUE, ?, ?)
        """,
        [target_id, score, updated_at, updated_at],
    )


# ── 1. HARD caps Zod gate ────────────────────────────────────────────────────


def test_hard_caps_blocks_too_long_description(fake_export):
    """Un leaf avec description > 200 chars est bloqué (HARD cap fail)."""
    leaf = _make_leaf("lion_savanna",
        description_en="x" * 220,  # 220 > 200 → HARD cap fail
    )
    _write_i18n_batch(fake_export["i18n_path"], [leaf])
    _insert_publishable(fake_export["conn"], "poc-demo/lion_savanna_1024.png")
    fake_export["session"].commit()

    summary = exp.export_run(dry_run=False, limit=None)
    assert summary["leaves_exported"] == 0
    assert summary["leaves_fail_hard_caps"] == 1
    assert summary["hard_cap_violations"][0][0] == "lion_savanna"


def test_hard_caps_accepts_soft_caps_violated_status(fake_export):
    """Un leaf `status='soft_caps_violated'` mais respectant HARD caps passe.

    C'est l'invariant clé : soft caps = warning interne, pas blocage.
    """
    leaf = _make_leaf("lion_savanna", status="soft_caps_violated")
    _write_i18n_batch(fake_export["i18n_path"], [leaf])
    _insert_publishable(fake_export["conn"], "poc-demo/lion_savanna_1024.png")
    fake_export["session"].commit()

    summary = exp.export_run(dry_run=False, limit=None)
    assert summary["leaves_exported"] == 1
    assert summary["leaves_pass_hard_caps"] == 1


# ── 2. Filtre publishable=true ──────────────────────────────────────────────


def test_leaf_without_publishable_is_skipped(fake_export):
    """Un leaf hard-caps OK mais sans annotation publishable est skippé."""
    leaf = _make_leaf("lion_savanna")
    _write_i18n_batch(fake_export["i18n_path"], [leaf])
    # Pas d'insert dans annotation → leaf doit être skippé.
    fake_export["session"].commit()

    summary = exp.export_run(dry_run=False, limit=None)
    assert summary["leaves_exported"] == 0
    assert summary["leaves_no_publishable"] == 1


# ── 3. Sélection meilleure annotation par leaf ──────────────────────────────


def test_best_annotation_by_score_is_selected(fake_export):
    """Pour un leaf avec plusieurs publishables, on garde le meilleur score."""
    leaf = _make_leaf("lion_savanna")
    _write_i18n_batch(fake_export["i18n_path"], [leaf])
    # 3 annotations publishables du même leaf, scores différents
    _insert_publishable(
        fake_export["conn"], "poc-demo/lion_savanna_v1.png", score=3,
        updated_at="2026-05-12T08:00:00+00:00",
    )
    _insert_publishable(
        fake_export["conn"], "poc-demo/lion_savanna_v2.png", score=6,
        updated_at="2026-05-12T09:00:00+00:00",
    )
    _insert_publishable(
        fake_export["conn"], "poc-demo/lion_savanna_v3.png", score=4,
        updated_at="2026-05-12T10:00:00+00:00",
    )
    fake_export["session"].commit()

    summary = exp.export_run(dry_run=False, limit=None)
    assert summary["leaves_exported"] == 1
    assert summary["exported"][0]["score"] == 6
    # target_id du meilleur (score=6)
    assert summary["exported"][0]["target_id"] == "poc-demo/lion_savanna_v2.png"


# ── 4. Slugs calculés via slug_utils ────────────────────────────────────────


def test_slugs_computed_correctly(fake_export):
    """Les 3 post_slugs + r2_slug sont calculés via slug_utils."""
    leaf = _make_leaf("lion_savanna")
    _write_i18n_batch(fake_export["i18n_path"], [leaf])
    _insert_publishable(fake_export["conn"], "poc-demo/lion_savanna.png")
    fake_export["session"].commit()

    summary = exp.export_run(dry_run=False, limit=None)
    e = summary["exported"][0]
    assert e["r2_slug"] == "lion-in-savanna"
    assert e["post_slugs"]["en"] == "lion-in-savanna"
    assert e["post_slugs"]["fr"] == "lion-dans-la-savane"
    # AR via corpus : "أسد في الغابة" → "asad-fi-al-ghaba"
    assert e["post_slugs"]["ar"] == "asad-fi-al-ghaba"


# ── 5. UPSERT image + image_publication × 3 ─────────────────────────────────


def test_upserts_image_and_3_publications(fake_export):
    """Un export produit 1 ligne `image` + 3 lignes `image_publication`."""
    leaf = _make_leaf("lion_savanna")
    _write_i18n_batch(fake_export["i18n_path"], [leaf])
    _insert_publishable(fake_export["conn"], "poc-demo/lion_savanna.png")
    fake_export["session"].commit()

    exp.export_run(dry_run=False, limit=None)

    n_img = fake_export["conn"].execute(
        "SELECT COUNT(*) FROM image",
    ).fetchone()[0]
    n_pub = fake_export["conn"].execute(
        "SELECT COUNT(*) FROM image_publication",
    ).fetchone()[0]
    assert n_img == 1
    assert n_pub == 3  # fr + en + ar

    # Toutes les locales doivent être présentes.
    locales = sorted(
        r[0] for r in fake_export["conn"].execute(
            "SELECT locale FROM image_publication",
        ).fetchall()
    )
    assert locales == ["ar", "en", "fr"]


# ── 6. mark_image_ready_for_export (transition Brief A) ─────────────────────


def test_ready_for_export_transition_applied(fake_export):
    """Après export, les 3 lignes image_publication sont `ready_for_export`."""
    leaf = _make_leaf("lion_savanna")
    _write_i18n_batch(fake_export["i18n_path"], [leaf])
    _insert_publishable(fake_export["conn"], "poc-demo/lion_savanna.png")
    fake_export["session"].commit()

    exp.export_run(dry_run=False, limit=None)

    statuses = sorted(
        r[0] for r in fake_export["conn"].execute(
            "SELECT status FROM image_publication",
        ).fetchall()
    )
    assert statuses == ["ready_for_export"] * 3


# ── 7. Frontmatter écrits × 3 locales + manifest ────────────────────────────


def test_frontmatter_and_manifest_written(fake_export):
    """3 fichiers JSON Post + 1 manifest.json sont produits."""
    leaf = _make_leaf("lion_savanna")
    _write_i18n_batch(fake_export["i18n_path"], [leaf])
    _insert_publishable(fake_export["conn"], "poc-demo/lion_savanna.png")
    fake_export["session"].commit()

    exp.export_run(dry_run=False, limit=None)

    # Fichiers
    fr_post = fake_export["posts_dir"] / "fr" / "lion-dans-la-savane.json"
    en_post = fake_export["posts_dir"] / "en" / "lion-in-savanna.json"
    ar_post = fake_export["posts_dir"] / "ar" / "asad-fi-al-ghaba.json"
    assert fr_post.is_file()
    assert en_post.is_file()
    assert ar_post.is_file()

    # Contenu FR
    fr = json.loads(fr_post.read_text(encoding="utf-8"))
    assert fr["locale"] == "fr"
    assert fr["slug"] == "lion-dans-la-savane"
    assert fr["r2_slug"] == "lion-in-savanna"
    assert fr["title"]
    assert fr["description"]
    assert fr["imageSource"].endswith("/png/lion-in-savanna.png")
    assert fr["status"] == "approved"

    # AR : pas de latin résiduel dans le slug
    ar = json.loads(ar_post.read_text(encoding="utf-8"))
    assert ar["slug"] == "asad-fi-al-ghaba"
    assert all(ord(c) < 128 for c in ar["slug"])

    # Manifest
    manifest = json.loads(
        (fake_export["export_dir"] / "manifest.json").read_text(encoding="utf-8"),
    )
    assert manifest["total_leaves_exported"] == 1
    assert manifest["leaves"][0]["r2_slug"] == "lion-in-savanna"
    assert manifest["leaves"][0]["post_slugs"]["ar"] == "asad-fi-al-ghaba"


# ── 8. Collision détection ──────────────────────────────────────────────────


def test_r2_slug_collision_blocks_second_leaf(fake_export):
    """Deux leaves avec le même `name_en` produisent une collision r2_slug.

    Le second leaf est skippé (consigné).
    """
    leaf1 = _make_leaf("lion_savanna_v1", name_en="Lion in Savanna")
    leaf2 = _make_leaf(
        "lion_savanna_v2",
        name_en="Lion in Savanna",  # collision
        name_fr="Lion bis",
        name_ar="أسد ثاني",
    )
    _write_i18n_batch(fake_export["i18n_path"], [leaf1, leaf2])
    _insert_publishable(fake_export["conn"], "poc-demo/lion_savanna_v1.png")
    _insert_publishable(fake_export["conn"], "poc-demo/lion_savanna_v2.png")
    fake_export["session"].commit()

    summary = exp.export_run(dry_run=False, limit=None)
    assert summary["leaves_exported"] == 1
    # leaf2 doit être listé comme skippé avec raison collision
    skipped_ids = [s[0] for s in summary["leaves_skipped"]]
    assert "lion_savanna_v2" in skipped_ids
    skipped_reasons = " | ".join(s[1] for s in summary["leaves_skipped"])
    assert "collision" in skipped_reasons


# ── 9. Idempotence (rerun = 0 doublon) ──────────────────────────────────────


def test_rerun_is_idempotent(fake_export):
    """Un second run consécutif produit UPDATE pur (0 doublon DB, 0 fichier dupliqué)."""
    leaf = _make_leaf("lion_savanna")
    _write_i18n_batch(fake_export["i18n_path"], [leaf])
    _insert_publishable(fake_export["conn"], "poc-demo/lion_savanna.png")
    fake_export["session"].commit()

    s1 = exp.export_run(dry_run=False, limit=None)
    s2 = exp.export_run(dry_run=False, limit=None)

    assert s1["image_inserts"] == 1
    assert s2["image_inserts"] == 0
    assert s2["image_updates"] == 1
    assert s2["publication_inserts"] == 0
    assert s2["publication_updates"] == 3

    # Compte final invariant
    n_img = fake_export["conn"].execute(
        "SELECT COUNT(*) FROM image",
    ).fetchone()[0]
    n_pub = fake_export["conn"].execute(
        "SELECT COUNT(*) FROM image_publication",
    ).fetchone()[0]
    assert n_img == 1
    assert n_pub == 3


# ── 10. Dry-run = aucune écriture ───────────────────────────────────────────


def test_dry_run_does_not_write_db_or_disk(fake_export):
    """`--dry-run` n'écrit rien : DB intacte, pas de fichier produit."""
    leaf = _make_leaf("lion_savanna")
    _write_i18n_batch(fake_export["i18n_path"], [leaf])
    _insert_publishable(fake_export["conn"], "poc-demo/lion_savanna.png")
    fake_export["session"].commit()

    summary = exp.export_run(dry_run=True, limit=None)
    # Le comptage logique compte quand même les leaves exportables
    assert summary["leaves_exported"] == 1

    # Mais la DB est intacte (pas d'image ni de publication)
    n_img = fake_export["conn"].execute(
        "SELECT COUNT(*) FROM image",
    ).fetchone()[0]
    n_pub = fake_export["conn"].execute(
        "SELECT COUNT(*) FROM image_publication",
    ).fetchone()[0]
    assert n_img == 0
    assert n_pub == 0

    # Pas de fichiers post écrits
    assert not (fake_export["posts_dir"] / "fr").exists() or not list(
        (fake_export["posts_dir"] / "fr").glob("*.json")
    )
    # Pas de manifest
    assert not (fake_export["export_dir"] / "manifest.json").exists()


# ── 11. Limit ───────────────────────────────────────────────────────────────


def test_limit_caps_exports(fake_export):
    """`--limit N` ne traite que les N premiers leaves (ordre déterministe)."""
    leaves = [
        _make_leaf(f"lion_savanna_v{i}",
                   name_en=f"Lion Variant {chr(65+i)}",  # ascii alpha distinct
                   name_fr=f"Lion Variante {chr(65+i)}",
                   name_ar=f"أسد {i}")
        for i in range(5)
    ]
    _write_i18n_batch(fake_export["i18n_path"], leaves)
    for i in range(5):
        _insert_publishable(
            fake_export["conn"], f"poc-demo/lion_savanna_v{i}.png",
        )
    fake_export["session"].commit()

    summary = exp.export_run(dry_run=False, limit=2)
    assert summary["leaves_exported"] == 2


# ── 12. Helper _hard_caps_ok ────────────────────────────────────────────────


def test_hard_caps_ok_helper_detects_short_title():
    """Helper unitaire : titre 4 chars → fail (min 5)."""
    leaf = _make_leaf("x", title_en="abcd")  # 4 chars
    ok, viol = exp._hard_caps_ok(leaf)
    assert not ok
    assert any("title_en" in v for v in viol)


def test_hard_caps_ok_helper_detects_short_description():
    """Helper unitaire : description 10 chars → fail (min 20)."""
    leaf = _make_leaf("x", description_fr="trop court")  # 10 chars
    ok, viol = exp._hard_caps_ok(leaf)
    assert not ok
    assert any("description_fr" in v for v in viol)


def test_hard_caps_ok_helper_passes_boundary():
    """Helper : 5/20 chars exact → OK (bornes inclusives)."""
    leaf = _make_leaf("x",
        title_en="abcde", title_fr="abcde", title_ar="abcde",
        description_en="x" * 20, description_fr="x" * 20, description_ar="x" * 20,
    )
    ok, viol = exp._hard_caps_ok(leaf)
    assert ok, f"violations: {viol}"
