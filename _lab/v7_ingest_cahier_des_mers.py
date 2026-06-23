"""V7 — Le bot INGÈRE les 10 planches du Cahier des mers (variantes, mocks).

Pipeline (ADD-ONLY, identité bot, Postgres only) :
  1. Génère les assets mock par planche (``v7_mock_assets.generate``) à la
     convention ``{slug}/{style}.{png,svg}`` (classique en premier).
  2. Pour chaque planche : crée un work_item, ``edit_load`` (charge le buffer
     depuis le ``.md`` EXISTANT de git — les 10 posts existent déjà dans
     rimalab-v2), patche ``profil`` (pour exercer la garde de distribution),
     puis COMMIT en ``mode='update'`` avec ``asset_dir`` → le bot SCANNE
     ``{slug}/`` → bloc ``variantes`` émis dans le ``.md`` + images placées
     sous ``public/img/{slug}/`` (ADD-ONLY : aucune image existante écrasée).
  3. Réindexe → drift 0.

Le ``.md`` existant est mis à jour (ajout du bloc variantes + profil) via le
flux d'édition gardé (optimistic concurrency par hash) — « MAJ contrôlée
tracké », jamais de ``--force``. Les visuels RÉELS = track Hamma.

Usage :
    PYTHONPATH=src python _lab/v7_ingest_cahier_des_mers.py \
        --repo-root /d/projets/rimalab-v2 --assets _lab/v7_assets
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from v7_mock_assets import PLANCHES, generate  # noqa: E402  (sibling module)

LAUNCH_SET = "cahier-des-mers"
PG_URL = os.environ.get(
    "COCKPIT_TEST_DATABASE_URL",
    "postgresql+psycopg://artiste:artiste@127.0.0.1:5432/artiste_coloriage",
)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo-root", required=True, help="clone rimalab-v2 (feat/fr-only-launch)")
    ap.add_argument("--assets", default="_lab/v7_assets", help="dossier racine des assets mock")
    args = ap.parse_args()
    repo_root = Path(args.repo_root).resolve()
    assets_root = Path(args.assets).resolve()

    os.environ["DATABASE_URL"] = PG_URL
    os.environ["ARTISTE_LOG_TO_FILE"] = "0"

    # 1) Génère les assets mock.
    summary = generate(assets_root)
    print(f"[assets] {len(summary)} planches générées sous {assets_root}")

    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import sessionmaker

    from api import cockpit_models  # noqa: F401
    from api.db import DBConnAdapter
    from api.models import Base
    from services.cockpit_git_publish import commit_work_item
    from services.git_indexer import DEFAULT_REPO, parse_doc, reindex
    from services.git_states import compute_drift

    def _load_staging(slug: str):
        """Charge frontmatter (dates → ISO) + corps + base_hash du .md existant."""
        rel = f"src/content/posts/fr/{slug}.md"
        parsed = parse_doc(repo_root / rel, "fr", rel)
        fm = dict(parsed.frontmatter)
        for k in ("publishDate", "datePublication", "dateModification"):
            if k in fm and hasattr(fm[k], "isoformat"):
                fm[k] = fm[k].isoformat()[:10]
        return fm, parsed.body, parsed.content_hash

    schema = f"v7_ingest_{uuid.uuid4().hex[:10]}"
    engine = create_engine(PG_URL, future=True, connect_args={"options": f"-csearch_path={schema}"})
    with engine.begin() as c:
        c.execute(text(f'CREATE SCHEMA "{schema}"'))
    Base.metadata.create_all(bind=engine, tables=[
        cockpit_models.WorkItem.__table__,
        cockpit_models.GitIndex.__table__,
    ])

    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    session = SessionLocal()
    conn = DBConnAdapter(session)

    results = []
    try:
        for i, (slug, profil) in enumerate(PLANCHES.items()):
            wid = f"wi_{i}"
            # Charge le buffer depuis le .md EXISTANT (git autoritaire) + patche le
            # profil (exerce la garde de distribution au build front). last_synced_hash
            # = base_hash → optimistic concurrency satisfaite (pas d'édition externe).
            fm, body, base_hash = _load_staging(slug)
            fm["profil"] = profil
            conn.execute(
                "INSERT INTO work_item (id, repo, locale, slug, state, last_synced_hash, "
                "staging_frontmatter, staging_body, staging_state, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [wid, DEFAULT_REPO, "fr", slug, "valide", base_hash,
                 json.dumps(fm), body, "editing", "now", "now"],
            )
            session.commit()

            # Commit UPDATE + scan d'assets → variantes[] + images placées (ADD-ONLY).
            res = commit_work_item(
                conn, wid, repo_root=repo_root, mode="update",
                asset_dir=assets_root / slug,
                commit_message=f"feat(content): variantes {slug} via cockpit (bot)",
            )
            session.commit()
            assert res.committed, f"{slug} non commité"
            styles = [v["style"] for v in res.variantes]
            assert styles and styles[0] == "classique", f"{slug} : classique pas en premier"
            results.append((slug, profil, styles, res.commit_hash, res.bot_name, res.bot_email))
            print(f"  ok {slug:16s} [{profil:7s}] {styles}  {res.commit_hash[:10]} "
                  f"by {res.bot_name}")

        # Réindexe → drift 0.
        reindex(conn, repo=DEFAULT_REPO, root=repo_root)
        session.commit()

        rows = conn.execute(
            "SELECT slug, last_synced_hash FROM work_item WHERE repo = ?", [DEFAULT_REPO]
        ).fetchall()
        gi_rows = conn.execute(
            "SELECT slug, content_hash, exists FROM git_index WHERE repo = ? AND slug IN "
            "(" + ",".join("?" * len(PLANCHES)) + ")",
            [DEFAULT_REPO, *PLANCHES.keys()],
        ).fetchall()
        gi_by_slug = {r[0]: {"content_hash": r[1], "exists": bool(r[2])} for r in gi_rows}
        drift_count = sum(
            1 for slug, lsh in rows if compute_drift(gi_by_slug.get(slug), lsh)[0]
        )
        bots = {(r[4], r[5]) for r in results}
        print(f"\n  planches={len(results)}  drift={drift_count}  bot_uniforme={len(bots) == 1}")
        assert drift_count == 0, "drift non nul"
        assert len(bots) == 1, "auteur bot non uniforme"
        print("  OK : 10 planches ingérées, classique 1er, bot uniforme, drift 0")
        return 0
    finally:
        session.close()
        with engine.begin() as c:
            c.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
