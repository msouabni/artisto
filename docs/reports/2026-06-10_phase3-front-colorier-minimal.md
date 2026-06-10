# Phase 3 — Front colorier minimal (viewer SVG + review admin)
Date : 2026-06-10
Plan parent : `docs/architect/2026-06-10_plan-migration-decoloriage-prod.md`
Brief : `docs/architect/briefs/2026-06-10_brief-phase3-front-colorier-minimal.md`
Pré-requis : Phase 1 (spike) PASS + Phase 2 (backend) PASS

## Contexte

Phase 2 a câblé le moteur décoloriage par défaut dans `image_post_processing_worker` :
chaque image colorable produit un SVG bicouche (`coloring_svg_path`) + des métadonnées
typées dans `ImageOutput.model_config` (`coloring_engine`, `level`, `n_clickable`,
`n_ink_regions`, `publishable_tp`, `crayon_distribution`, `delta_e_median`, `processing_s`).

Phase 3 livre la **surface de revue interne** : un endpoint de listing lecture seule des
artefacts décoloriage produits + le viewer click-to-fill du spike, désormais branché sur
la liste réelle (clic → coloriage), avec chargement manuel conservé en fallback.

Périmètre strictement respecté : lecture seule de `model_config` (aucune écriture, aucune
migration Alembic, schéma DB inchangé). Non touchés : `ColorierApp.tsx`, site alwanbooks,
`alwanbooks_pipeline`, artefact Fable, `extract_palette`, `vectorizer`.

## Résultats

### 1. Endpoint de listing (lecture seule)

| Élément | Fichier:lignes |
|---|---|
| Nouveau routeur `prefix="/api/decoloriage"` | `src/api/routes/decoloriage_review.py:34` |
| Route `GET /api/decoloriage/artifacts` | `src/api/routes/decoloriage_review.py:165-243` |
| Parsing défensif `model_config` (None/invalide/non-objet → ignoré) | `src/api/routes/decoloriage_review.py:107-127` |
| Helpers NULL-safe (`_safe_int`/`_safe_float`/`_safe_crayon_distribution`) | `src/api/routes/decoloriage_review.py:74-104` |
| Normalisation `coloring_svg_path` → URL servable (`_coloring_svg_url`) | `src/api/routes/decoloriage_review.py:40-71` |
| Montage du routeur | `src/api/main.py:22` (import), `src/api/main.py:107` (`include_router`) |

**Choix d'un routeur dédié** (et non extension de `images.py`) : `images.py` expose
`@router.get("/{image_id}")` qui capturerait n'importe quel chemin statique sous
`/api/images/…`. Un prefix distinct `/api/decoloriage` évite toute collision de routage
et isole la surface de revue (responsabilité unique).

**Conventions DB** : accès via `get_db_read` (pas de `SessionLocal()` brut), placeholders
SQL `?` (réécrits par `DBConnAdapter`), pré-filtre `LIKE` cross-dialect SQLite/Postgres,
filtrage fin + NULL-safe + types natifs côté Python. Aucun `numpy.*` (les métadonnées
sont déjà JSON natives en base ; les helpers re-castent en `int`/`float`/`bool` natifs).

**Chargement du SVG** : pas d'endpoint de service SVG dédié — l'URL exposée
(`coloring_svg_url`) pointe directement vers le mount static `/data/` existant
(`src/api/main.py:107`). Le `coloring_svg_path` stocké relatif (`data/generated/…svg`,
backslashes Windows tolérés) est normalisé en `/data/generated/…svg`.

#### Contrat JSON du listing

`GET /api/decoloriage/artifacts?limit=500&offset=0` →

```json
{
  "count": 1,
  "items": [
    {
      "image_output_id": "out1",
      "image_id": "img1",
      "leaf_id": "polar_bear_on_ice",
      "variant_name": "pastel_chromakey",
      "level": "enfant",
      "coloring_svg_url": "/data/generated/polar_bear_on_ice__pastel_chromakey_coloriage.svg",
      "coloring_svg_path": "data/generated/polar_bear_on_ice__pastel_chromakey_coloriage.svg",
      "n_clickable": 37,
      "n_ink_regions": 3,
      "publishable_tp": false,
      "delta_e_median": 41.28,
      "crayon_distribution": {"#118AB2": 15, "#ffffff": 14},
      "created_at": "2026-01-01T00:00:00Z"
    }
  ]
}
```

Règles d'inclusion (toutes vérifiées par tests) :
- `model_config.coloring_engine == "decoloriage"` **ET** `coloring_svg_path` interprétable
  en URL servable. Sinon l'entrée est **exclue** (extract_palette, sans/empty svg_path).
