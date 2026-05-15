"""Tests pour ``scripts/alwanbooks_pipeline.py``.

Brief : MEP-v0/D — pipeline alwanbooks (R2 + rimalab-v2).

Couverture :

1. Conversion d'un PNG master en 4 variants (Pillow + img2pdf).
2. Mock upload R2 (écrit sur disque).
3. Idempotence ETag (mock simulé).
4. Conversion Post JSON → MD Astro YAML frontmatter.
5. Helper ``_ensure_post_complete`` (défauts injectés).
6. Écriture rimalab-v2 path.
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest

sys.path.insert(0, "scripts")

import alwanbooks_pipeline as pipe  # noqa: E402


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def sample_png(tmp_path) -> Path:
    """Crée un PNG simple 100×100 pour test conversion."""
    from PIL import Image, ImageDraw
    p = tmp_path / "sample.png"
    im = Image.new("RGB", (100, 100), (255, 255, 255))
    d = ImageDraw.Draw(im)
    d.rectangle([10, 10, 90, 90], outline=(0, 0, 0), width=3)
    im.save(p)
    return p


# ── 1. Conversion master → 4 variants ────────────────────────────────────────


def test_convert_master_to_variants_returns_4_outputs(sample_png):
    """Le converter retourne master/web/thumb/pdf en bytes non-vides."""
    out = pipe.convert_master_to_variants(sample_png)
    assert set(out.keys()) == {"master", "web", "thumb", "pdf"}
    for k, b in out.items():
        assert isinstance(b, bytes), f"{k}: not bytes"
        assert len(b) > 0, f"{k}: empty"


def test_convert_master_preserves_original_png(sample_png):
    """Le `master` retourné est le contenu PNG d'origine, byte pour byte."""
    out = pipe.convert_master_to_variants(sample_png)
    assert out["master"] == sample_png.read_bytes()


def test_convert_master_web_is_webp(sample_png):
    """Le variant `web` est un WebP valide (signature)."""
    out = pipe.convert_master_to_variants(sample_png)
    assert out["web"][:4] == b"RIFF"
    assert out["web"][8:12] == b"WEBP"


def test_convert_master_thumb_is_smaller(sample_png):
    """Le thumb (400×400 max) est ≤ taille du web variant pour grosse image."""
    from PIL import Image
    out = pipe.convert_master_to_variants(sample_png)
    # Décode le thumb pour vérifier les dimensions
    th = Image.open(io.BytesIO(out["thumb"]))
    assert th.size[0] <= 400 and th.size[1] <= 400


def test_convert_master_pdf_signature(sample_png):
    """Le PDF a la signature %PDF-."""
    out = pipe.convert_master_to_variants(sample_png)
    assert out["pdf"][:5] == b"%PDF-"


# ── 2. Mock upload R2 ────────────────────────────────────────────────────────


def test_mock_upload_writes_to_disk(tmp_path, monkeypatch, sample_png):
    """Le mock écrit les 4 variants sous data/export/r2_simulated/."""
    monkeypatch.setattr(pipe, "MOCK_R2_DIR", tmp_path / "r2sim")
    out = pipe.convert_master_to_variants(sample_png)
    uploaded, skipped = pipe._upload_variants_mock("test-slug", out)
    assert len(uploaded) == 4
    assert skipped == {}
    for variant, key in uploaded.items():
        assert (tmp_path / "r2sim" / key).is_file()


# ── 3. JSON → MD Astro ─────────────────────────────────────────────────────


def test_post_json_to_md_basic():
    post = {
        "locale": "fr",
        "slug": "lion-savane",
        "title": "Lion dans la savane",
        "title_card": "Lion",
        "description": "Un beau lion qui se balade sous le soleil africain dans la savane.",
        "keywords": ["lion", "savane"],
        "categoryId": "animals_cats",
        "themeIds": ["arabic-alphabet"],
        "ageMin": 4,
        "ageMax": 10,
        "niveauDifficulte": "easy",
        "imageSource": "https://x.com/png/lion-savane.png",
        "imageWeb": "https://x.com/webp/lion-savane.webp",
        "imageThumb": "https://x.com/thumbs/lion-savane.webp",
        "imagePdf": "https://x.com/pdf/lion-savane.pdf",
        "status": "approved",
        "datePublication": "2026-05-12",
        "featured": False,
    }
    md = pipe.post_json_to_md(post)
    # Format frontmatter
    assert md.startswith("---\n")
    assert "locale: 'fr'\n" in md
    assert "slug: 'lion-savane'\n" in md
    # Date sans quotes (YAML date scalar)
    assert "datePublication: 2026-05-12\n" in md
    # themeIds liste
    assert "themeIds:" in md
    assert "  - 'arabic-alphabet'" in md
    # body
    assert "## Lion dans la savane" in md
    assert "Un beau lion" in md


