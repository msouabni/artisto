"""Génère le contenu mock du lot « Le cahier des mers » (10 planches FR + hub).

Cap : git = vérité du contenu. Ce script produit un **clone de contenu mock**
à la spec réelle de ``rimalab-v2`` (frontmatter Zod ``posts``) sous
``data/mock-content/src/content/posts/fr/`` + des **plaques mock** (PNG/WebP/
PDF/SVG placeholders aux bonnes dimensions/nommage) sous
``data/mock-content/plates/``.

Source de vérité du contenu (textes exacts + corrections déjà appliquées) :
``alwanbooks-docs/CONTENU-cahier-des-mers.md``. Les 10 planches sont embarquées
ICI **verbatim** (title / h1 / meta / alt / corps / liens sœurs) — on ne
re-dérive RIEN du CSV générique (qui contient encore l'ancien slug
``poisson-simple`` et des titres « | Alwan Books » non corrigés).

Spécificités du lot :
  - marqueur de lot ``launchSet: cahier-des-mers`` posé sur les 10 (le front
    filtre dessus, jamais sur ``categoryId``) ;
  - ``categoryId: cahier_des_mers`` → breadcrumb Accueil → Le cahier des mers →
    planche + grille hub auto côté front ;
  - slug **corrigé** ``poisson-facile`` (était ``poisson-simple``), liens
    internes des planches 2/6/10 corrigés en conséquence ;
  - source de plaque par planche (``décoloriage`` / ``lineart-fill``) → mock
    à la spec correspondante (les vraies plaques remplaceront les mocks par
    commit plus tard).

Les vraies plaques remplaceront les mocks **par commit** dans le vrai repo,
sans autre changement : l'indexeur tourne sur ``CONTENT_REPO_PATH`` (défaut =
ce dossier mock).

Idempotent : ré-exécuter régénère les fichiers à l'identique (mêmes octets pour
les .md → ``content_hash`` stable).
"""
from __future__ import annotations

import struct
import zlib
from datetime import date, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MOCK_ROOT = PROJECT_ROOT / "data" / "mock-content"
POSTS_DIR = MOCK_ROOT / "src" / "content" / "posts" / "fr"
PLATES_DIR = MOCK_ROOT / "plates"

R2_BASE = "https://assets.alwanbooks.com/coloriages"

# Marqueur de lot de lancement (contrat partagé cockpit ↔ front).
LAUNCH_SET = "cahier-des-mers"
# Catégorie hub (id interne snake_case ; slug_i18n.fr = cahier-des-mers).
CATEGORY_ID = "cahier_des_mers"

# Spec plaques (placeholders aux bonnes dimensions / nommage).
#  - source PNG : 2480×3508 (A4 @ 300 dpi portrait) — la plaque imprimable.
#  - web        : 1240×1754 (A4 @ 150 dpi).
SOURCE_W, SOURCE_H = 2480, 3508
WEB_W, WEB_H = 1240, 1754

# Référence pour le calcul des publishDate. Toutes passées (lot de lancement →
# publiable immédiatement au build courant). publishDate ≤ BUILD_TIME requis.
REF_DATE = date(2026, 6, 22)


