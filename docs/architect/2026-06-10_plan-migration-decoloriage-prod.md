# Plan de migration — Décoloriage POC → Prod (pipeline + front colorier)
Date : 2026-06-10
Rôle : cadrage architecte (read-only). Ce document = roadmap + décisions. Les briefs d'exécution Claude Code sont produits phase par phase.

## Contexte

Le POC `decoloriage-validation` est **CLÔTURÉ-PASS** (cf. `docs/reports/2026-06-10_poc-decoloriage-SYNTHESE.md`). Pipeline validé :
`ERNIE pastel (PNG colorié) → segmentation OpenCV/k-means Lab (G1a) → partition (G2) → vectorisation (G3) → hiérarchie traits 2 poids (G4) → SVG bicouche click-to-fill + mapping 6 crayons (G5)`. Hypothèse pré-enregistrée validée 5/5 animaux (3,0–7,5×).

Objectif du cycle : **prendre en compte intégralement les résultats du POC en prod**, migration propre, rien laissé de côté. Le colorieur doit d'abord être **fonctionnel** sur les sorties POC ; un artefact Claude Fable affinera l'UX ensuite.

### Découverte structurante (inventaire 2026-06-10)

Une chaîne coloriage **existe déjà en prod** (actée 2026-05-31) et c'est l'objet de la réconciliation :

| Maillon prod actuel | Rôle | Chemin |
|---|---|---|
| `extract_palette` (preset `iso_trait_v3_anomaly_split`) | régions + palette + `coloring_svg` (mode `blank_outlined`) + ink SVG | `src/services/extract_palette.py` |
| `vectorizer` (VTracer, `bw_default`) | SVG **print** (impression) — orthogonal au coloriage interactif | `src/services/vectorizer.py` |
| `image_post_processing_worker` | appelle extract_palette + vectorizer, écrit les chemins SVG dans `ImageOutput.model_config` (JSON) | `src/workers/image_post_processing_worker.py:99-200` |
| `coloring_storage.get_storage_paths` | convention de chemins `data/generated/{leaf}__{variant}{,.svg,_coloriage.svg}` | `src/services/coloring_storage.py:108-134` |
| `ColorierApp.tsx` | front : charge **PNG**, calcule `coloringData` en **pixel flood-fill in-app** | `data/sites/alwanbooks/src/components/colorier/ColorierApp.tsx` |
| `alwanbooks_pipeline.py` | pousse PNG/WebP/Thumb/PDF en R2 — **ne véhicule pas de SVG coloriage** | `scripts/alwanbooks_pipeline.py` |

Le POC produit un **SVG bicouche vectoriel** (`<g id="fills">` régions cliquables `data-color`/`data-region-id` + `<g id="strokes">` traits 2 poids ink/shading) → **changement de paradigme** côté front (pixel → vectoriel natif) et **remplacement** de l'étage région/coloriage d'`extract_palette`.

## Décisions de cadrage (actées 2026-06-10)

| # | Décision | Choix |
|---|---|---|
| D1 | Réconciliation extract_palette | **Remplacement propre** : décoloriage = chemin coloriage interactif. extract_palette gardé en rollback 1 cycle (flag env), puis déprécié. |
| D2 | Front colorier Phase 1 | **Viewer SVG minimal autonome** (pont). L'artefact Claude Fable = UX finale, phase ultérieure. |
| D3 | Séquencement | **Spike end-to-end 1 image** d'abord, puis industrialisation. |
| D4 | `vectorizer` print | **Inchangé** — la vectorisation print reste sur VTracer `bw_default`. Le décoloriage ne touche que le coloriage interactif. |
| D5 | Niveaux G2 | **`enfant` en v1** (défaut POC). Param `level` câblé mais tout-petit/adulte non exposés au front v1. `publishable_tp` stocké pour info. |
| D6 | Modèle DB | **Pas de migration Alembic en v1** : chemins + métadonnées décoloriage stockés dans `ImageOutput.model_config` (JSON, pattern existant), via un helper typé. Table dédiée = à réévaluer si le JSON sature. |
| D7 | Presets POC | **Immutables** — recopiés verbatim depuis `poc/decoloriage/` (méthodo POC). Aucun reparamétrage sans nouveau bench. |