- `model_config` None / JSON tronqué / racine non-objet → entrée **ignorée**, jamais de 500.
- Numériques absents/NULL → `0` / `0.0` ; `crayon_distribution` non-dict → `{}` ;
  `publishable_tp` absent → `false`. Tri NULL-safe sur `created_at` (clé `""` si NULL).

### 2. Front — `data/decoloriage_viewer.html` (surface de revue)

Le viewer du spike a été **fait évoluer** (pas de page dédiée — le JS click-to-fill est
réutilisé en place) :

- **Carte « Artefacts décoloriage »** : au chargement, `fetch("/api/decoloriage/artifacts")`
  rend la liste (titre = leaf/variant, badge `TP ✓/✗`, ligne méta `n_clickable zones ·
  n_ink_regions encre · ΔE médian`). Bouton **Rafraîchir**.
- **Clic sur une entrée** → charge son `coloring_svg_url` dans le viewer click-to-fill
  existant (`loadUrl` → `setSvg` → `wireRegions`), marque l'entrée active.
- **Chargement initial** : `?svg=<url>` explicite → charge ce SVG + liste la revue ;
  sinon → liste + auto-sélection du 1er artefact ; si liste vide/indisponible → fallback
  sur le SVG historique du spike.
- **Fallback manuel conservé** : champ URL, bouton « Charger depuis l'URL », file-picker
  `.svg` (carte « Charger un SVG (fallback) »).
- **Conservé du spike** : palette 6 crayons + Papier, **Solution** (applique `data-color`),
  **Reset**, toggle **Guides shading**.
- **Liste vide gérée** : message « Aucun artefact décoloriage généré pour l'instant » +
  invite au chargement manuel (qui reste actif).
- **Accès admin** : carte `/data/admin.html` retitrée « Décoloriage - Revue » + description
  mise à jour (`data/admin.html:155-156`).

### 3. Tests — `tests/test_decoloriage_review_api.py` (12 tests)

Portables SQLite (via `app_with_test_db` + `test_conn` de `conftest.py`), aucun Postgres,
aucun ComfyUI. Couverture :

- Cas nominal : artefact listé, `coloring_svg_url` servable, métadonnées en types natifs.
- `coloring_svg_path` avec backslashes Windows → URL `/data/...` correcte.
- Exclusions : `coloring_engine="extract_palette"` exclu ; sans `coloring_svg_path` exclu ;
  `coloring_svg_path` vide exclu ; le vrai artefact coexistant reste listé (filtre sélectif).
- `model_config` None → ignoré sans 500 ; JSON tronqué (mais matché par le LIKE) → ignoré
  sans 500 ; racine JSON non-objet (tableau) → ignoré.
- NULL-safe : numériques NULL/absents → `0`/`0.0`, `publishable_tp` absent → `false`,
  `crayon_distribution` valeur NULL → `0` ; `created_at` NULL sur une entrée → tri sans
  `TypeError`.
- Liste vide → `{"count": 0, "items": []}`.
- Output orphelin (image absente, LEFT JOIN) → `leaf_id` None, pas d'erreur.

### Sortie pytest

```
$ PYTHONPATH=src python -m pytest tests/test_decoloriage_review_api.py -v
platform win32 -- Python 3.11.9, pytest-9.0.2
collected 12 items
tests/test_decoloriage_review_api.py ............                       [100%]
============================= 12 passed in 11.25s =============================
```

Non-régression ciblée (routes images + décoloriage backend) :

```
$ PYTHONPATH=src python -m pytest tests/test_bulk_generation_jobs.py \
    tests/test_bulk_variants_jobs.py tests/test_cli_bulk_generation_jobs.py \
    tests/test_create_image_job_workflow.py tests/test_job_review_flow.py \
    tests/test_image_post_processing_worker.py tests/test_decoloriage_phase2.py \
    tests/test_decoloriage_spike.py -q
67 passed in 12.80s
```

Suite complète (hors module pré-cassé `test_content_generator`, sans rapport) :

```
$ PYTHONPATH=src python -m pytest tests/ -q --ignore=tests/test_content_generator.py
873 passed in 17.08s
```

(861 baseline Phase 2 + 12 nouveaux tests = 873.) `tests/test_content_generator.py`
échoue toujours à la **collection** (`ImportError: HARAKAT_RE` absent de
`services.ollama_json`) — **pré-existant**, déjà noté en Phase 1/2, module non touché.

### Usage éditeur

1. Ouvrir `/data/admin.html` → carte **Décoloriage - Revue**.
2. La page liste automatiquement les artefacts décoloriage produits (panneau de droite,
   « Artefacts décoloriage »). Le premier est auto-sélectionné et affiché dans le canvas.