# ── Les 10 planches du Cahier des mers (verbatim, source CONTENU-cahier-des-mers.md)
# Chaque entrée :
#   slug, plate_id, volume, source ('decoloriage' | 'lineart-fill'),
#   title, h1, meta (= description), alt, liens (slugs sœurs), corps.
PLANCHES: list[dict] = [
    {
        "slug": "baleine",
        "plate_id": "baleine-0001",
        "volume": 1600,
        "source": "decoloriage",
        "title": "Coloriage baleine à imprimer — le géant qui chante · Alwan",
        "h1": "La baleine, le géant qui chante — coloriage à imprimer",
        "meta": "Une baleine en noir & blanc qui attend tes couleurs. Coloriage baleine à imprimer, gratuit, avec le secret de son chant qui voyage sous la mer.",
        "alt": "coloriage baleine à imprimer, dessin au trait à colorier",
        "liens": ["baleine-bleue", "tortue-de-mer", "meduse"],
        "corps": (
            "Le plus grand animal du monde vit dans l'eau, et pourtant il respire l'air "
            "comme toi : de temps en temps, il remonte souffler à la surface et lâche une "
            "fontaine vers le ciel. Sous les vagues, il chante — de vraies chansons, longues "
            "et graves, qui voyagent sur des centaines de kilomètres pour qu'un autre géant "
            "les entende. Sur ta page, le chant s'est tu et les couleurs ont disparu. "
            "Pose-les doucement : un géant, ça se réveille sans bruit."
        ),
    },
    {
        "slug": "poisson-facile",
        "plate_id": "poisson-facile-0002",
        "volume": 1600,
        "source": "lineart-fill",
        "title": "Coloriage poisson facile à imprimer — pour débuter · Alwan",
        "h1": "Un poisson facile à colorier — coloriage à imprimer",
        "meta": "Un poisson tout simple, en grandes formes, pour les petites mains. Coloriage poisson facile à imprimer, gratuit — le premier coloriage de la mer.",
        "alt": "coloriage poisson facile à imprimer, dessin au trait simple à colorier",
        "liens": ["poisson-rouge", "poisson-rigolo", "crabe"],
        "corps": (
            "C'est peut-être ton tout premier poisson. Tant mieux : celui-là est tout en "
            "rondeurs, fait pour les mains qui débutent. De grandes formes, peu de traits, "
            "et toute la place pour essayer. Choisis une couleur pour le corps, une autre "
            "pour la nageoire, et regarde-le s'éveiller. Ici, il n'y a pas de faute : chaque "
            "poisson a le droit d'être de la couleur qu'on veut. À toi de jouer."
        ),
    },
    {
        "slug": "tortue-de-mer",
        "plate_id": "tortue-de-mer-0003",
        "volume": 1000,
        "source": "decoloriage",
        "title": "Coloriage tortue de mer à imprimer — la grande voyageuse",
        "h1": "La tortue de mer, la grande voyageuse — coloriage à imprimer",
        "meta": "Une tortue de mer en noir & blanc qui revient de loin. Coloriage tortue de mer à imprimer, gratuit, et le mystère de la plage qu'elle retrouve toujours.",
        "alt": "coloriage tortue de mer à imprimer, dessin au trait à colorier",
        "liens": ["baleine", "hippocampe", "crabe"],
        "corps": (
            "Elle ne marche pas, elle vole : sous l'eau, ses grandes nageoires battent comme "
            "des ailes lentes. La tortue de mer traverse des océans entiers — des milliers de "
            "kilomètres — puis revient pondre exactement sur la plage où elle est née, parfois "
            "des années plus tard. Personne ne sait vraiment comment elle s'en souvient. Sur "
            "ta page, elle est rentrée de très loin, toute pâle du voyage. Rends-lui ses "
            "couleurs : elle les a bien méritées."
        ),
    },
    {
        "slug": "hippocampe",
        "plate_id": "hippocampe-0004",
        "volume": 1000,
        "source": "lineart-fill",
        "title": "Coloriage hippocampe à imprimer — le poisson qui nage debout",
        "h1": "L'hippocampe, le poisson qui nage debout — coloriage à imprimer",
        "meta": "Un hippocampe en noir & blanc à colorier. Coloriage hippocampe à imprimer, gratuit, et la surprise du papa qui porte les bébés.",
        "alt": "coloriage hippocampe à imprimer, dessin au trait à colorier",
        "liens": ["tortue-de-mer", "pieuvre", "meduse"],
        "corps": (
            "C'est un poisson, mais il a tout fait à l'envers : il nage debout, tout droit, "
            "en remuant une minuscule nageoire si vite qu'on la voit à peine. Pour ne pas "
            "partir avec le courant, il s'accroche aux herbes avec sa queue. Et le plus "
            "étonnant : ce n'est pas la maman qui porte les bébés, c'est le papa. Sur ta "
            "page, il attend, gris et sage. Donne-lui ses couleurs — il en existe des roses, "
            "des jaunes, des mouchetés."
        ),
    },
    {
        "slug": "crabe",
        "plate_id": "crabe-0005",
        "volume": 880,
        "source": "lineart-fill",
        "title": "Coloriage crabe à imprimer — le chevalier de côté · Alwan",
        "h1": "Le crabe, le chevalier qui marche de côté — coloriage à imprimer",
        "meta": "Un crabe en noir & blanc, armure comprise. Coloriage crabe à imprimer, gratuit, et pourquoi sa pince repousse quand il la perd.",
        "alt": "coloriage crabe à imprimer, dessin au trait à colorier",
        "liens": ["tortue-de-mer", "pieuvre", "poisson-rouge"],
        "corps": (
            "Il porte son squelette à l'extérieur, comme une armure, et il avance de travers "
            "— jamais tout droit, toujours de côté. Avec ses pinces, il attrape, il pince, il "
            "bricole. S'il en perd une, pas de panique : elle repousse. Et quand il devient "
            "trop grand pour sa carapace, il en sort et s'en fabrique une neuve. Sur ta page, "
            "l'armure est encore blanche. À toi de la peindre — rouge, orange, ou bleue comme "
            "certains crabes des récifs."
        ),
    },
    {
        "slug": "poisson-rouge",
        "plate_id": "poisson-rouge-0006",
        "volume": 720,
        "source": "decoloriage",
        "title": "Coloriage poisson rouge à imprimer — celui qui se souvient",
        "h1": "Le poisson rouge, celui qu'on croit oublieux — coloriage à imprimer",
        "meta": "Le poisson rouge n'oublie pas tout en trois secondes — c'est faux ! Coloriage poisson rouge à imprimer, gratuit, et la vérité sur sa mémoire.",
        "alt": "coloriage poisson rouge à imprimer, dessin au trait à colorier",
        "liens": ["poisson-facile", "poisson-rigolo", "pieuvre"],
        "corps": (
            "On dit qu'il oublie tout en trois secondes. C'est faux. Le poisson rouge se "
            "souvient pendant des mois : il reconnaît les visages, retient des chemins, devine "
            "l'heure de son repas. Bien soigné, il peut vivre très, très longtemps — bien plus "
            "qu'on ne le croit. Et sais-tu qu'il ne naît même pas rouge ? Il vient au monde "
            "tout gris, et sa couleur arrive avec le temps. Sur ta page, c'est à toi de la "
            "faire arriver — d'un coup."
        ),
    },
    {
        "slug": "pieuvre",
        "plate_id": "pieuvre-0007",
        "volume": 720,
        "source": "decoloriage",
        "title": "Coloriage pieuvre à imprimer — le caméléon des mers · Alwan",
        "h1": "La pieuvre, le caméléon des mers — coloriage à imprimer",
        "meta": "Une pieuvre en noir & blanc qui n'attend que tes couleurs. Coloriage pieuvre à imprimer, gratuit, et trois secrets vrais : trois cœurs, sang bleu, zéro os.",
        "alt": "coloriage pieuvre à imprimer, dessin au trait à colorier",
        "liens": ["meduse", "hippocampe", "crabe"],
        "corps": (
            "Approche sans bruit. Dans le creux du rocher vit un animal sans un seul os, avec "
            "trois cœurs et du sang bleu. Quand il a peur, il devient pierre ; quand il est "
            "curieux, il devient corail — il change de couleur sans même y penser. Comme il "
            "n'a pas d'os, il se faufile par un trou grand comme son œil. Et ses huit bras "
            "réfléchissent presque tout seuls. De toute la mer, c'est lui qui a porté le plus "
            "de couleurs. Rends-lui-en — une, ou les huit."
        ),
    },
    {
        "slug": "baleine-bleue",
        "plate_id": "baleine-bleue-0008",
        "volume": 480,
        "source": "decoloriage",
        "title": "Coloriage baleine bleue à imprimer — le plus grand",
        "h1": "La baleine bleue, le plus grand animal de l'histoire — coloriage à imprimer",
        "meta": "La baleine bleue, plus grande que tous les dinosaures. Coloriage baleine bleue à imprimer, gratuit, et son cœur gros comme une petite voiture.",
        "alt": "coloriage baleine bleue à imprimer, dessin au trait à colorier",
        "liens": ["baleine", "tortue-de-mer", "meduse"],
        "corps": (
            "Aucun animal, jamais, n'a été plus grand qu'elle — pas même les dinosaures. La "
            "baleine bleue est longue comme trois autobus. Son cœur est gros comme une petite "
            "voiture, et on l'entendrait battre de loin. Le plus drôle ? Ce géant se nourrit "
            "de minuscules bestioles pas plus grosses qu'un grain de riz, qu'il avale par "
            "millions. Sur ta page, le plus grand cœur du monde attend ses couleurs. Prends "
            "ton temps : il y a de la place."
        ),
    },
    {
        "slug": "meduse",
        "plate_id": "meduse-0009",
        "volume": 480,
        "source": "decoloriage",
        "title": "Coloriage méduse à imprimer — la lanterne des mers · Alwan",
        "h1": "La méduse, presque rien et pourtant vivante — coloriage à imprimer",
        "meta": "Une méduse en noir & blanc, lumière éteinte. Coloriage méduse à imprimer, gratuit : ni cœur, ni cerveau, ni os, et pourtant bien vivante.",
        "alt": "coloriage méduse à imprimer, dessin au trait à colorier",
        "liens": ["pieuvre", "baleine-bleue", "hippocampe"],
        "corps": (
            "Pas d'os, pas de cœur, pas de cerveau — et pourtant elle vit, elle bouge, elle "
            "danse. La méduse, c'est presque de l'eau pure mise en forme. Elle se laisse "
            "porter par les courants, en ouvrant et fermant son ombrelle tout doucement. "
            "Certaines s'allument dans le noir, comme de petites lanternes. Et on en connaît "
            "une, minuscule, capable de redevenir jeune au lieu de mourir. Sur ta page, sa "
            "lumière s'est éteinte. Rallume-la avec tes couleurs."
        ),
    },
    {
        "slug": "poisson-rigolo",
        "plate_id": "poisson-rigolo-0010",
        "volume": 390,
        "source": "lineart-fill",
        "title": "Coloriage poisson rigolo à imprimer — le clown de la mer",
        "h1": "Le poisson rigolo, le clown de la mer — coloriage à imprimer",
        "meta": "Un poisson rigolo en noir & blanc, prêt à faire le clown. Coloriage poisson rigolo à imprimer, gratuit — plus les couleurs sont folles, mieux c'est.",
        "alt": "coloriage poisson rigolo à imprimer, dessin au trait à colorier",
        "liens": ["poisson-facile", "poisson-rouge", "crabe"],
        "corps": (
            "Celui-là ne se prend pas au sérieux. Avec ses yeux ronds, sa bouche en O et son "
            "air toujours étonné, on dirait qu'il vient de raconter une bêtise. Peut-être "
            "qu'il nage à l'envers pour faire rire les crabes. Peut-être qu'il a posé ses "
            "nageoires comme un chapeau. Ici, aucune règle : plus tu choisis des couleurs "
            "folles, plus il est content. Fais-en le poisson le plus rigolo de tout l'océan "
            "— c'est tout ce qu'il demande."
        ),
    },
]


