#!/usr/bin/env python3
"""
Peuple les tables liées aux images avec des jeux de données de démonstration.

Prérequis : init_db.py + import_taxonomy_json_to_db.py (taxonomie universal_v0, vocabulaire themes)

Usage:
  python scripts/seed_data.py
  python scripts/seed_data.py --reset   # vide les tables avant d'insérer
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"
DEFAULT_DB = DATA_DIR / "artiste_coloriage.duckdb"

TAXONOMY_ID = "universal_v0"
NOW = lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def seed(db_path: Path, reset: bool = False) -> None:
    _ = db_path
    sys.path.insert(0, str(PROJECT_ROOT / "src"))
    from api.db import get_db_sync, init_db

    init_db()
    conn = get_db_sync(read_only=False)

    # Vérifier que la taxonomie existe
    row = conn.execute(
        "SELECT 1 FROM taxonomy WHERE taxonomy_id = ?", [TAXONOMY_ID]
    ).fetchone()
    if not row:
        print("Erreur: exécutez d'abord init_db.py puis import_taxonomy_json_to_db.py")
        conn.close()
        sys.exit(1)

    # Créer generation_batch si absent (schéma partiel)
    for stmt in [
        """CREATE TABLE IF NOT EXISTS generation_batch (
            id TEXT PRIMARY KEY, name TEXT NOT NULL, scope_type TEXT DEFAULT 'terms',
            prompt_strategy TEXT DEFAULT 'ai_ollama', images_per_term INTEGER DEFAULT 5,
            auto_approve_threshold REAL, status TEXT DEFAULT 'pending',
            created_at TEXT, updated_at TEXT)""",
        """CREATE TABLE IF NOT EXISTS generation_batch_term (
            batch_id TEXT NOT NULL REFERENCES generation_batch(id),
            term_id TEXT NOT NULL, taxonomy_id TEXT NOT NULL REFERENCES taxonomy(taxonomy_id),
            include_subtree INTEGER DEFAULT 0, PRIMARY KEY (batch_id, term_id, taxonomy_id))""",
    ]:
        try:
            conn.execute(stmt)
        except Exception:
            pass

    now = NOW()

    if reset:
        print("Réinitialisation des tables liées aux images…")
        for table in [
            "site_publication", "collection_image", "image_taxonomy_tag",
            "image_output", "collection", "image", "site_taxonomy", "site", "job",
            "generation_batch_term", "generation_batch",
        ]:
            try:
                conn.execute(f"DELETE FROM {table}")
            except Exception:
                pass

    # ── Jobs ───────────────────────────────────────────────────────────────
    # (id, type, status, config, started, finished, err, created, image_id)
    jobs_data = [
        ("job_gen_001", "image_generation", "completed", '{"model":"flux/schnell","steps":20}', now, now, None, now, "img_001"),
        ("job_gen_002", "image_generation", "completed", '{"model":"flux/schnell","steps":20}', now, now, None, now, "img_002"),
        ("job_gen_003", "image_generation", "completed", '{"model":"flux/schnell","steps":25}', now, now, None, now, "img_003"),
        ("job_gen_004", "image_generation", "completed", '{"model":"flux/schnell","steps":20}', now, now, None, now, "img_004"),
        ("job_gen_005", "image_generation", "running", '{"model":"flux/schnell","steps":20}', now, None, None, now, "img_010"),
        ("job_gen_fail", "image_generation", "failed", '{"model":"flux/schnell"}', now, now, "CUDA out of memory", now, "img_005"),
        ("job_gen_007", "image_generation", "completed", '{"model":"flux/schnell","steps":20}', now, now, None, now, "img_007"),
        ("job_export_001", "export", "completed", '{"site_id":"site_fr","collection_id":"col_noel"}', now, now, None, now, None),
        ("job_export_002", "export", "pending", '{"site_id":"site_en","collection_id":"col_mandalas"}', None, None, None, now, None),
        ("job_batch_001", "batch_generation", "completed", '{"batch_id":"batch_001"}', now, now, None, now, None),
    ]
    job_cols = conn.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_name = 'job'"
    ).fetchall()
    has_image_id = any(c[0] == "image_id" for c in job_cols)
    for row in jobs_data:
        jid, jtype, status, config, started, finished, err, created = row[:8]
        image_id = row[8] if len(row) > 8 else None
        if not conn.execute("SELECT 1 FROM job WHERE id = ?", [jid]).fetchone():
            if has_image_id:
                conn.execute(
                    """INSERT INTO job (id, type, status, config, started_at, finished_at, error_message, created_at, image_id)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    [jid, jtype, status, config, started, finished, err, created, image_id],
                )
            else:
                conn.execute(
                    """INSERT INTO job (id, type, status, config, started_at, finished_at, error_message, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    [jid, jtype, status, config, started, finished, err, created],
                )
            print(f"  + job {jid}")

    # Mettre à jour image_id sur les jobs image_generation existants si la colonne existe
    if has_image_id:
        conn.execute("""
            UPDATE job SET image_id = (
                SELECT io.image_id FROM image_output io
                WHERE io.job_id = job.id
                LIMIT 1
            )
            WHERE job.type = 'image_generation' AND job.image_id IS NULL
              AND EXISTS (SELECT 1 FROM image_output io WHERE io.job_id = job.id)
        """)

    # ── Sites ─────────────────────────────────────────────────────────────
    sites_data = [
        ("site_fr", '{"fr":"Coloriage FR","en":"Coloring FR"}', "https://coloriage.example.fr", "fr", "FR", "kids", None, 1),
        ("site_en", '{"fr":"Coloriage EN","en":"Coloring EN"}', "https://coloring.example.com", "en", "US", "kids", None, 1),
        ("site_ar", '{"fr":"Coloriage AR","ar":"تلوين"}', "https://coloriage.example.ma", "ar", "MA", "kids", None, 1),
        ("site_demo", '{"fr":"Site démo","en":"Demo site"}', "https://demo.coloriage.local", "fr", "FR", "kids", None, 1),
    ]
    for sid, name_i18n, base_url, locale, country, audience, config, active in sites_data:
        if not conn.execute("SELECT 1 FROM site WHERE id = ?", [sid]).fetchone():
            conn.execute(
                """INSERT INTO site (id, name_i18n, base_url, default_locale, country, audience, taxonomy_config_path, active, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [sid, name_i18n, base_url, locale, country, audience, config, active, now, now],
            )
            conn.execute(
                """INSERT INTO site_taxonomy (site_id, source_taxonomy_id, created_at)
                   VALUES (?, ?, ?)""",
                [sid, TAXONOMY_ID, now],
            )
            print(f"  + site {sid}")

    # ── Images (concepts) — variété de statuts pour tests ───────────────────
    # (id, title, status, prompt, neg_prompt, origin_type, batch_id, origin_term_id, origin_taxonomy_id, created, updated)
    images_data = [
        ("img_001", "Chat mignon à colorier", "draft", "Un chat assis, style coloriage enfant", "", "manual", None, "animaux_domestiques", TAXONOMY_ID, now, now),
        ("img_002", "Chien joueur", "prompt_ready", "Un chien qui court avec une balle", "", "manual", None, "animaux_domestiques", TAXONOMY_ID, now, now),
        ("img_003", "Mandalas faciles", "generated", "Mandalas simples pour débutants", "", "manual", None, "mandalas_faciles", TAXONOMY_ID, now, now),
        ("img_004", "Voiture de course", "approved", "Voiture de course rouge, vue de face", "", "manual", None, "voitures", TAXONOMY_ID, now, now),
        ("img_005", "Dinosaure T-Rex", "draft", "Tyrannosaurus Rex, style cartoon", "", "manual", None, "dinosaures", TAXONOMY_ID, now, now),
        ("img_006", "Mandalas fleurs", "generated", "Mandalas avec motifs floraux", "", "batch", "batch_001", "mandalas_fleurs", TAXONOMY_ID, now, now),
        ("img_007", "Noël - sapin", "published", "Sapin de Noël décoré", "", "manual", None, "noel", TAXONOMY_ID, now, now),
        ("img_008", "Lettres A et B", "draft", "Coloriage lettres A et B", "", "manual", None, "lettres", TAXONOMY_ID, now, now),
        ("img_009", "Pâques - lapin", "scheduled", "Lapin de Pâques avec œufs", "", "manual", None, "paques", TAXONOMY_ID, now, now),
        ("img_010", "Avion de ligne", "generating", "Avion de ligne vue de côté", "", "manual", None, "avions", TAXONOMY_ID, now, now),
    ]
    for row in images_data:
        if not conn.execute("SELECT 1 FROM image WHERE id = ?", [row[0]]).fetchone():
            conn.execute(
                """INSERT INTO image (id, title, status, prompt, negative_prompt, origin_type, origin_batch_id, origin_term_id, origin_taxonomy_id, file_path, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, '', ?, ?)""",
                [*row[:9], row[9], row[10]],
            )
            print(f"  + image {row[0]}")

    # ── Image outputs (liés aux jobs de génération) ─────────────────────────
    outputs_data = [
        ("out_001", "img_001", "job_gen_001", "outputs/img_001_v1.png", "png", 512, 512, 7.2, "flux/schnell", None, now),
        ("out_002", "img_002", "job_gen_002", "outputs/img_002_v1.png", "png", 512, 512, 6.8, "flux/schnell", None, now),
        ("out_003", "img_003", "job_gen_003", "outputs/img_003_v1.png", "png", 512, 512, 8.1, "flux/schnell", None, now),
        ("out_004", "img_004", "job_gen_004", "outputs/img_004_v1.png", "png", 512, 512, 7.5, "flux/schnell", None, now),
        ("out_005", "img_004", "job_gen_004", "outputs/img_004_v2.png", "png", 512, 512, 8.0, "flux/schnell", None, now),
        ("out_006", "img_006", "job_batch_001", "outputs/img_006_v1.png", "png", 512, 512, 7.0, "flux/schnell", None, now),
        ("out_007", "img_007", "job_gen_007", "outputs/img_007_v1.png", "png", 512, 512, 8.5, "flux/schnell", None, now),
    ]
    for oid, iid, jid, fp, fmt, w, h, q, model, cfg, created in outputs_data:
        if not conn.execute("SELECT 1 FROM image_output WHERE id = ?", [oid]).fetchone():
            conn.execute(
                """INSERT INTO image_output (id, image_id, job_id, file_path, file_format, width, height, quality_score, model_name, model_config, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [oid, iid, jid, fp, fmt, w, h, q, model, cfg, created],
            )
            print(f"  + output {oid}")

    # Mettre à jour selected_output_id pour les images avec outputs
    conn.execute("UPDATE image SET selected_output_id = 'out_001' WHERE id = 'img_001'")
    conn.execute("UPDATE image SET selected_output_id = 'out_002' WHERE id = 'img_002'")
    conn.execute("UPDATE image SET selected_output_id = 'out_003' WHERE id = 'img_003'")
    conn.execute("UPDATE image SET selected_output_id = 'out_005' WHERE id = 'img_004'")  # v2 meilleur
    conn.execute("UPDATE image SET selected_output_id = 'out_006' WHERE id = 'img_006'")
    conn.execute("UPDATE image SET selected_output_id = 'out_007' WHERE id = 'img_007'")

    # ── Tags taxonomiques ───────────────────────────────────────────────────
    tags_data = [
        ("img_001", TAXONOMY_ID, "animaux_domestiques"),
        ("img_001", TAXONOMY_ID, "animaux"),
        ("img_002", TAXONOMY_ID, "animaux_domestiques"),
        ("img_002", TAXONOMY_ID, "animaux"),
        ("img_003", TAXONOMY_ID, "mandalas_faciles"),
        ("img_003", TAXONOMY_ID, "mandalas"),
        ("img_004", TAXONOMY_ID, "voitures"),
        ("img_004", TAXONOMY_ID, "vehicules"),
        ("img_005", TAXONOMY_ID, "dinosaures"),
        ("img_005", TAXONOMY_ID, "animaux"),
        ("img_006", TAXONOMY_ID, "mandalas_fleurs"),
        ("img_006", TAXONOMY_ID, "mandalas"),
        ("img_007", TAXONOMY_ID, "noel"),
        ("img_007", TAXONOMY_ID, "saisons_evenements"),
        ("img_008", TAXONOMY_ID, "lettres"),
        ("img_008", TAXONOMY_ID, "educatif"),
        ("img_009", TAXONOMY_ID, "paques"),
        ("img_009", TAXONOMY_ID, "saisons_evenements"),
        ("img_010", TAXONOMY_ID, "avions"),
        ("img_010", TAXONOMY_ID, "vehicules"),
    ]
    for img_id, tax_id, term_id in tags_data:
        try:
            conn.execute(
                """INSERT INTO image_taxonomy_tag (image_id, taxonomy_id, term_id, created_at)
                   VALUES (?, ?, ?, ?)""",
                [img_id, tax_id, term_id, now],
            )
        except Exception:
            pass  # déjà présent
    print(f"  + {len(tags_data)} tags taxonomiques")

    # origin_term_id/origin_taxonomy_id déjà définis dans l'INSERT image (évite UPDATE + bug FK DuckDB)

    # ── Collections ────────────────────────────────────────────────────────
    collections_data = [
        ("col_animaux", "animaux", '{"fr":"Animaux","en":"Animals"}', "animaux", TAXONOMY_ID, now, now),
        ("col_mandalas", "mandalas", '{"fr":"Mandalas","en":"Mandalas"}', "mandalas", TAXONOMY_ID, now, now),
        ("col_noel", "noel", '{"fr":"Noël","en":"Christmas"}', "noel", TAXONOMY_ID, now, now),
        ("col_vehicules", "vehicules", '{"fr":"Véhicules","en":"Vehicles"}', "vehicules", TAXONOMY_ID, now, now),
    ]
    for cid, slug, name_i18n, term_id, tax_id, created, updated in collections_data:
        if not conn.execute("SELECT 1 FROM collection WHERE id = ?", [cid]).fetchone():
            conn.execute(
                """INSERT INTO collection (id, slug, name_i18n, term_id, taxonomy_id, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                [cid, slug, name_i18n, term_id, tax_id, created, updated],
            )
            print(f"  + collection {cid}")

    # ── Collection ↔ Image ─────────────────────────────────────────────────
    collection_images = [
        ("col_animaux", "img_001", 0),
        ("col_animaux", "img_002", 1),
        ("col_animaux", "img_005", 2),
        ("col_mandalas", "img_003", 0),
        ("col_mandalas", "img_006", 1),
        ("col_noel", "img_007", 0),
        ("col_vehicules", "img_004", 0),
    ]
    for cid, img_id, sort_order in collection_images:
        try:
            conn.execute(
                """INSERT INTO collection_image (collection_id, image_id, sort_order, created_at)
                   VALUES (?, ?, ?, ?)""",
                [cid, img_id, sort_order, now],
            )
        except Exception:
            pass
    print(f"  + {len(collection_images)} liens collection_image")

    # ── Publications site ───────────────────────────────────────────────────
    publications = [
        ("img_007", "site_fr", "published", "https://coloriage.example.fr/noel/sapin", now, now, now),
        ("img_004", "site_fr", "pending", None, None, now, now),
        ("img_003", "site_en", "published", "https://coloring.example.com/mandalas/easy", now, now, now),
    ]
    for img_id, site_id, status, url, pub_at, created, updated in publications:
        try:
            conn.execute(
                """INSERT INTO site_publication (image_id, site_id, status, published_url, published_at, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                [img_id, site_id, status, url, pub_at, created, updated],
            )
        except Exception:
            pass
    print(f"  + {len(publications)} publications site")

    # ── Batches de génération ───────────────────────────────────────────────
    batches_data = [
        ("batch_001", "Campagne Mandalas", "terms", "ai_ollama", 5, "done", now, now),
        ("batch_002", "Campagne Pâques", "terms", "ai_ollama", 3, "prompts_ready", now, now),
        ("batch_003", "Campagne Véhicules", "subtree", "template", 10, "pending", now, now),
    ]
    for bid, name, scope, strategy, per_term, status, created, updated in batches_data:
        if not conn.execute("SELECT 1 FROM generation_batch WHERE id = ?", [bid]).fetchone():
            conn.execute(
                """INSERT INTO generation_batch (id, name, scope_type, prompt_strategy, images_per_term, status, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                [bid, name, scope, strategy, per_term, status, created, updated],
            )
            print(f"  + generation_batch {bid}")
    for batch_id, term_id, tax_id, subtree in [
        ("batch_001", "mandalas_fleurs", TAXONOMY_ID, 0),
        ("batch_002", "paques", TAXONOMY_ID, 0),
        ("batch_003", "vehicules", TAXONOMY_ID, 1),
    ]:
        try:
            conn.execute(
                """INSERT INTO generation_batch_term (batch_id, term_id, taxonomy_id, include_subtree)
                   VALUES (?, ?, ?, ?)""",
                [batch_id, term_id, tax_id, subtree],
            )
        except Exception:
            pass

    conn.session.commit()
    conn.close()
    print("Seed terminé (PostgreSQL).")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a != "--reset"]
    reset = "--reset" in sys.argv
    db_path = Path(args[0]) if args else DEFAULT_DB
    seed(db_path, reset)