3. Cliquer une entrée de la liste → son SVG bicouche se charge dans le canvas click-to-fill.
4. Choisir un crayon dans la palette (6 crayons + Papier), cliquer une région pour la
   remplir. **Solution** révèle les couleurs ERNIE quantifiées, **Reset** efface, **Guides
   shading** révèle les subdivisions internes.
5. Fallback : coller une URL `/data/generated/...svg` (ou ouvrir un fichier `.svg` local)
   dans la carte « Charger un SVG (fallback) ». Le paramètre d'URL `?svg=<url>` reste pris
   en charge pour partage direct.

## Points d'attention

1. **`coloring_svg_url` non vérifié à l'existence disque** : l'endpoint expose l'URL telle
   que dérivée du chemin stocké, sans `os.path.exists`. Le viewer affiche un message
   d'erreur propre si le fetch échoue (404). C'est volontaire (lecture seule, pas d'I/O
   disque dans le listing) — à garder en tête si des chemins orphelins existent en base.
2. **Pré-filtre SQL `LIKE`** sur `"coloring_engine": "decoloriage"` (avec/sans espace) :
   cross-dialect, mais c'est le **filtre Python** (après parsing JSON) qui garantit le
   contrat exact. Un `model_config` qui contiendrait le motif dans une autre clé serait
   chargé puis écarté par le filtre Python (test `test_model_config_non_object_json_ignored`).
3. **Tri** : `created_at DESC` (récents d'abord), NULL-safe. Pas de pagination UI (le
   `limit=500` par défaut couvre largement le volume de revue actuel).
4. **Métadonnée déjà native en base** (Phase 2 garantit pas de `numpy.*`) ; les helpers
   NULL-safe sont une ceinture-bretelles défensive côté lecture.

## Vérification des 6 critères d'acceptation

| # | Critère | Statut |
|---|---|---|
| 1 | Endpoint listing : artefacts décoloriage + `coloring_svg_url` servable + métadonnées, JSON natif, NULL-safe, `get_db_read` + `?` | ✓ (`decoloriage_review.py:165-243`, tests nominal + NULL-safe) |
| 2 | Entrée non-décoloriage exclue ; `model_config` invalide/None → pas de 500 | ✓ (`test_extract_palette_entry_excluded`, `test_*_ignored_no_500`) |
| 3 | Viewer : liste + clic→SVG dans click-to-fill (6 crayons + Papier, Solution, Reset, Guides), fallback manuel, liste vide gérée, accès admin | ✓ (`decoloriage_viewer.html`, `admin.html`) |
| 4 | `pytest test_decoloriage_review_api` vert + aucune régression images, sans Postgres | ✓ (12 passed ; 67 ciblés ; 873 suite) |
| 5 | Aucune migration Alembic ; front public/export/extract_palette non touchés | ✓ (aucune migration ; seuls 2 routes + 2 HTML + 1 test) |
| 6 | Rapport (route fichier:lignes + HTTP, contrat JSON, fichiers front, pytest, usage) | ✓ (ce document) |

## Fichiers créés / modifiés

Créés :
- `src/api/routes/decoloriage_review.py` — routeur `/api/decoloriage`, route
  `GET /artifacts`, parsing défensif + helpers NULL-safe.
- `tests/test_decoloriage_review_api.py` — 12 tests portables SQLite.
- `docs/reports/2026-06-10_phase3-front-colorier-minimal.md` — ce rapport.

Modifiés :
- `src/api/main.py` — import + `include_router(decoloriage_review.router)`.
- `data/decoloriage_viewer.html` — surface de revue (liste artefacts, clic→charge,
  Rafraîchir, fallback manuel conservé, liste vide gérée) ; styles `.review-*`.
- `data/admin.html` — carte « Décoloriage - Revue » (titre + description).

## Décision / Verdict

**Phase 3 PASS.**

La surface de revue interne est fonctionnelle : `GET /api/decoloriage/artifacts` liste en
lecture seule les artefacts décoloriage produits en Phase 2 (filtre moteur + svg_path,
NULL-safe, JSON natif, défensif sur `model_config`), et le viewer click-to-fill du spike
est branché dessus (clic → coloriage), fallback manuel conservé, liste vide gérée, accessible
depuis l'admin. Aucune migration, aucun front public / export / extract_palette touché.
12 tests verts + 873 tests suite (hors module pré-cassé sans rapport).

→ Feu vert pour la **Phase 4** (export vers sites : pousser le SVG bicouche + métadonnées
dans `alwanbooks_pipeline`, ADD-ONLY).