def _png_placeholder(width: int, height: int) -> bytes:
    """Génère un PNG valide minimal (fond blanc) aux dimensions données."""

    def chunk(tag: bytes, data: bytes) -> bytes:
        c = tag + data
        return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)

    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)  # 8-bit RGB
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


def _svg_placeholder_decoloriage(width: int, height: int, title: str) -> str:
    """SVG bicouche placeholder façon **décoloriage** : régions multiples (issu
    de la segmentation d'une image coloriée) + contour épais."""
    return (
        f'<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}">\n'
        f'  <title>MOCK PLATE (decoloriage): {title}</title>\n'
        f'  <g id="regions">\n'
        f'    <rect x="0" y="0" width="{width}" height="{height}" fill="#ffffff"/>\n'
        f'    <ellipse cx="{width // 2}" cy="{height // 2}" '
        f'rx="{width * 3 // 8}" ry="{height // 4}" fill="#ffffff"/>\n'
        f'    <circle cx="{width // 3}" cy="{height // 3}" r="{width // 12}" fill="#ffffff"/>\n'
        f'  </g>\n'
        f'  <g id="ink" fill="none" stroke="#000000" stroke-width="6">\n'
        f'    <ellipse cx="{width // 2}" cy="{height // 2}" '
        f'rx="{width * 3 // 8}" ry="{height // 4}"/>\n'
        f'    <circle cx="{width // 3}" cy="{height // 3}" r="{width // 12}"/>\n'
        f'  </g>\n'
        f'</svg>\n'
    )


