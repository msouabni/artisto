# Phase 2 — Industrialisation backend décoloriage
Date : 2026-06-10
Plan parent : `docs/architect/2026-06-10_plan-migration-decoloriage-prod.md`
Brief : `docs/architect/briefs/2026-06-10_brief-phase2-industrialisation-decoloriage.md`
Pré-requis : Phase 1 (spike) PASS — `docs/reports/2026-06-10_phase1-spike-decoloriage.md`

## Contexte

Le spike Phase 1 a prouvé la chaîne `PNG pastel → src/services/decoloriage.py
(G1a→G5) → SVG bicouche → viewer`. Phase 2 industrialise le backend :
promotion du module en service propre (logging, erreurs explicites, sérialisation
typée) et branchement dans `image_post_processing_worker` **en remplacement** de
l'étage coloriage interactif d'`extract_palette`, derrière un flag de rollback
`ARTISTE_COLORING_ENGINE`. Aucune migration Alembic (D6) ; presets du moteur
immutables (D7) ; niveau `enfant` câblé (D5) ; `vectorizer` print inchangé (D4).

## Résultats

### 1. `src/services/decoloriage.py` promu en service propre

- **Logging** : ajout d'un `logger = logging.getLogger(__name__)` ; lignes
  `decoloriage start …` / `decoloriage done …` (compatible
  `artiste_logging.setup_logging("image_post_processing_worker")`).
- **Erreurs explicites** : nouvelle exception `DecoloriageError(RuntimeError)`
  levée sur image illisible (`cv2.imread` → None), dimension nulle, segmentation
  vide (0 région), masque de traits vide. Plus de crash silencieux en aval.
- **`DecoloriageResult.to_metadata() -> dict`** : sérialisation JSON-safe,
  NULL-safe sur tous les numériques, conversion en types Python natifs (jamais
  `numpy.*`). Clés exactes (contrat brief) :
  `coloring_engine`, `level`, `n_clickable`, `n_ink_regions`, `publishable_tp`,
  `crayon_distribution`, `delta_e_median`, `processing_s`.
- **Constante** `COLORING_ENGINE = "decoloriage"`, `__all__` ajouté.
- **Sorties fonctionnelles INCHANGÉES** : aucun preset/seuil touché (D7) ; le SVG
  et les fonctions cœur G1a→G5 sont identiques au spike (les 7 tests spike
  passent toujours sans modification).

### 2. Branchement worker — fonction pure `produce_coloring_artifact`

Point d'intégration exact :

