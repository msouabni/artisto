"""Tests V5 — variantes de style portées par le work_item + scan + sérialisation.

Couvre (Postgres éphémère ; aucun SQLite, aucun réseau réel) :
  - ``scan_variantes`` : ``classique`` en premier, reste alpha, style = basename
    sans extension, .png obligatoire, .svg optionnel ;
  - ``work_item.staging_variantes`` → bloc ``variantes`` dans le ``.md`` ;
  - sérialisation du bloc + PLACEMENT des images à la convention
    ``public/img/{slug}/{style}.{png,svg}`` ;
  - ADD-ONLY : une variante / image ajoutée n'écrase pas l'existant ;
  - garde de distribution : refus cockpit si un style interdit est posé sur
    une planche ``profil:'facile'``.

Le repo contenu est un **clone git jetable** créé dans tmp_path.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from PIL import Image

from services.cockpit_git_publish import (
    CLASSIQUE_STYLE,
    CockpitPublishError,
    check_distribution,
    commit_work_item,
    scan_variantes,
)
from services.git_indexer import DEFAULT_REPO, split_frontmatter

REPO = DEFAULT_REPO


def _git(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=str(root), capture_output=True, text=True, encoding="utf-8"
    )


@pytest.fixture
def content_clone(tmp_path) -> Path:
    """Clone git jetable : src/content/posts/fr + src/content/styles (garde V3)."""
    root = tmp_path / "content-clone"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.name", "seed")
    _git(root, "config", "user.email", "seed@local")
    (root / "src" / "content" / "posts" / "fr").mkdir(parents=True)
    # Seed styles (miroir de la garde de distribution front V3).
    styles_dir = root / "src" / "content" / "styles"
    styles_dir.mkdir(parents=True)
    (styles_dir / "classique.json").write_text(
        json.dumps({"label": "Classique", "artiste": "maison",
                    "profils": ["facile", "enfant", "ado", "adulte"]}),
        encoding="utf-8",
    )
    (styles_dir / "briques.json").write_text(
        json.dumps({"label": "Briques", "artiste": "boulon",
                    "profils": ["enfant", "ado", "adulte"]}),
        encoding="utf-8",
    )
    (styles_dir / "zentangle.json").write_text(
        json.dumps({"label": "Zentangle", "artiste": "boulon",
                    "profils": ["ado", "adulte"]}),
        encoding="utf-8",
    )
    (root / "README.md").write_text("seed\n", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-q", "-m", "seed")
    return root


def _mock_png(path: Path) -> None:
    Image.new("RGBA", (64, 64), (255, 255, 255, 255)).save(path, "PNG")


def _make_assets(tmp_path: Path, slug: str, styles: list[str], *, svg: bool = True) -> Path:
    d = tmp_path / "assets" / slug
    d.mkdir(parents=True)
    for s in styles:
        _mock_png(d / f"{s}.png")
        if svg:
            (d / f"{s}.svg").write_text(f"<svg>{s}</svg>", encoding="utf-8")
    return d


def _insert_wi(conn, wid: str, slug: str, fm: dict, *, variantes=None, body="## corps") -> None:
    conn.execute(
        "INSERT INTO work_item (id, repo, locale, slug, state, staging_frontmatter, "
        "staging_body, staging_state, staging_variantes, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [wid, REPO, "fr", slug, "valide", json.dumps(fm), body, "pending_commit",
         json.dumps(variantes) if variantes is not None else None, "now", "now"],
    )
    conn.session.commit()


def _base_fm(slug: str, **extra) -> dict:
    fm = {
        "locale": "fr", "slug": slug, "title": f"Coloriage {slug}",
        "description": "Une planche de coloriage marine à imprimer pour tester.",
        "categoryId": "cahier_des_mers", "themeIds": [],
    }
    fm.update(extra)
    return fm


# ── scan_variantes ──────────────────────────────────────────────────────────────

def test_scan_classique_first_then_alpha(tmp_path):
    d = _make_assets(tmp_path, "pieuvre", ["zentangle", "briques", "classique"])
    variantes = scan_variantes(d, slug="pieuvre")
    styles = [v.style for v in variantes]
    assert styles[0] == CLASSIQUE_STYLE
    assert styles == ["classique", "briques", "zentangle"]  # classique 1er, reste alpha


def test_scan_style_is_basename(tmp_path):
    d = _make_assets(tmp_path, "crabe", ["classique", "briques"])
    variantes = scan_variantes(d, slug="crabe")
    for v in variantes:
        assert v.image == f"/img/crabe/{v.style}.png"
        assert v.print == f"/img/crabe/{v.style}.svg"
        assert v.image_path.stem == v.style  # style = nom de fichier sans extension


def test_scan_png_only_no_svg(tmp_path):
    d = _make_assets(tmp_path, "meduse", ["classique"], svg=False)
    variantes = scan_variantes(d, slug="meduse")
    assert variantes[0].print is None
    assert variantes[0].print_path is None


def test_scan_requires_classique(tmp_path):
    d = _make_assets(tmp_path, "hippocampe", ["briques"])  # pas de classique
    with pytest.raises(CockpitPublishError, match="classique"):
        scan_variantes(d, slug="hippocampe")


def test_scan_missing_dir(tmp_path):
    with pytest.raises(CockpitPublishError, match="introuvable"):
        scan_variantes(tmp_path / "nope", slug="x")


# ── work_item.variantes (staging) → bloc .md ─────────────────────────────────────

def test_staging_variantes_emitted_in_md(conn, content_clone):
    variantes = [
        {"style": "classique", "image": "/img/baleine/classique.png", "alt": "coloriage baleine classique"},
        {"style": "briques", "image": "/img/baleine/briques.png", "alt": "baleine briques"},
    ]
    _insert_wi(conn, "wi_b", "baleine", _base_fm("baleine"), variantes=variantes)
    res = commit_work_item(conn, "wi_b", repo_root=content_clone, launch_set="cahier-des-mers")
    conn.session.commit()
    assert res.committed
    md = (content_clone / "src/content/posts/fr/baleine.md").read_text(encoding="utf-8")
    fm, _ = split_frontmatter(md)
    assert [v["style"] for v in fm["variantes"]] == ["classique", "briques"]
    assert fm["variantes"][0]["image"] == "/img/baleine/classique.png"


def test_staging_variantes_classique_forced_first(conn, content_clone):
    # classique listée en dernier dans le staging → forcée en premier à l'émission.
    variantes = [
        {"style": "briques", "image": "/img/tortue-de-mer/briques.png"},
        {"style": "classique", "image": "/img/tortue-de-mer/classique.png"},
    ]
    _insert_wi(conn, "wi_t", "tortue-de-mer", _base_fm("tortue-de-mer"), variantes=variantes)
    res = commit_work_item(conn, "wi_t", repo_root=content_clone)
    conn.session.commit()
    assert res.variantes[0]["style"] == "classique"


# ── Scan via asset_dir : bloc .md + placement images à la convention ─────────────

def test_asset_dir_scan_serializes_and_places_images(conn, content_clone, tmp_path):
    d = _make_assets(tmp_path, "pieuvre", ["classique", "briques"])
    _insert_wi(conn, "wi_p", "pieuvre", _base_fm("pieuvre", profil="enfant"))
    res = commit_work_item(
        conn, "wi_p", repo_root=content_clone, asset_dir=d, launch_set="cahier-des-mers",
    )
    conn.session.commit()
    assert res.committed
    # Bloc variantes dans le .md, classique en premier.
    fm, _ = split_frontmatter(
        (content_clone / "src/content/posts/fr/pieuvre.md").read_text(encoding="utf-8")
    )
    assert [v["style"] for v in fm["variantes"]] == ["classique", "briques"]
    # alt dérivé (« coloriage {sujet} {style} ... ») puisque non fourni.
    assert "pieuvre" in fm["variantes"][0]["alt"].lower()
    # Images placées à la convention public/img/{slug}/{style}.{png,svg}.
    img_dir = content_clone / "public" / "img" / "pieuvre"
    assert (img_dir / "classique.png").exists()
    assert (img_dir / "classique.svg").exists()
    assert (img_dir / "briques.png").exists()
    # Le commit inclut le .md ET les images.
    tracked = _git(content_clone, "ls-files", "public/img/pieuvre").stdout.strip().splitlines()
    assert "public/img/pieuvre/classique.png" in tracked


# ── ADD-ONLY : variante / image ajoutée n'écrase pas ─────────────────────────────

def test_add_only_image_not_overwritten(conn, content_clone, tmp_path):
    # 1er commit : classique seule.
    img_dir = content_clone / "public" / "img" / "crabe"
    d1 = _make_assets(tmp_path, "crabe", ["classique"])
    _insert_wi(conn, "wi_c", "crabe", _base_fm("crabe"))
    commit_work_item(conn, "wi_c", repo_root=content_clone, asset_dir=d1)
    conn.session.commit()
    before = (img_dir / "classique.png").read_bytes()

    # Réécrit l'image source mock (contenu différent) puis re-commit en force
    # (update contrôlé) — sans force=True, ADD-ONLY conserve l'existante.
    Image.new("RGBA", (128, 128), (0, 0, 0, 255)).save(d1 / "classique.png", "PNG")
    # On simule un nouveau work_item update-less : ADD-ONLY sur le .md refuserait,
    # donc on teste le placement d'image isolément via _place_variante_images.
    from services.cockpit_git_publish import _place_variante_images
    scanned = scan_variantes(d1, slug="crabe")
    _place_variante_images(content_clone, "crabe", scanned, force=False)
    after = (img_dir / "classique.png").read_bytes()
    assert after == before, "ADD-ONLY : image existante ne doit pas être écrasée"

    # Avec force=True : update contrôlé tracké → écrasée.
    _place_variante_images(content_clone, "crabe", scanned, force=True)
    assert (img_dir / "classique.png").read_bytes() != before


def test_add_only_md_refuses_existing_without_force(conn, content_clone, tmp_path):
    d = _make_assets(tmp_path, "meduse", ["classique"])
    _insert_wi(conn, "wi_m", "meduse", _base_fm("meduse"))
    commit_work_item(conn, "wi_m", repo_root=content_clone, asset_dir=d)
    conn.session.commit()
    with pytest.raises(CockpitPublishError, match="ADD-ONLY"):
        commit_work_item(conn, "wi_m", repo_root=content_clone, asset_dir=d)


# ── Garde de distribution (profil page ↔ profils du style) ───────────────────────

def test_distribution_refuses_zentangle_on_facile(conn, content_clone, tmp_path):
    d = _make_assets(tmp_path, "poisson-facile", ["classique", "zentangle"])
    _insert_wi(conn, "wi_f", "poisson-facile", _base_fm("poisson-facile", profil="facile"))
    with pytest.raises(CockpitPublishError, match="distribution"):
        commit_work_item(conn, "wi_f", repo_root=content_clone, asset_dir=d)
    # Aucun .md ni image placée (refus AVANT écriture/commit).
    assert not (content_clone / "src/content/posts/fr/poisson-facile.md").exists()


def test_distribution_allows_briques_on_enfant(conn, content_clone, tmp_path):
    d = _make_assets(tmp_path, "poisson-rouge", ["classique", "briques"])
    _insert_wi(conn, "wi_pr", "poisson-rouge", _base_fm("poisson-rouge", profil="enfant"))
    res = commit_work_item(conn, "wi_pr", repo_root=content_clone, asset_dir=d)
    conn.session.commit()
    assert res.committed
    assert {v["style"] for v in res.variantes} == {"classique", "briques"}


def test_check_distribution_unit():
    sp = {"classique": ["facile", "enfant", "ado", "adulte"], "zentangle": ["ado", "adulte"]}
    v = [{"style": "classique", "image": "x"}, {"style": "zentangle", "image": "y"}]
    # facile + zentangle → 1 violation ; classique OK.
    assert len(check_distribution(v, "facile", sp)) == 1
    # enfant : pas de garde 'facile' → 0 violation.
    assert check_distribution(v, "enfant", sp) == []
    # style inconnu du clone → laissé au build front (pas de violation locale).
    assert check_distribution([{"style": "inconnu", "image": "z"}], "facile", {}) == []