def _svg_placeholder_lineart(width: int, height: int, title: str) -> str:
    """SVG bicouche placeholder façon **lineart-fill** : grandes formes simples
    (line art épuré, peu de régions)."""
    return (
        f'<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}">\n'
        f'  <title>MOCK PLATE (lineart-fill): {title}</title>\n'
        f'  <g id="regions">\n'
        f'    <rect x="0" y="0" width="{width}" height="{height}" fill="#ffffff"/>\n'
        f'  </g>\n'
        f'  <g id="ink" fill="none" stroke="#000000" stroke-width="8">\n'
        f'    <rect x="{width // 6}" y="{height // 6}" '
        f'width="{width * 2 // 3}" height="{height * 2 // 3}" rx="{width // 12}"/>\n'
        f'  </g>\n'
        f'</svg>\n'
    )


def _publish_date_for(index: int) -> date:
    """Lot de lancement : toutes les publishDate sont PASSÉES (publiable au build
    courant). Échelonnées en arrière pour un tri stable date desc côté grille."""
    return REF_DATE - timedelta(days=index)


def _md(p: dict, index: int) -> str:
    slug = p["slug"]
    plate_id = p["plate_id"]
    pub = _publish_date_for(index).isoformat()
    # Sujet pour les keywords = le slug humanisé (sans article). Évite « la
    # baleine » issu du H1 ; donne « baleine », « poisson facile », etc.
    sujet = slug.replace("-", " ")
    title_card = f"Coloriage {sujet}"[:40]

    # Liens sœurs : la liste de slugs du doc (ordre préservé). Le retour hub
    # (↩ cahier-des-mers) est géré côté template (lien dédié), pas dans `liens`.
    liens_yaml = "\n".join(f"  - '{s}'" for s in p["liens"])
    keywords = [f"coloriage {sujet}", f"{sujet} à imprimer", "animaux marins"]
    keywords_yaml = "\n".join(f"  - '{k}'" for k in keywords)

    # title / meta peuvent contenir & et ' → YAML double-quote sûr.
    title_yaml = '"' + p["title"].replace('"', '\\"') + '"'
    h1_yaml = '"' + p["h1"].replace('"', '\\"') + '"'
    meta_yaml = '"' + p["meta"].replace('"', '\\"') + '"'
    alt_yaml = '"' + p["alt"].replace('"', '\\"') + '"'

    return (
        "---\n"
        "locale: 'fr'\n"
        f"slug: '{slug}'\n"
        f"title: {title_yaml}\n"
        f"h1: {h1_yaml}\n"
        f"title_card: '{title_card}'\n"
        f"description: {meta_yaml}\n"
        f"imageAlt: {alt_yaml}\n"
        "keywords:\n"
        f"{keywords_yaml}\n"
        f"categoryId: '{CATEGORY_ID}'\n"
        "themeIds: []\n"
        "liens:\n"
        f"{liens_yaml}\n"
        "ageMin: 4\n"
        "ageMax: 10\n"
        "niveauDifficulte: 'easy'\n"
        f"imageSource: '{R2_BASE}/png/{plate_id}.png'\n"
        f"imageWeb: '{R2_BASE}/webp/{plate_id}.webp'\n"
        f"imageThumb: '{R2_BASE}/thumbs/{plate_id}.webp'\n"
        f"imagePdf: '{R2_BASE}/pdf/{plate_id}.pdf'\n"
        f"imageSvg: '{R2_BASE}/svg/{plate_id}.svg'\n"
        "status: 'approved'\n"
        f"publishDate: {pub}\n"
        f"datePublication: {pub}\n"
        f"dateModification: {REF_DATE.isoformat()}\n"
        "featured: false\n"
        f"launchSet: '{LAUNCH_SET}'\n"
        f"clusterId: 'cahier-des-mers'\n"
        f"plateId: '{plate_id}'\n"
        f"plateSource: '{p['source']}'\n"
        f"searchVolume: {p['volume']}\n"
        "---\n\n"
        f"{p['corps']}\n"
    )


