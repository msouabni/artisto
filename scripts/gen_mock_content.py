"""Génère le jeu de contenu mock du cluster marin (Phase 1, incrément 1).

Cap : git = vérité du contenu. Ce script produit un **clone de contenu mock**
à la spec réelle de ``rimalab-v2`` (frontmatter Zod ``posts``) sous
``data/mock-content/src/content/posts/fr/`` + des **plaques mock** (PNG/PDF/SVG
placeholders aux bonnes dimensions/nommage) sous ``data/mock-content/plates/``.

Les vraies plaques remplaceront les mocks **par commit** dans le vrai repo,
sans autre changement : l'indexeur tourne sur ``CONTENT_REPO_PATH`` (défaut =
ce dossier mock).

Source des 10 sujets : ``data/clusters/cluster-marin-sujets.csv``.

Idempotent : ré-exécuter régénère les fichiers à l'identique (mêmes octets pour
les .md → ``content_hash`` stable).
"""
from __future__ import annotations

import csv
import struct
import zlib
from datetime import date, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CSV_PATH = PROJECT_ROOT / "data" / "clusters" / "cluster-marin-sujets.csv"
# Source figée cross-repo (si le CSV n'a pas encore été rapatrié dans le repo).
CSV_SOURCE = PROJECT_ROOT.parent / "alwanbooks-docs" / "resources" / "cluster-marin-sujets.csv"
MOCK_ROOT = PROJECT_ROOT / "data" / "mock-content"
POSTS_DIR = MOCK_ROOT / "src" / "content" / "posts" / "fr"
PLATES_DIR = MOCK_ROOT / "plates"

R2_BASE = "https://assets.alwanbooks.com/coloriages"

# Spec plaques (placeholders aux bonnes dimensions / nommage).
#  - source PNG : 2480×3508 (A4 @ 300 dpi portrait) — la plaque imprimable.
#  - web        : 1240×1754 (A4 @ 150 dpi).
SOURCE_W, SOURCE_H = 2480, 3508
WEB_W, WEB_H = 1240, 1754

# Référence pour le calcul des publishDate (mélange passé/futur pour la démo
# des états dérivés ecrit/programme/publie).
REF_DATE = date(2026, 6, 22)


def _png_placeholder(width: int, height: int) -> bytes:
    """Génère un PNG valide minimal (fond blanc) aux dimensions données.

    PNG « vrai fichier » (en-tête + IHDR + IDAT compressé + IEND) pour que la
    chaîne tourne sur des octets réels. Contenu = blanc uni (placeholder).
    """
    def chunk(tag: bytes, data: bytes) -> bytes:
        c = tag + data
        return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)

    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)  # 8-bit RGB
    # Lignes : 1 octet filtre (0) + width*3 octets blancs.
    row = b"\x00" + b"\xff" * (width * 3)
    raw = row * height
    idat = zlib.compress(raw, 6)
    return sig + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")


def _pdf_placeholder(title: str) -> bytes:
    """Génère un PDF A4 minimal mais valide (placeholder plaque imprimable)."""
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        None,  # contenu (rempli ci-dessous)
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    stream = f"BT /F1 18 Tf 60 760 Td (MOCK PLATE: {title}) Tj ET".encode("latin-1", "replace")
    objs[3] = b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream"

    out = b"%PDF-1.4\n"
    offsets = []
    for i, body in enumerate(objs, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"
    xref_pos = len(out)
    out += f"xref\n0 {len(objs) + 1}\n".encode()
    out += b"0000000000 65535 f \n"
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_pos}\n%%EOF\n"
    ).encode()
    return out


def _svg_placeholder(width: int, height: int, title: str) -> str:
    """SVG bicouche placeholder (contour + 1 région) à la spec coloriage."""
    return (
        f'<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}">\n'
        f'  <title>MOCK PLATE: {title}</title>\n'
        f'  <g id="regions">\n'
        f'    <rect x="0" y="0" width="{width}" height="{height}" fill="#ffffff"/>\n'
        f'  </g>\n'
        f'  <g id="ink" fill="none" stroke="#000000" stroke-width="3">\n'
        f'    <rect x="{width // 8}" y="{height // 8}" '
        f'width="{width * 3 // 4}" height="{height * 3 // 4}"/>\n'
        f'  </g>\n'
        f'</svg>\n'
    )


