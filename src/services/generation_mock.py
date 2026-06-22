"""Génération MOCKÉE d'une plaque + métadonnées pour un work_item — Phase 2.

Cap (cf. ADR §5 workflow HITL) : déclenchement de génération depuis le cockpit.
**En Phase 2 incrément 1, TOUT est mocké : aucun appel ComfyUI / LLM réel.**

    [work_item: construction]
        │  POST /api/cockpit/work-items/{id}/generate
        ▼
    [generation_mock] → plaque mock (plate_image.image_state=ready)
                      + métadonnées mock (title/description/body brouillon
                        dérivés de l'opportunité / du slug du work_item)
                      → remplit staging_frontmatter + staging_body
                      → staging_state = review_image

Interface RÉELLE derrière le mock (track Hamma — NE PAS implémenter ici) :

    def generate_plate_real(work_item, style_source) -> PlateArtifact:
        # 1. PromptGenerator.build_prompt(leaf_id, style=...)         (existant)
        # 2. ComfyUI ERNIE Q8 → PNG colorié                          (worker image)
        # 3. décoloriage / vectorizer → SVG bicouche + PNG print     (existant)
        # 4. upload R2 → URLs (imageSource/imageWeb/imageThumb/...)   (à câbler)
        # 5. LLM (qwen3.5:4b) → title/description/body i18n           (worker text)
        # → renvoie URLs R2 + métadonnées ; PAS de data-URI mock.

    La même signature publique (``generate`` ci-dessous) sera réutilisée : seul
    le corps « produit l'artefact » bascule du mock au worker réel (gated). Le
    reste (transitions HITL, staging, commit) est identique.

Le mock est **déterministe** (pas d'aléa réseau) et **hors-ligne**. Il produit :
  - une plaque factice : un petit SVG inline encodé en data-URI (aperçu réel
    affichable en zone Validation, sans dépendance binaire) ;
  - des métadonnées brouillon dérivées du slug / de l'opportunité reliée
    (volume, keyword), bornées selon les SOFT caps éditoriaux (titre ~40-60).

PostgreSQL unique. SQLite interdit (y compris tests).
"""
from __future__ import annotations

import base64
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any

from services.git_indexer import DEFAULT_REPO
from services.hitl import (
    HitlTransitionError,
    get_staging_state,
    set_plate_state,
    transition_staging,
)

# Style par défaut quand aucun n'est fourni / relié. 'decoloriage' = le pipeline
# pastel→décoloriage acté (cf. CLAUDE.md). Mocké ici quoi qu'il arrive.
DEFAULT_STYLE_SOURCE = "decoloriage"


class GenerationError(RuntimeError):
    """Erreur métier du déclenchement de génération (work_item absent, état KO…)."""


@dataclass
class GenerationResult:
    """Résultat d'un déclenchement de génération mock."""

    work_item_id: str
    repo: str
    locale: str
    slug: str
    style_source: str
    staging_state: str
    plate_state: str
    preview_url: str
    frontmatter: dict[str, Any]
    body: str
    mocked: bool = True
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "work_item_id": self.work_item_id,
            "repo": self.repo,
            "locale": self.locale,
            "slug": self.slug,
            "style_source": self.style_source,
            "staging_state": self.staging_state,
            "plate_state": self.plate_state,
            "preview_url": self.preview_url,
            "frontmatter": self.frontmatter,
            "body": self.body,
            "mocked": self.mocked,
            "notes": self.notes,
        }


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _humanize(slug: str) -> str:
    """`tortue-de-mer` → `Tortue de mer` (libellé lisible pour les méta brouillon)."""
    words = slug.replace("_", " ").replace("-", " ").split()
    return " ".join(words).strip().capitalize() or slug