def main() -> None:
    POSTS_DIR.mkdir(parents=True, exist_ok=True)
    PLATES_DIR.mkdir(parents=True, exist_ok=True)

    # Purge les anciens .md du dossier mock (évite de laisser traîner
    # poisson-simple.md après la correction de slug).
    for old in POSTS_DIR.glob("*.md"):
        old.unlink()

    png_src = _png_placeholder(SOURCE_W, SOURCE_H)
    png_web = _png_placeholder(WEB_W, WEB_H)

    n_posts = 0
    n_plates = 0
    for index, p in enumerate(PLANCHES):
        slug = p["slug"]
        plate_id = p["plate_id"]
        (POSTS_DIR / f"{slug}.md").write_text(_md(p, index), encoding="utf-8")
        n_posts += 1

        # Plaques mock (bonnes dimensions / nommage = plate_id). Le SVG diffère
        # selon la source (décoloriage = régions multiples, lineart-fill = formes
        # simples) pour refléter la spec de chaque pipeline.
        (PLATES_DIR / f"{plate_id}.png").write_bytes(png_src)
        (PLATES_DIR / f"{plate_id}.web.png").write_bytes(png_web)
        (PLATES_DIR / f"{plate_id}.pdf").write_bytes(_pdf_placeholder(plate_id))
        if p["source"] == "decoloriage":
            svg = _svg_placeholder_decoloriage(SOURCE_W, SOURCE_H, plate_id)
        else:
            svg = _svg_placeholder_lineart(SOURCE_W, SOURCE_H, plate_id)
        (PLATES_DIR / f"{plate_id}.svg").write_text(svg, encoding="utf-8")
        n_plates += 1

    print(f"OK : {n_posts} posts mock (Cahier des mers) -> {POSTS_DIR}")
    print(f"OK : {n_plates} plaques mock (png/web/pdf/svg) -> {PLATES_DIR}")
    print(f"     launchSet={LAUNCH_SET} · categoryId={CATEGORY_ID}")


if __name__ == "__main__":
    main()