def test_post_json_to_md_strips_pipeline_block():
    """Les champs `_pipeline` et `r2_slug` ne sont pas émis (debug-only)."""
    post = {
        "locale": "en",
        "slug": "lion",
        "title": "Lion",
        "title_card": "Lion",
        "description": "A simple lion drawing for kids to color in the afternoon.",
        "keywords": ["lion"],
        "categoryId": "animals",
        "themeIds": [],
        "ageMin": 4,
        "ageMax": 10,
        "niveauDifficulte": "easy",
        "imageSource": "x", "imageWeb": "x", "imageThumb": "x", "imagePdf": "x",
        "status": "approved",
        "datePublication": "2026-05-12",
        "featured": False,
        "r2_slug": "lion",
        "_pipeline": {"leaf_id": "lion_savanna"},
    }
    md = pipe.post_json_to_md(post)
    assert "r2_slug" not in md
    assert "_pipeline" not in md


def test_post_json_to_md_quotes_escaped_apostrophes():
    """Apostrophes dans le texte → doublées en YAML simple-quote."""
    post = {
        "locale": "fr",
        "slug": "x",
        "title": "L'enfant qui joue",
        "title_card": "L'enfant",
        "description": "Voici l'illustration d'un enfant qui joue avec son ballon dans le jardin.",
        "keywords": ["enfant"],
        "categoryId": "kids",
        "themeIds": [],
        "ageMin": 4, "ageMax": 10, "niveauDifficulte": "easy",
        "imageSource": "x", "imageWeb": "x", "imageThumb": "x", "imagePdf": "x",
        "status": "approved", "datePublication": "2026-05-12", "featured": False,
    }
    md = pipe.post_json_to_md(post)
    assert "title: 'L''enfant qui joue'" in md


# ── 4. _ensure_post_complete ────────────────────────────────────────────────


def test_ensure_post_complete_injects_defaults():
    """Les champs requis manquants reçoivent des défauts sains.

    ``categoryId`` est calculé depuis ``_pipeline.leaf_id`` via le mapping
    rimalab-v2 ; sans info de leaf, fallback final ``objects_things``
    (règle 8 — brief 2026-05-12).
    """
    minimal = {
        "locale": "fr", "slug": "x", "title": "T", "title_card": "Tc",
        "description": "D", "keywords": [],
    }
    out = pipe._ensure_post_complete(minimal)
    assert out["categoryId"] == "objects_things"
    assert out["themeIds"] == []
    assert out["ageMin"] == 4
    assert out["ageMax"] == 10
    assert out["niveauDifficulte"] == "easy"
    assert out["status"] == "approved"
    assert out["featured"] is False
    # datePublication injectée si absente
    assert out["datePublication"]
    # dateModification injectée (= datePublication au premier export, Zod V2)
    assert out["dateModification"]
    assert out["dateModification"] == out["datePublication"]