def _mock_plate_data_uri(slug: str) -> str:
    """Plaque factice : SVG inline (data-URI). Aperçu réel, zéro dépendance binaire.

    Bicouche symbolique : un cadre + un libellé. Suffisant pour la revue image
    mock (on valide le FLUX, pas l'esthétique). Le réel produira un PNG/SVG R2.
    """
    label = _humanize(slug)
    svg = (
        "<svg xmlns='http://www.w3.org/2000/svg' width='320' height='240' "
        "viewBox='0 0 320 240'>"
        "<rect width='320' height='240' fill='#ffffff' stroke='#202124' "
        "stroke-width='4'/>"
        "<circle cx='160' cy='110' r='62' fill='none' stroke='#202124' "
        "stroke-width='3'/>"
        "<text x='160' y='205' font-family='Segoe UI, sans-serif' font-size='18' "
        f"text-anchor='middle' fill='#202124'>{label} (MOCK)</text>"
        "</svg>"
    )
    b64 = base64.b64encode(svg.encode("utf-8")).decode("ascii")
    return f"data:image/svg+xml;base64,{b64}"


def _draft_metadata(
    locale: str,
    slug: str,
    opportunity: dict[str, Any] | None,
    style_source: str,
) -> tuple[dict[str, Any], str]:
    """Métadonnées brouillon MOCK dérivées du slug / de l'opportunité reliée.

    Bornes SOFT éditoriales indicatives (cf. CLAUDE.md) : titre ~40-60,
    description ~80-130 (FR). Le mock vise le bas de fourchette, la revue texte
    humaine ajuste. Aucun LLM.
    """
    label = _humanize(slug)
    keyword = (opportunity or {}).get("keyword") or f"coloriage {label.lower()}"
    volume = (opportunity or {}).get("volume")

    title = f"Coloriage {label.lower()} à imprimer — gratuit · Alwan"
    description = (
        f"Un coloriage {label.lower()} en noir & blanc à imprimer gratuitement. "
        f"Dessin au trait simple à colorier pour petits et grands."
    )
    body = (
        f"Voici un coloriage {label.lower()} à imprimer. "
        f"(Brouillon généré automatiquement — à relire et enrichir en revue texte.)"
    )

    fm: dict[str, Any] = {
        "locale": locale,
        "slug": slug,
        "title": title,
        "title_card": f"Coloriage {label.lower()}",
        "description": description,
        "keywords": [keyword] + ([f"{label.lower()} à imprimer"] if label else []),
        "categoryId": (opportunity or {}).get("cluster") or "a_classer",
        "themeIds": [],
        "ageMin": 4,
        "ageMax": 10,
        "niveauDifficulte": "easy",
        # Références d'asset : MOCK (le réel = URLs R2 posées par le worker).
        "imageSource": f"mock://plate/{slug}.png",
        "imageSvg": f"mock://plate/{slug}.svg",
        "status": "draft",
        "publishDate": date.today().isoformat(),
        "featured": False,
        "plateSource": style_source,
    }
    if volume is not None:
        fm["searchVolume"] = int(volume)
    return fm, body


def _fetch_work_item(conn: Any, work_item_id: str) -> dict[str, Any]:
    cols = ["id", "repo", "locale", "slug", "state", "opportunity_id"]
    rows = conn.execute(
        f"SELECT {', '.join(cols)} FROM work_item WHERE id = ?", [work_item_id]
    ).fetchall()
    if not rows:
        raise GenerationError(f"work_item '{work_item_id}' introuvable")
    return dict(zip(cols, rows[0]))


def _fetch_linked_opportunity(conn: Any, wi: dict[str, Any]) -> dict[str, Any] | None:
    """Opportunité reliée (par opportunity_id, sinon fallback slug)."""
    cols = ["id", "keyword", "sujet", "slug", "volume", "kd", "score", "cluster"]
    sel = ", ".join(cols)
    oid = wi.get("opportunity_id")
    if oid:
        rows = conn.execute(
            f"SELECT {sel} FROM opportunity WHERE id = ?", [oid]
        ).fetchall()
        if rows:
            return dict(zip(cols, rows[0]))
    rows = conn.execute(
        f"SELECT {sel} FROM opportunity WHERE slug = ? ORDER BY score DESC NULLS LAST",
        [wi.get("slug")],
    ).fetchall()
    return dict(zip(cols, rows[0])) if rows else None