## Architecture cible

```
PromptGenerator (style=pastel)             [INCHANGÉ]
   → ComfyUI ERNIE Q8 → PNG colorié        [INCHANGÉ]
   → image_post_processing_worker          [MODIFIÉ : branche coloriage = décoloriage]
        ├─ coloriage interactif : src/services/decoloriage.py  ◄── NOUVEAU (cœur POC productionisé)
        │      → SVG bicouche + métadonnées (crayons, ink_regions, publishable_tp)
        │      → stocké via coloring_storage + chemins dans ImageOutput.model_config
        ├─ print : vectorizer bw_default     [INCHANGÉ]
        └─ [rollback] extract_palette si ARTISTE_COLORING_ENGINE=extract_palette
   → front : viewer SVG minimal              ◄── NOUVEAU (Phase 3) ; ColorierApp.tsx refondu plus tard (artefact Fable)
   → export : alwanbooks_pipeline pousse aussi le SVG bicouche  [ÉTENDU, Phase 4]
   → publication
```

Flag de bascule : `ARTISTE_COLORING_ENGINE` ∈ {`decoloriage` (défaut), `extract_palette` (rollback)}.

## Phases

### Phase 0 — Inventaire état réel ✅ FAIT
Cartographie complète de la chaîne coloriage existante (ce document, section Contexte). Aucun brief.

### Phase 1 — SPIKE end-to-end sur 1 image (point d'entrée) ✅ FAIT 2026-06-10 — spike PASS
Tranche verticale fine, prouve la chaîne avant d'industrialiser.
**Résultat** (rapport `docs/reports/2026-06-10_phase1-spike-decoloriage.md`) : chaîne prouvée sur `polar_bear_on_ice` (PNG pastel réel) → `src/services/decoloriage.py` (G1a→G5 portés verbatim) → SVG bicouche (37 zones cliquables, 3 régions-encre, 97 arcs 2 poids) → `data/decoloriage_viewer.html` + carte admin. pytest 7/7 sans Postgres. Réserve : viewer validé statiquement (à éprouver en navigateur). Coût 2,24 s/image (G1a+G2 refaits depuis le PNG, pas de cache region_map). Brief : `docs/architect/briefs/2026-06-10_brief-phase1-spike-decoloriage.md`.
- **1a** Extraire le **cœur réutilisable** du POC (pas le harness contact-sheet) dans un module prod brouillon `src/services/decoloriage.py`. Fonctions à porter (cf. inventaire) : `preprocess_meanshift`, `kmeans_lab`, `connected_regions`, `merge_v3`, `extract_region_polygons`, `extract_topological_arcs`, `classify_arc_into_ink_or_shading`, `measure_line_thickness`, `smooth_open_arc`, `compute_ink_regions`, `nearest_crayon`. Presets/constantes **recopiés verbatim** (G1a v3 params, G2 enfant, crayons, seuils ink 50/60 %, L*≥92).
- **1b** Façade unique `decolorize(png_path, level="enfant") -> DecoloriageResult` (SVG bicouche `str` + régions[crayon, hex, data-region-id, is_ink] + `publishable_tp`).
- **1c** Brancher en CLI minimal OU dans `image_post_processing` derrière le flag, produire le SVG d'**1 leaf taxonomie réel** (ex. `polar_bear_on_ice`) et le stocker via `coloring_storage`.
- **1d** **Viewer SVG minimal** (port du HTML/JS standalone G5) servi en statique (à la manière du playground ERNIE), qui charge ce SVG et fait le click-to-fill dans le navigateur.
- **Critères de sortie** : 1 leaf réel → PNG pastel → SVG bicouche → viewer le colorie (palette 6 crayons + Papier, solution, reset, toggle Guides) dans un navigateur. Livrable visuel + rapport `docs/reports/`.