| Élément | Fichier:lignes |
|---|---|
| Flag + `_resolve_coloring_engine()` | `src/workers/image_post_processing_worker.py:55-77` |
| Fonction pure `produce_coloring_artifact(...)` | `src/workers/image_post_processing_worker.py:81-154` |
| Appel dans `process()` (remplace l'ancien bloc extract_palette) | `src/workers/image_post_processing_worker.py:300-321` |
| `coloring_metadata` propagé dans le résultat | `src/workers/image_post_processing_worker.py:351-358` |
| Fusion additive dans `model_config` (`save_result`) | `src/workers/image_post_processing_worker.py:396-405` |

Signature : `produce_coloring_artifact(png_path, out_svg_path, engine, level="enfant", extract_preset=None) -> dict`.

- **Pure et testable** : aucun accès DB, aucune queue, aucun ComfyUI. Dispatche
  selon `engine`, écrit le SVG coloriage dans `out_svg_path`, retourne les
  métadonnées.
- `engine="decoloriage"` (défaut) → import local de `decolorize`, SVG bicouche,
  `result.to_metadata()`. Le `extract_preset` n'est utilisé que comme **signal
  "variante colorable"** (porte `if extract_preset:` dans `process()`), pas
  passé au moteur décoloriage.
- `engine="extract_palette"` (rollback) → `make_params(extract_preset)` →
  `extract_palette` → `render_svg(mode="blank_outlined")` — **mêmes appels
  module-level que la branche historique** (donc mockables à l'identique).
- **Flag** `ARTISTE_COLORING_ENGINE` ∈ {`decoloriage` (défaut), `extract_palette`}
  lu via `os.environ` **à chaque appel** (`_resolve_coloring_engine`, pattern
  `ARTISTE_PROMPT_STYLE`). Valeur inconnue → fallback `decoloriage` + warning.
- **SVG print** (`Vectorizer bw_default`) reste produit inconditionnellement,
  quel que soit le moteur coloriage (D4) — bloc `process()` ligne 323+ inchangé.
- **Enrichissement `model_config` additif** : `save_result` re-lit le
  `model_config` courant, ajoute `vector_svg_path`/`coloring_svg_path` puis
  **fusionne** les clés de `coloring_metadata` sans écraser les clés existantes
  (`variant_name`, `extract_preset`, `force_chromakey`, `seed`, …).

### Schéma des métadonnées `model_config` (moteur décoloriage)

```json
{
  "variant_name": "pastel_chromakey",        // pré-existant, préservé
  "extract_preset": "floodfill_chromakey_v1",// pré-existant, préservé
  "force_chromakey": true,                   // pré-existant, préservé
  "seed": 98765,                             // pré-existant, préservé
  "vector_svg_path": "data/generated/<leaf>__<variant>.svg",
  "coloring_svg_path": "data/generated/<leaf>__<variant>_coloriage.svg",
  "coloring_engine": "decoloriage",          // ◄ ajouté
  "level": "enfant",                         // ◄ ajouté
  "n_clickable": 37,                         // ◄ ajouté (int natif)
  "n_ink_regions": 3,                        // ◄ ajouté (int natif)
  "publishable_tp": false,                   // ◄ ajouté (bool natif)
  "crayon_distribution": {"#118AB2": 15, "#ffffff": 14},  // ◄ ajouté
  "delta_e_median": 41.28,                   // ◄ ajouté (float natif)
  "processing_s": 2.24                       // ◄ ajouté (float natif)
}
```

En rollback (`extract_palette`), seules `coloring_engine="extract_palette"` et
`extract_preset` sont ajoutées par le moteur (comportement legacy inchangé).

### 3. Tests — `tests/test_decoloriage_phase2.py` (14 tests)

- Flag : défaut décoloriage, lecture à chaque appel, fallback sur valeur inconnue.
- Dispatch décoloriage sur l'**image réelle du spike** (`polar_bear_on_ice`) :
  SVG bicouche écrit, clés métadonnées exactes, types natifs (pas de `numpy.*`),
  `json.dumps` ne lève pas.
- `to_metadata()` appelé directement + cas NULL-safe (`None` → 0/0.0).
- Dispatch rollback `extract_palette` (services natifs mockés), preset requis,
  moteur inconnu → `ValueError`.
- Enrichissement `model_config` additif (clés pré-existantes préservées) via DB
  SQLite in-memory.
- Aucun accès DB par le service (audit statique du module).

### Sortie pytest

```
$ python -m pytest tests/test_decoloriage_phase2.py tests/test_decoloriage_spike.py \
      tests/test_image_post_processing_worker.py -v
platform win32 -- Python 3.11.9, pytest-9.0.2
collected 32 items

tests/test_decoloriage_phase2.py ......... (14) ........................ PASSED
tests/test_decoloriage_spike.py ......................................... PASSED (7)
tests/test_image_post_processing_worker.py ........................... PASSED (11)

============================== 32 passed in 5.96s ==============================
```

Suite complète (hors module pré-cassé) :

```
$ python -m pytest tests/ -q --ignore=tests/test_content_generator.py
861 passed in 17.85s
```

`tests/test_content_generator.py` échoue à la **collection** (`ImportError:
HARAKAT_RE` absent de `services.ollama_json`) — **pré-existant**, déjà noté au
point 5 du rapport spike, sans rapport avec cette phase (module non touché).

### Preuve du dispatch des 2 moteurs

- **décoloriage** : `test_dispatch_decoloriage_writes_bilayer_svg` +
  `test_dispatch_decoloriage_metadata_keys` — SVG bicouche réel
  (`<g id="fills">`/`<g id="strokes">`/`fill-rule="evenodd"`) + métadonnées
  `coloring_engine="decoloriage"`, `n_clickable>0`.
- **extract_palette** : `test_dispatch_extract_palette_mocked` — appelle bien
  `make_params`/`extract_palette`/`render_svg(mode="blank_outlined")`,
  métadonnées `coloring_engine="extract_palette"`. Les 3 tests legacy du worker
  (`test_dispatch_extract_palette_pour_chromakey`,
  `test_update_model_config_apres_succes`, `test_idempotence_rejouable`) ont été
  épinglés sur `ARTISTE_COLORING_ENGINE=extract_palette` (le défaut prod ayant
  basculé sur décoloriage, D1) et passent inchangés sur le fond.

## Points d'attention

1. **Tests worker legacy épinglés sur le flag** : 3 tests historiques validaient
   l'ancien défaut (`extract_palette`). Ils ont été annotés avec
   `monkeypatch.setenv("ARTISTE_COLORING_ENGINE", "extract_palette")` pour
   continuer à couvrir le rollback. Le nouveau défaut prod (décoloriage) est
   couvert par `test_decoloriage_phase2.py`. Aucun test supprimé.
2. **Signal "variante colorable" = `extract_preset` présent** : le branchement
   conserve la porte historique `if extract_preset:`. Une variante sans
   `extract_preset` (ex. `lineart`) ne produit toujours QUE le SVG print. Le nom
   du preset est ignoré par le moteur décoloriage (utilisé seulement comme
   signal + transmis au moteur extract_palette en rollback). À surveiller si une
   future variante colorable n'a pas de preset extract_palette.
3. **Coût ~2,2 s/image** (G1a v3 + G2 refaits depuis le PNG) — déjà noté ; le
   worker est asynchrone, acceptable. `processing_s` est désormais persisté dans
   `model_config` pour suivi en lot.
4. **`model_config` JSON grossit** (D6, point 5 du plan) : la métadonnée
   décoloriage reste compacte (`crayon_distribution` ≈ 6 entrées). Pas de
   saturation à ce stade ; réévaluation table dédiée reportée avant Phase 4.
5. **Lecteurs `model_config` en aval** (`grep -rn "model_config" src/`) : voir
   section dédiée — aucun n'est impacté.

### Lecteurs `model_config` en aval impactés

| Lecteur | Rôle | Impact |
|---|---|---|
| `src/api/routes/images.py:253-269` (`_variant_exists`) | check ADD-ONLY via `LIKE "%variant_name%"` | **Aucun** — ne lit que `variant_name`, clé préservée |
| `src/api/routes/images.py:315/1326+` (`IMG_OUTPUT_COLS`) | renvoie `model_config` brut (TEXT) dans les réponses API | **Aucun** — passthrough, clés en plus tolérées par les clients |
| `src/workers/image_worker.py:64-123` (`_enrich_model_config_with_variant`) | pose `variant_name`/`extract_preset`/`force_chromakey` à l'enqueue | **Aucun** — s'exécute en amont, clés décoloriage ajoutées après par le post-processing |
| `src/workers/image_post_processing_worker.py` (`process`/`save_result`) | producteur des clés coloriage | **Modifié (volontaire)** — fusion additive |

**Verdict lecteurs : aucun lecteur cassé.** L'enrichissement est strictement
additif sur des clés nouvelles ; les colonnes/réponses API restant un passthrough
JSON, les clés supplémentaires sont inertes côté consommateurs.

## Vérification des 6 critères d'acceptation

| # | Critère | Statut |
|---|---|---|
| 1 | `decoloriage` (défaut) produit le SVG bicouche, SVG print toujours via vectorizer (D4) | ✓ (dispatch + bloc vectorizer inchangé) |
| 2 | `extract_palette` : comportement legacy strictement inchangé (rollback prouvé par test) | ✓ (`test_dispatch_extract_palette_mocked` + 3 tests legacy épinglés) |
| 3 | `model_config` porte les métadonnées typées sans perte des clés existantes, JSON-sérialisable natif | ✓ (`test_model_config_enrichment_additive`, `test_*_native_types`) |
| 4 | `pytest test_decoloriage_phase2 + test_decoloriage_spike` vert, sans Postgres ni ComfyUI | ✓ (32 passed ; SQLite in-memory / no-DB) |
| 5 | Aucune migration Alembic ; extract_palette/vectorizer/front non supprimés ni cassés | ✓ (aucune migration ; imports/usages conservés ; suite 861 passed) |
| 6 | Rapport présent (intégration, schéma, pytest, dispatch 2 moteurs, lecteurs aval) | ✓ (ce document) |

## Fichiers créés / modifiés

Créés :
- `tests/test_decoloriage_phase2.py` — 14 tests portables SQLite.
- `docs/reports/2026-06-10_phase2-industrialisation-decoloriage.md` — ce rapport.

Modifiés :
- `src/services/decoloriage.py` — logger, `DecoloriageError`, `to_metadata()`,
  `COLORING_ENGINE`, gardes d'erreur (image illisible / 0 région / masque vide),
  `__all__`. Sorties fonctionnelles inchangées (D7).
- `src/workers/image_post_processing_worker.py` — flag `ARTISTE_COLORING_ENGINE`
  + `_resolve_coloring_engine()` + `produce_coloring_artifact()` ; branche
  coloriage de `process()` réécrite via le dispatch ; fusion additive des
  métadonnées coloriage dans `save_result`.
- `tests/test_image_post_processing_worker.py` — 3 tests legacy épinglés sur
  `ARTISTE_COLORING_ENGINE=extract_palette` (le défaut prod a basculé).

## Décision / Verdict

**Phase 2 PASS.**

Le backend est prêt : le moteur décoloriage est le chemin coloriage interactif
par défaut (SVG bicouche), `extract_palette` reste disponible en rollback via
`ARTISTE_COLORING_ENGINE=extract_palette` (lecture par appel, pas de redémarrage).
Les métadonnées décoloriage typées sont persistées additivement dans
`ImageOutput.model_config` (D6, aucune migration), sans casser un seul lecteur
en aval. Le SVG print (vectorizer `bw_default`) est inchangé (D4), niveau
`enfant` câblé (D5), presets du moteur immutables (D7). 32 tests ciblés verts,
861 tests verts sur la suite (hors module pré-cassé `test_content_generator`,
sans rapport).

→ Feu vert pour la **Phase 3** (front colorier minimal : viewer SVG click-to-fill
réutilisable + intégration preview/review admin).