def generate(
    conn: Any,
    work_item_id: str,
    *,
    style_source: str | None = None,
    repo: str = DEFAULT_REPO,
) -> GenerationResult:
    """Déclenche la génération MOCK d'un work_item → plaque + méta → review_image.

    Effets (transactionnels, à committer par l'appelant via ``transaction``) :
      1. garde HITL : la transition ``staging_state → generating`` doit être
         légale (depuis none / review_image(regen) / generating / rejected) ;
      2. produit une plaque mock (``plate_image.image_state = ready``,
         ``preview_url`` = data-URI SVG) ;
      3. produit des métadonnées mock (``staging_frontmatter`` + ``staging_body``)
         dérivées de l'opportunité reliée / du slug ;
      4. transitionne ``staging_state`` → ``review_image``.

    **Aucun appel ComfyUI / LLM.** L'interface réelle est documentée en tête de
    module (track Hamma). Idempotence : ré-appeler depuis ``review_image``
    (re-génération demandée) régénère plaque + méta proprement.

    Returns:
        ``GenerationResult``.
    """
    import json

    wi = _fetch_work_item(conn, work_item_id)
    locale, slug = wi["locale"], wi["slug"]
    style = style_source or DEFAULT_STYLE_SOURCE
    notes: list[str] = []

    # 1. Garde : on entre dans la génération (none → generating, ou regen depuis
    #    review_image / generating). Transition gardée + horodatée.
    src = get_staging_state(conn, work_item_id)
    if src not in ("none", "review_image", "generating", "rejected"):
        raise HitlTransitionError(
            f"génération impossible depuis staging_state '{src}' "
            f"(autorisé : none / review_image / generating / rejected)"
        )
    if src != "generating":
        transition_staging(conn, work_item_id, "generating", src_expected=src)
    set_plate_state(conn, work_item_id, "pending")
    notes.append(f"génération MOCK déclenchée (depuis '{src}')")

    # 2. Plaque mock (aucun ComfyUI). image_state → ready.
    preview = _mock_plate_data_uri(slug)
    opp = _fetch_linked_opportunity(conn, wi)

    now = _now_iso()
    mock_meta = {
        "mock": True,
        "style_source": style,
        "seed": abs(hash(slug)) % 1_000_000,
        "derived_from": "opportunity" if opp else "slug",
        "keyword": (opp or {}).get("keyword"),
    }
    rows = conn.execute(
        "SELECT id FROM plate_image WHERE work_item_id = ?", [work_item_id]
    ).fetchall()
    if rows:
        conn.execute(
            "UPDATE plate_image SET image_state = ?, style_source = ?, "
            "preview_url = ?, mock_meta = ?, updated_at = ? WHERE id = ?",
            ["ready", style, preview, json.dumps(mock_meta), now, rows[0][0]],
        )
    else:
        from services.git_indexer import _new_id

        conn.execute(
            "INSERT INTO plate_image (id, work_item_id, image_state, style_source, "
            "preview_url, mock_meta, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [_new_id("plate"), work_item_id, "ready", style, preview,
             json.dumps(mock_meta), now, now],
        )
    notes.append("plaque mock prête (image_state=ready)")

    # 3. Métadonnées mock → staging buffer (jamais autoritaire, jamais servi).
    fm, body = _draft_metadata(locale, slug, opp, style)
    conn.execute(
        "UPDATE work_item SET staging_frontmatter = ?, staging_body = ?, updated_at = ? "
        "WHERE id = ?",
        [json.dumps(fm), body, now, work_item_id],
    )
    notes.append("métadonnées mock écrites en staging (brouillon)")

    # 4. generating → review_image (plaque + méta prêtes).
    transition_staging(conn, work_item_id, "review_image", src_expected="generating")
    notes.append("staging_state → review_image (en attente de validation IMAGE)")

    return GenerationResult(
        work_item_id=work_item_id,
        repo=repo,
        locale=locale,
        slug=slug,
        style_source=style,
        staging_state="review_image",
        plate_state="ready",
        preview_url=preview,
        frontmatter=fm,
        body=body,
        mocked=True,
        notes=notes,
    )