### Phase 2 — Industrialiser service + worker (backend) ✅ FAIT 2026-06-10 — Phase 2 PASS
**Résultat** (rapport `docs/reports/2026-06-10_phase2-industrialisation-decoloriage.md`) : `decoloriage` est le moteur coloriage par défaut (`DEFAULT_COLORING_ENGINE`, flag `ARTISTE_COLORING_ENGINE`, rollback `extract_palette` lu par appel) ; intégré dans `image_post_processing_worker.py` (`produce_coloring_artifact`, dispatch l.300-321, fusion additive `model_config` l.396-405) ; 8 clés métadonnées typées JSON-safe ; SVG print vectorizer inchangé (D4) ; aucune migration (D6) ; aucun lecteur `model_config` aval cassé. 32 tests ciblés + 861 suite verts (hors `test_content_generator` pré-cassé). Brief : `docs/architect/briefs/2026-06-10_brief-phase2-industrialisation-decoloriage.md`.
À surveiller : « variante colorable » = présence d'un `extract_preset` (le moteur décoloriage ignore le nom du preset). Coût ~2,2 s/image (persisté en `processing_s`).
- Promotion du module spike en **service propre** : dataclasses (`DecoloriageResult`, `RegionMeta`), presets gelés, gestion d'erreurs, NULL-safe, **portable SQLite**.
- Remplacement de la branche coloriage d'`image_post_processing_worker` par le moteur décoloriage, **gated** par `ARTISTE_COLORING_ENGINE` (défaut `decoloriage`).
- Stockage des chemins + métadonnées dans `ImageOutput.model_config` via **helper typé** (clés : `coloring_engine`, `coloring_svg_path`, `level`, `publishable_tp`, `crayon_distribution`, `delta_e_median`).
- **Tests pytest** (SQLite in-memory) sur la façade + l'enrichissement model_config + le flag rollback.
- Rapport tests + état schéma (aucune migration attendue).

### Phase 3 — Front colorier minimal (viewer SVG, le « fonctionnel ») ✅ FAIT 2026-06-10 — Phase 3 PASS
**Résultat** (rapport `docs/reports/2026-06-10_phase3-front-colorier-minimal.md`) : endpoint lecture seule `GET /api/decoloriage/artifacts` (routeur dédié `src/api/routes/decoloriage_review.py`, monté `main.py:107` — routeur séparé pour éviter la capture par `images.py /{image_id}`), parsing `model_config` défensif + NULL-safe + filtre `coloring_engine="decoloriage"`. `data/decoloriage_viewer.html` branché sur la liste (clic→charge), fallback manuel + liste vide gérés, carte admin « Décoloriage - Revue ». 12 tests + 873 suite verts. Réserve : click-to-fill non éprouvé en navigateur réel (API testée). Brief : `docs/architect/briefs/2026-06-10_brief-phase3-front-colorier-minimal.md`.
- Composant **viewer SVG click-to-fill minimal réutilisable** consommant l'URL du SVG bicouche : palette 6 crayons + Papier, solution, reset, toggle Guides (tous prouvés en POC).
- Intégration **preview/review** dans l'admin (carte depuis `/data/admin.html`, comme le playground) pour la revue éditoriale.
- **Editor HTML** si un livrable JSON/config accompagne (règle projet).
- C'est le front « fonctionnel » demandé. L'artefact Claude Fable = refonte UX en phase ultérieure (remplace/enrichit ce viewer et/ou `ColorierApp.tsx`).

### Phase 4 — Export vers sites (alwanbooks_pipeline) ✅ FAIT 2026-06-10 — Phase 4 PASS (partie repo-locale)
**Résultat** (rapport `docs/reports/2026-06-10_phase4-export-svg-bicouche-r2.md`) : le SVG bicouche est poussé comme 5e asset R2 sous `coloriages/svg/{slug}.svg` (`image/svg+xml`), ADD-ONLY idempotent `master-md5` (md5 du contenu SVG), best-effort par leaf, `--mock` sûr. Seul `scripts/alwanbooks_pipeline.py` touché (zéro cross-repo). 886 tests + smoke `--mock` (`polar_bear_on_ice`). Brief : `docs/architect/briefs/2026-06-10_brief-phase4-export-svg-bicouche-r2.md`.
**⚠️ Dépendance cross-repo NON traitée (volontaire)** : rien ne consomme le SVG côté rimalab. Reco du rapport = **convention d'URL** `{ASSETS}/coloriages/svg/{slug}.svg` (zéro changement schéma Zod, fallback PNG flood-fill si 404). Le passage front pixel→vectoriel = artefact Claude Fable. À traiter dans un **brief cross-repo dédié** (Phase 4b / couplé Fable).
- Étendre le manifest/export pour pousser le **SVG bicouche (+ métadonnées)** à côté de PNG/WebP/PDF (R2 / assets site), en **ADD-ONLY**.
- Coordination cross-repo minimale : livrer l'asset SVG ; l'intégration du composant riche (Fable) côté site = phase cross-repo dédiée.