def _publish_date_for(index: int) -> date:
    """Échelonne les publishDate : 3 futurs (programme), 7 passés/présents (publie)."""
    # index 0..9. On met les 3 premiers (plus gros volume) au futur pour la démo.
    if index < 3:
        return REF_DATE + timedelta(days=7 * (index + 1))  # +7, +14, +21 jours → programme
    return REF_DATE - timedelta(days=5 * (index - 2))  # -5, -10, ... → publie


def _md(row: dict, index: int) -> str:
    slug = (row.get("slug_fr") or "").strip()
    sujet = (row.get("sujet_fr") or slug).strip()
    h1 = (row.get("h1_fr") or f"Coloriage {sujet}").strip()
    title = (row.get("title_fr") or h1).strip()
    plate_id = (row.get("plate_id") or slug).strip()
    pub = _publish_date_for(index).isoformat()
    desc = (
        f"Coloriage {sujet} à imprimer gratuit — illustration adaptée aux "
        f"enfants. Plaque mock du cluster animaux marins."
    )[:200]

    return (
        "---\n"
        "locale: 'fr'\n"
        f"slug: '{slug}'\n"
        f"title: '{title}'\n"
        f"title_card: 'Coloriage {sujet}'\n"
        f"description: \"{desc}\"\n"
        "keywords:\n"
        f"  - 'coloriage {sujet}'\n"
        f"  - '{sujet} à imprimer'\n"
        "  - 'animaux marins'\n"
        "categoryId: 'animals_marine'\n"
        "themeIds: []\n"
        "ageMin: 4\n"
        "ageMax: 10\n"
        "niveauDifficulte: 'easy'\n"
        f"imageSource: '{R2_BASE}/png/{plate_id}.png'\n"
        f"imageWeb: '{R2_BASE}/webp/{plate_id}.webp'\n"
        f"imageThumb: '{R2_BASE}/thumbs/{plate_id}.webp'\n"
        f"imagePdf: '{R2_BASE}/pdf/{plate_id}.pdf'\n"
        f"imageSvg: '{R2_BASE}/svg/{plate_id}.svg'\n"
        "status: 'approved'\n"
        # publishDate : champ de planification (cf. ADR §6). Distinct de
        # datePublication (legacy) qu'on garde pour rester à la spec Zod.
        f"publishDate: {pub}\n"
        f"datePublication: {pub}\n"
        f"dateModification: {REF_DATE.isoformat()}\n"
        "featured: false\n"
        f"clusterId: 'animaux-marins'\n"
        f"plateId: '{plate_id}'\n"
        "---\n\n"
        f"## À propos de ce coloriage\n\n"
        f"Plaque **mock** « {sujet} » du cluster *animaux marins*. Ce contenu "
        f"est un placeholder à la spec réelle ; la vraie plaque le remplacera "
        f"par commit dans git, sans autre changement.\n\n"
        f"## Conseils\n\n"
        f"Utilise des bleus et des verts pour l'eau, et des teintes vives pour "
        f"le sujet.\n"
    )


def main() -> None:
    POSTS_DIR.mkdir(parents=True, exist_ok=True)
    PLATES_DIR.mkdir(parents=True, exist_ok=True)

    csv_path = CSV_PATH if CSV_PATH.exists() else CSV_SOURCE
    if not csv_path.exists():
        raise SystemExit(f"CSV cluster marin introuvable ({CSV_PATH} ni {CSV_SOURCE}).")
    with csv_path.open("r", encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))

    png_src = _png_placeholder(SOURCE_W, SOURCE_H)
    png_web = _png_placeholder(WEB_W, WEB_H)

    n_posts = 0
    n_plates = 0
    for index, row in enumerate(rows):
        slug = (row.get("slug_fr") or "").strip()
        plate_id = (row.get("plate_id") or slug).strip()
        if not slug:
            continue
        (POSTS_DIR / f"{slug}.md").write_text(_md(row, index), encoding="utf-8")
        n_posts += 1

        # Plaques mock (bonnes dimensions / nommage = plate_id).
        (PLATES_DIR / f"{plate_id}.png").write_bytes(png_src)
        (PLATES_DIR / f"{plate_id}.web.png").write_bytes(png_web)
        (PLATES_DIR / f"{plate_id}.pdf").write_bytes(_pdf_placeholder(plate_id))
        (PLATES_DIR / f"{plate_id}.svg").write_text(
            _svg_placeholder(SOURCE_W, SOURCE_H, plate_id), encoding="utf-8",
        )
        n_plates += 1

    print(f"OK : {n_posts} posts mock -> {POSTS_DIR}")
    print(f"OK : {n_plates} plaques mock (png/web/pdf/svg) -> {PLATES_DIR}")


if __name__ == "__main__":
    main()