def test_ensure_post_complete_maps_category_from_leaf_id():
    """Le bloc ``_pipeline.leaf_id`` détermine ``categoryId`` via mapping.

    Vérifie le routing pour les 8 nouvelles catégories rimalab-v2
    (brief 2026-05-12 — commit rimalab ``5975195``).
    """
    cases = [
        # Règle 1 — lions (startswith)
        ("lion_in_savanna", "animals_lions"),
        ("lion_in_the_savanna", "animals_lions"),
        # Règle 2 — oiseaux
        ("peacock_with_open_tail", "animals_birds"),
        ("snowy_owl", "animals_birds"),
        ("turkey_bird", "animals_birds"),
        ("emperor_penguin", "animals_birds"),
        # Règle 3 — faune marine
        ("sea_turtle_swimming", "animals_marine"),
        ("great_white_shark", "animals_marine"),
        ("starfish_on_seabed", "animals_marine"),
        ("swimming_seahorse", "animals_marine"),
        ("harp_seal", "animals_marine"),
        ("crab_on_beach", "animals_marine"),
        # Règle 4 — animaux domestiques
        ("persian_cat", "animals_pets"),
        ("british_shorthair_cat", "animals_pets"),
        ("pet_rabbit", "animals_pets"),
        ("hamster", "animals_pets"),
        ("guinea_pig", "animals_pets"),
        ("french_bulldog", "animals_pets"),
        ("labrador_retriever", "animals_pets"),
        ("pet_turtle", "animals_pets"),
        ("dairy_cow", "animals_pets"),
        ("farm_donkey", "animals_pets"),
        ("sheep_with_lamb", "animals_pets"),
        # Règle 5 — faune sauvage
        ("african_elephant", "animals_wild"),
        ("asian_elephant", "animals_wild"),
        ("polar_bear_on_ice", "animals_wild"),
        ("grizzly_bear", "animals_wild"),
        ("gray_wolf", "animals_wild"),
        ("arctic_fox", "animals_wild"),
        ("bengal_tiger", "animals_wild"),
        ("snow_leopard", "animals_wild"),
        ("spotted_leopard", "animals_wild"),
        ("jaguar_in_jungle", "animals_wild"),
        ("zebra_in_savanna", "animals_wild"),
        ("chimpanzee", "animals_wild"),
        ("orangutan_in_tree", "animals_wild"),
        ("sloth_in_tree", "animals_wild"),
        ("spotted_hyena", "animals_wild"),
        ("monarch_butterfly", "animals_wild"),
        ("honey_bee", "animals_wild"),
        ("garden_snail", "animals_wild"),
        ("griffin", "animals_wild"),
        ("phoenix_rising_from_ashes", "animals_wild"),
        # Règle 6 — humains
        ("firefighter_superhero", "general_humans"),
        ("firefighter_with_hose", "general_humans"),
        ("astronaut_walking_on_moon", "general_humans"),
        ("doctor_with_stethoscope", "general_humans"),
        ("baker_with_bread", "general_humans"),
        ("chef_cooking", "general_humans"),
        ("fisherman_with_net", "general_humans"),
        ("breakdancer", "general_humans"),
        ("child_running_outdoors", "general_humans"),
        ("kid_yoga_pose", "general_humans"),
        ("family_at_iftar_table", "general_humans"),
        ("captain_america_with_shield", "general_humans"),
        ("iron_man", "general_humans"),
        ("princess_in_tower", "general_humans"),
        ("kylian_mbappe_cartoon", "general_humans"),
        ("neymar_jr_cartoon", "general_humans"),
        ("snowboarder_jump", "general_humans"),
        ("water_skiing", "general_humans"),
        ("robot_superhero", "general_humans"),
        ("football_coach", "general_humans"),
        # Règle 7 — lettres alphabet
        ("letter_d_with_dog", "letters_arabic"),
        ("letter_u_with_ufo", "letters_arabic"),
        # Règle 8 — fallback objets / motifs / véhicules / outils
        ("abstract_zentangle", "objects_things"),
        ("advanced_mandala_for_teens", "objects_things"),
        ("birthday_cake_with_candles", "objects_things"),
        ("city_car", "objects_things"),
        ("double_decker_bus", "objects_things"),
        ("subway_train", "objects_things"),
        ("first_steam_engine_train", "objects_things"),
        ("hot_air_balloon", "objects_things"),
        ("smartwatch", "objects_things"),
        ("vr_headset", "objects_things"),
        ("flat_screen_tv", "objects_things"),
        ("kitchen_oven", "objects_things"),
        ("claw_hammer", "objects_things"),
        ("wood_chisel", "objects_things"),
        ("fireplace", "objects_things"),
        ("solar_panel_on_roof", "objects_things"),
        ("ai_brain_with_circuits", "objects_things"),
        ("crescent_moon_and_star", "objects_things"),
    ]
    for leaf_id, expected_cat in cases:
        post = {
            "locale": "fr", "slug": "x", "title": "T", "title_card": "Tc",
            "description": "D", "keywords": [],
            "_pipeline": {"leaf_id": leaf_id},
        }
        out = pipe._ensure_post_complete(post)
        assert out["categoryId"] == expected_cat, (
            f"{leaf_id} should map to {expected_cat}, got {out['categoryId']}"
        )


def test_map_leaf_to_category_lion_priority_over_cat():
    """``lion_in_the_savanna`` doit aller dans ``animals_lions`` (priorité 1)
    et pas tomber dans ``animals_cats`` ou ``animals_pets`` parce que le
    mapper voit ``cat`` quelque part dans le nom."""
    assert pipe.map_leaf_to_category("lion_in_the_savanna") == "animals_lions"
    assert pipe.map_leaf_to_category("lion_in_savanna") == "animals_lions"
    assert pipe.map_leaf_to_category("lion_cub") == "animals_lions"