### Phase 5 — Dépréciation extract_palette
- Après N lots prod validés sur le décoloriage : retirer le chemin coloriage interactif d'`extract_palette`, garder le code 1 cycle (rollback), puis supprimer.
- Mettre à jour `CLAUDE.md` (section « Style pastel + pipeline coloriage 2026-05-31 ») + mémoire `project_extract_palette_prod`.

## Transversal (toutes phases)
- **Reporting obligatoire** : `docs/reports/YYYY-MM-DD_<type>-<name>.md` (Contexte / Résultats / Points d'attention / Décision) à chaque phase et à chaque pytest.
- **Presets immutables** (méthodo POC) ; rollback par flag env, pas par édition de presets.
- **NULL-safe** avant tri numérique ; types JSON natifs en sortie API.
- **Editor HTML** pour tout YAML/JSON livrable.
- Pas de `git push` ni de migration sans demande explicite.

## Backlog rattaché (hors périmètre migration v1)
- **b5** crayon Noir `#15151B` (yeux/truffes forcés sur Océan) — décision design system.
- **b6** mode solution paramétrable (`ernie` vs `crayon`).
- **b9** repositionner/remplacer Prune (jamais matché).
- **b1** fusion protected répétitifs (peacock) · **b2** fusion contrainte par masque de traits.
- **Artefact Claude Fable** : refonte UX front (post Phase 3).
- Exposer niveaux tout-petit/adulte au front (post v1).

## Points d'attention / à trancher en cours
1. **Niveau v1 = enfant seul** (D5). Si l'éditorial veut le sélecteur 3 niveaux dès la prod, c'est un ajout Phase 3 (pas un bloqueur).
2. **Coût Python** ~1 s/image (G1a v3 + G2 = passe coûteuse). Acceptable en post-processing asynchrone ; à surveiller en lot.
3. **Masque de traits G2 = ground truth** de la classification ink/shading : si troué, des arcs encre passent en shading. Surveiller en prod (déjà noté en G4).
4. **ΔE médian ~44** (palette saturée vs pastels) : copy UX « 6 crayons pour s'exprimer », pas « qui matchent ta photo » (limite assumée).
5. **model_config JSON** (D6) : si la métadonnée grossit (régions × crayons), réévaluer une table dédiée — à acter avant Phase 4.

## Action suivante
**Phases 1-2-3-4 closes (toutes PASS).** Le pipeline décoloriage est branché de bout en bout côté artiste-coloriage : génération → service → worker (défaut + rollback flag) → SVG bicouche → review admin → export R2. Restent :
- **Phase 4b (cross-repo, à brief dédié)** : faire consommer le SVG par le colorieur rimalab (convention d'URL recommandée) — couplé à l'artefact Claude Fable (pixel→vectoriel).
- **Phase 5 (déprécation extract_palette)** : après N lots prod validés sur décoloriage.
- ~~**Vérif navigateur réel** du viewer/click-to-fill~~ ✅ confirmé par l'utilisateur 2026-06-10 (viewer PASS en navigateur — réserve levée).

**NB organisation** : code Phases 1-4 **non commité** (`src/services/decoloriage.py`, `image_post_processing_worker.py`, `decoloriage_review.py`, `alwanbooks_pipeline.py`, 4 fichiers tests, viewer/admin HTML, `decoloriage_cli.py`) — à committer en lot quand l'utilisateur le décidera. Pas de push autonome.
**NB mémoire** : `docs/architect/MEMORY.md` mérite un `/architect-save` (4 phases livrées depuis le dernier checkpoint).