def test_map_leaf_to_category_polar_bear_is_wild():
    """``polar_bear_on_ice`` doit aller dans ``animals_wild`` (règle 5)."""
    assert pipe.map_leaf_to_category("polar_bear_on_ice") == "animals_wild"


def test_map_leaf_to_category_sea_turtle_is_marine():
    """``sea_turtle_swimming`` doit aller dans ``animals_marine``
    (règle 3 — ``sea_turtle`` matche avant ``pet_turtle``)."""
    assert pipe.map_leaf_to_category("sea_turtle_swimming") == "animals_marine"


def test_map_leaf_to_category_firefighter_is_human():
    """``firefighter_superhero`` doit aller dans ``general_humans``
    (règle 6 — préfixe profession)."""
    assert pipe.map_leaf_to_category("firefighter_superhero") == "general_humans"


def test_map_leaf_to_category_big_cats_not_pets():
    """``bengal_tiger`` ne doit PAS être routé vers ``animals_pets``
    (filtre big_cats — règle 4 → tombe en règle 5 ``animals_wild``)."""
    assert pipe.map_leaf_to_category("bengal_tiger") == "animals_wild"
    assert pipe.map_leaf_to_category("snow_leopard") == "animals_wild"
    assert pipe.map_leaf_to_category("jaguar_in_jungle") == "animals_wild"


def test_ensure_post_complete_filters_short_keywords():
    """Les keywords <2 chars (HARD cap Zod) sont filtrés."""
    post = {
        "locale": "fr", "slug": "x", "title": "T", "title_card": "Tc",
        "description": "D",
        "keywords": ["lion", "D", "savane", "x", "animaux", ""],
    }
    out = pipe._ensure_post_complete(post)
    assert "D" not in out["keywords"]
    assert "x" not in out["keywords"]
    assert "" not in out["keywords"]
    assert "lion" in out["keywords"]
    assert "savane" in out["keywords"]
    assert "animaux" in out["keywords"]


def test_map_leaf_to_category_handles_none():
    """``map_leaf_to_category(None)`` retourne le fallback sans crash.

    Le fallback final (règle 8) est ``objects_things`` depuis le patch
    2026-05-12 (6 nouvelles Categories rimalab).
    """
    assert pipe.map_leaf_to_category(None) == "objects_things"
    assert pipe.map_leaf_to_category("") == "objects_things"
    assert pipe.map_leaf_to_category("unknown_random_leaf") == "objects_things"


def test_ensure_post_complete_preserves_existing():
    """Les champs déjà présents ne sont pas écrasés."""
    post = {
        "locale": "fr", "slug": "x", "title": "T", "title_card": "Tc",
        "description": "D", "keywords": [],
        "categoryId": "animals", "ageMin": 6, "niveauDifficulte": "medium",
    }
    out = pipe._ensure_post_complete(post)
    assert out["categoryId"] == "animals"
    assert out["ageMin"] == 6
    assert out["niveauDifficulte"] == "medium"


# ── 5. Écriture MD vers rimalab-v2 ──────────────────────────────────────────


def test_write_post_md_creates_directory_structure(tmp_path):
    """`write_post_md` crée le path locale s'il n'existe pas."""
    fake_root = tmp_path / "rimalab-v2"
    out = pipe.write_post_md(fake_root, "ar", "asad-fi-al-ghaba", "---\n---\nbody")
    assert out.is_file()
    assert out.parent.name == "ar"
    assert out.name == "asad-fi-al-ghaba.md"


# ── 6. Helper YAML emitter ──────────────────────────────────────────────────


def test_emit_yaml_value_handles_types():
    assert pipe._emit_yaml_value(None) == "null"
    assert pipe._emit_yaml_value(True) == "true"
    assert pipe._emit_yaml_value(False) == "false"
    assert pipe._emit_yaml_value(42) == "42"
    assert pipe._emit_yaml_value("hello") == "'hello'"
    # list[str] → multiligne
    out = pipe._emit_yaml_value(["a", "b"])
    assert "- 'a'" in out
    assert "- 'b'" in out


def test_yaml_quote_escapes_single_quote():
    assert pipe._yaml_quote("L'enfant") == "'L''enfant'"


# ── 7. md5 helper ───────────────────────────────────────────────────────────


def test_md5_deterministic():
    a = pipe._md5(b"hello")
    b = pipe._md5(b"hello")
    assert a == b
    assert pipe._md5(b"hello") != pipe._md5(b"world")
