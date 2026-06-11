# Architect Memory — Artiste Coloriage

Mis à jour : 2026-06-10 (POC décoloriage G0→G5 CLÔTURÉ-PASS + **migration POC→prod Phases 1-4 livrées, commitées, PR #2 mergée sur main**. Cutover **réactivé** sur décision utilisateur (lève l'annulation 2026-05-27), dates +15j. **Correctif process : la mémoire canonique est CE fichier (alwanbooks-docs/memory/), pas la copie in-repo artiste-coloriage/docs/architect/ — qui est périmée et à supprimer (Étape 3).**)

## ⚠️ Source de vérité — à lire en premier

**Mémoire canonique = `alwanbooks-docs/memory/architect-memory.md` (ce fichier).** La copie `artiste-coloriage/docs/architect/MEMORY.md` est **périmée** (restée en 2026-05-26) et doit être supprimée via l'Étape 3. Les skills `/architect-load` et `/architect-save` pointent encore sur la copie in-repo → **à corriger** (les faire pointer ici, ou faire l'Étape 3). Cas vécu 2026-06-10 : une session a chargé la copie périmée et a travaillé sans le contexte 2026-05-27 (posture cutover, doc Pattern A, fix push-auto). Réconcilié ici.

## État courant du projet

Cycle multi-sites clôturé bout-en-bout (prod rimalab `e2d6456`). Doc canonique migrée vers `alwanbooks-docs/` (2026-05-27, Pattern A). **2026-06-09/10 : POC décoloriage G0→G5 CLÔTURÉ-PASS** (pipeline `ERNIE pastel → segmentation → SVG bicouche click-to-fill`, hypothèse 5/5 animaux 3,0–7,5×, capitalisé §T19) **puis migration POC→prod Phases 1-4 livrées** : service `decoloriage.py`, moteur par défaut dans `image_post_processing_worker` (flag `ARTISTE_COLORING_ENGINE`, rollback `extract_palette`), review admin `GET /api/decoloriage/artifacts` + viewer (confirmé navigateur), export R2 `coloriages/svg/{slug}.svg` ADD-ONLY. 886 tests verts. **Commit `f8f9242` → PR #2 mergée sur `main`** (merge `589b12c`). Reste : Phase 4b cross-repo (conso SVG par colorieur rimalab + artefact Claude Fable, pixel→vectoriel) ; Phase 5 (déprécation extract_palette). **Cutover réactivé** (cadrage ~2026-06-16, cutover ~2026-07-10). **Cadrage fonctionnel** (6 questions 2026-05-26) toujours en attente d'arbitrage utilisateur. À réconcilier : fil 2026-05-30/06-01 (workflow unifié Phase A.1 + ADR multi-variantes) non encore intégré ici.

## Cycle en cours

- **Intitulé** : Migration décoloriage POC → prod (pipeline + front colorier)
- **Démarré** : 2026-06-10 · **Interne BOUCLÉE 2026-06-10** (Phases 1-4 PASS, commit `f8f9242`, PR #2 mergée `589b12c`)
- **Critères de sortie** :
  - ✅ Inventaire état réel (Explore) · ✅ Réconciliation actée : décoloriage **remplace** extract_palette, rollback flag (D1)
  - ✅ POC productionisé `src/services/decoloriage.py` (Ph.1-2) · ✅ SVG bicouche dans le lifecycle worker (Ph.2)
  - ✅ Front review + viewer confirmé navigateur (Ph.3) · ✅ Export R2 ADD-ONLY (Ph.4) + tests + reporting par phase
  - ✅ Commit + PR #2 mergée sur main
- **Reste (hors interne)** : [ ] Phase 4b conso SVG site rimalab + artefact Claude Fable · [ ] Phase 5 déprécation extract_palette
- **Bloqueurs** : aucun pour l'interne ; Phase 4b en attente de l'artefact Claude Fable.

### Cycle précédent — multi-sites + doc Pattern A (clos 2026-05-27)
Workflow git-as-CMS multi-sites + MEP v0 : Modèle A ADD-ONLY, Niveau 1, R2 master-md5, 1er push prod mergé (`e2d6456`, 869 pages), mini-bundle Phase 1+2+3, migration doc Pattern A → alwanbooks-docs (144 fichiers), manuel d'exploitation 10 UCs, fix bug push-auto `git_bot_push` (677 tests). Posture corrigée : l'archi propose, l'utilisateur tranche.

### Cycle parallèle — POC décoloriage (clos 2026-06-10)
G0 corpus · G1a quantif couleur · G2 partition 3 cadrans (tout-petit conditionnel) · G3 vectorisation anti-slivers · G4 hiérarchie traits 2 poids (**hypothèse 5/5 animaux**) · G5 SVG bicouche + batch 10 sujets. PASS. Détail : reports `2026-06-10_poc-decoloriage-*`.

## Échéances / Deadlines

| Date cible | Quoi | Statut | Contexte |
|---|---|---|---|
| _2026-05-09 → 2026-05-26 (multiples)_ | _Cycle MEP v0 + multi-sites Niveau 1 + R2 fix + 1er push prod + mini-bundle Phase 1+2+3 + drop arabic-alphabet_ | _fait_ | _Voir Décisions `2026-05-*`_ |
| 2026-05-27 | Migration doc Pattern A (alwanbooks-docs, 144 fichiers) + manuel exploitation 10 UCs + fix bug push-auto `git_bot_push` (677 tests) | fait | Commits `a44a9ee`/`861cf44`/`dc6fb0d` docs + `d61852b`/`6464d32` artisto |
| 2026-05-30 (proposé) | Étape 3 nettoyage : `git rm -r docs/architect/ docs/reports/` côté pipeline + README → alwanbooks-docs + idem rimalab | à faire (sans urgence) | Pré-requis : validation visuelle alwanbooks-docs OK. **Renforcé 2026-06-10** : la copie in-repo a causé un chargement de mémoire périmée. |
| 2026-06-09 → 2026-06-10 | POC décoloriage G0→G5 + extension batch + capitalisation T19 | fait | reports `2026-06-10_poc-decoloriage-*` |
| 2026-06-10 | Migration décoloriage POC→prod Phases 1-4 + commit `f8f9242` + **PR #2 mergée sur main** (`589b12c`) | fait | `briefs/2026-06-10_brief-phase{1-4}-*` + `reports/2026-06-10_phase{1-4}-*` + `architecture/2026-06-10_plan-migration-decoloriage-prod.md` |
| 2026-06-16 (réactivé +15j) | Cadrer date cutover J+30 + brief court coordination | à faire | **Cutover RÉACTIVÉ 2026-06-10** (lève l'annulation 2026-05-27, décision utilisateur). Ex-2026-06-01. |
| 2026-07-03 (réactivé +15j) | Phase 6 Documentation/Release rimalab (ADR §1.13/§1.14 + checklist cutover) | à faire | Lié au cutover. |
| 2026-07-10 (réactivé +15j) | Cutover J+30 alwanbooks.com | à faire | Verbe `pipeline cutover` livré, jamais exécuté. |
| (sans date) | Phase 4b cross-repo : conso SVG par colorieur rimalab + artefact Claude Fable | à faire | Convention d'URL reco. Brief cross-repo dédié. |
| (sans date) | Phase 5 : déprécation extract_palette (chemin coloriage interactif) | à faire | Après N lots prod validés sur décoloriage. |
| (en attente) | Arbitrage utilisateur des 6 questions de cadrage fonctionnel | à faire (utilisateur) | `notes/2026-05-26_point-fonctionnel-cadrage-plateforme.md` §2 |

## Décisions architecturales actées

| Date | Décision | Statut | Rapport |
|---|---|---|---|
| 2026-05-05 → 06 | _Consolidation fondations_ : routing LLM (qwen3.5:4b texte / 9b vision / gemma4 arbitre, batching vision banni) · `/no_think` qwen3 strict vs `"think":false` qwen3.5+ · bornes Zod HARD/SOFT par locale · params image figés (euler/8/1.0/normal) | Actée | `2026-05-05_decision-llm-finale.md`, `2026-05-06_poc-seed-variance.md` |
| 2026-05-09 → 10 | _Consolidation_ : PromptGenerator service · audit cartographie · fix `2_objets` · annotateur v2 + greffon prod · 8 transferts skill P3 · pivot T25 · gate ERNIE · H3 45 sub-cats · Plan MEP v0 · worker image ERNIE-only · Spec subject · Vague 1 MEP v0 | Actée — consolidée | Rapports `2026-05-09_*`, `2026-05-10_*` |
| 2026-05-12 → 15 | MEP-v0/C1+C2+C3+D livrés · audit contrat rimalab 100 % · 7 catégories rimalab (`6889870`) · registry categories cross-repo + `--sync-categories` | Actée — livrée | `2026-05-12_*`, `2026-05-14_*`, `2026-05-15_*` |
| 2026-05-24 | **Modèle A — ADD-ONLY + blocklist + regen explicite** (posts+themes) ; Categories sync strict. Multi-sites Niveau 1 (`destination_sites.json` + clones gitignored) | Actée | `architecture/workflow-pipeline-multi-sites.md` |
| 2026-05-25 → 26 | _Consolidation multi-sites_ : Niveau 1 (669 tests) · R2 idempotence `master-md5` · 3 règles démarche briefs · MILESTONE 1er push prod (`e2d6456`, 869 pages) · bascule C1→C2 HTTPS · editorial seed corrigé · auto-tagging themeIds · mini-bundle Phase 1+2+3 · CLI `--regen` répétable · couplage ADR §1.13+§1.14 Phase 6 | Actée — livrée | `2026-05-25_phase-premier-push-prod-pipeline.md`, `2026-05-26_phase-bundle-categories-editorial-drop-theme-argparse.md` |
| 2026-05-27 | **Migration doc Pattern A vers `alwanbooks-docs`** (repo privé) : `architecture/`, `briefs/`, `reports/`, `notes/`, `contracts/`, `memory/`, `adr/` (MADR). 144 fichiers migrés. Doc canonique = ce repo | Actée — livrée | Commit `a44a9ee` alwanbooks-docs |
| 2026-05-27 | **Manuel d'exploitation `exploiter-plateforme-comme-cms.md`** (1648 lignes, 10 UCs) | Actée — livrée | Commits `861cf44`+`dc6fb0d` |
| 2026-05-27 | **Posture archi — ne pas pousser vers le cutover** : l'archi propose, l'utilisateur tranche. Questions de cadrage fonctionnel ouvertes | Actée — règle posture | `notes/2026-05-26_point-fonctionnel-cadrage-plateforme.md` |
| 2026-05-27 | **Setup Obsidian + footnotes** (vault = alwanbooks-docs, wikilinks OFF) · **Fix bug push-auto `git_bot_push`** (677 tests, branche `bot/lot-{date}`) | Actée — livrée | `reports/2026-05-27_phase-fix-pipeline-push-auto-bot-branch.md` |
| 2026-06-01 | **ADR multi-variantes par leaf_id** (pastel_chromakey default, flat_cartoon_chromakey + lineart opt-in) | Actée | `adr/2026-06-01_multi-variantes-coloriage.md` (commit `c8e4539`) — _mémoire à réconcilier sur le fil workflow unifié Phase A.1 (`briefs/2026-05-30_*`)_ |
| 2026-06-10 | **POC `decoloriage-validation` CLÔTURÉ-PASS** : ERNIE pastel → segmentation → SVG bicouche. Hypothèse régions(c) ≥ 2× line art validée 5/5 animaux. Remplace binarisation+potrace pour coloriage interactif. §T19 | Actée — livrée | `reports/2026-06-10_poc-decoloriage-SYNTHESE.md` |
| 2026-06-10 | **Tout-petit CONDITIONNEL** : `publishable_tp = non_protected ≤ 12 ET protected_immune ≤ 15` (5/10). Protected immunes à tous niveaux | Actée | `reports/2026-06-10_poc-decoloriage-g2.md` |
| 2026-06-10 | **Mapping 6 crayons via ΔE Lab** + Papier si L*≥92. Solution = lecture stylisée (ΔE médian ~44) | Actée | `reports/2026-06-10_poc-decoloriage-g5.md` |
| 2026-06-10 | **Migration décoloriage POC→prod (Phases 1-4 PASS) + PR #2 mergée** : service `decoloriage.py` G1a→G5 ; moteur par défaut worker (flag `ARTISTE_COLORING_ENGINE`, rollback extract_palette) ; métadonnées `model_config` ; review `GET /api/decoloriage/artifacts` + viewer ; export R2 `coloriages/svg/{slug}.svg` ADD-ONLY. Commit `f8f9242` → merge `589b12c` (commit thématique large incl. écosystème pastel/vectorize/playground non commité) | Actée — livrée + mergée | `adr/2026-06-10_decoloriage-pipeline.md` + `architecture/2026-06-10_plan-migration-decoloriage-prod.md` |
| 2026-06-10 | **Cutover RÉACTIVÉ** (lève l'annulation 2026-05-27, décision utilisateur) : dates +15j (cadrage ~2026-06-16, cutover ~2026-07-10) | Actée — réactivation | Conversation 2026-06-10 |

## Dette technique connue

| Sujet | Origine / détail | Sévérité | Suite |
|---|---|---|---|
| **Mémoire dupliquée 2 repos + skills pointent sur la copie périmée** | `/architect-load`/`-save` lisent `artiste-coloriage/docs/architect/MEMORY.md` (périmé 2026-05-26) au lieu du canonique alwanbooks-docs. A causé un chargement obsolète 2026-06-10 | **À corriger** | Étape 3 (`git rm` in-repo) + repointer les skills vers alwanbooks-docs |
| Helper `find_metrics_entry` n'itère pas `subjects` | `scripts/poc_rerun_2objets.py:71` | Mineure | Si relance POC `2_objets` |
| Import `HARAKAT_RE` cassé `tests/test_content_generator.py` | Empêche l'import ; pytest l'ignore | À investiguer | Stabilisation tests legacy |
| `data/artiste_coloriage.duckdb` legacy | Cf. CLAUDE.md | Documentaire | Ne pas lire en prod |
| Migration progressive R2 metadata `master-md5` | 405 objets sans metadata, skip via ETag | Documentaire | Aucune action |
| SSH host key absent sandbox | Bascule C2 HTTPS OK | À documenter | C2 HTTPS permanent |
| Schema Zod Categories `.passthrough()` vs `.refine()` | Editorial hors bornes non rejeté au build | Mineure | Vérifier avec rimalab |
| Tests collection (`test_import_subjects_v0`, `test_start_singleton_lock`) | ModuleNotFoundError au collect | À investiguer | Cycle stabilisation legacy |
| Manuel exploitation peut diverger du code | Cas UC1 2026-05-27 | À surveiller | Relire UC concerné à chaque modif majeure |
| **Étape 3 nettoyage `docs/architect/`+`docs/reports/` côté pipeline non faite** | Migration Pattern A a copié, sources préservées local | À faire | `git rm` + README → alwanbooks-docs |
| Réconciliation décoloriage vs `extract_palette` | **Tranchée (D1 : remplacement, rollback flag)** | Résolu | extract_palette déprécié Phase 5 |
| Backlog coloriage non commité | **Résorbé par `f8f9242`/PR #2** (écosystème pastel/vectorize/playground/décoloriage). RESTENT untracked côté artisto : rapports multi-sites 2026-05-25/26/27 + point-fonctionnel + brief mini-bundle | Mineure | Commit séparé |
| **`.gitignore` lacunaire** | `_lab/`, `data/sites/`, `data/outputs/`, `data/generated/` untracked malgré CLAUDE.md ; + fichier junk `"utput ACCESS_KEY_ID…"` | Mineure | Corriger `.gitignore` + supprimer junk |
| **Fil 2026-05-30/06-01 non intégré en mémoire** | Workflow unifié Phase A.1 (`briefs/2026-05-30_*` + Alembic 0011) + ADR multi-variantes (`2026-06-01`) postérieurs à la mémoire 2026-05-27, jamais consolidés | À investiguer | Lire ces docs + consolider dans cette mémoire |

## Hypothèses en cours de validation

- **`Solo bird` à l'échelle** : template prêt, jamais testé en scale-bench. À valider sur 14 leaves (post-MEP v0).
- **Modèle A ADD-ONLY préserve les éditions manuelles** : confirmé sur runs successifs. Reste « humain édite MD → pipeline push → diff nul ».
- **Cutover via verbe pipeline en run prod** : verbe livré + tests, jamais exécuté.
- **Push auto `bot/lot-{date}` en prod (credential helper Windows)** : smoke 3 OK 2026-05-27. À surveiller sur 5-10 lots.

## Pièges découverts

### LLM
- **`/no_think` opère uniquement sur `qwen3:` strict** ; qwen3.5+ → `"think": false`. **Batching vision** dégrade → 1 image/call. **Description AR qwen3.5:4b** dépasse 100 chars (~37 % retry), harakat ~26 % → strip. **QC anatomie via LLM vision = invalidé** (humain only).

### Image / sampler
- **`karras` catastrophique** sujets complexes (invalidé). **`dpmpp_2m` banni**, euler seul. **`cfg ≥ 1.5` → `3_jambes`**, garder cfg=1.0. **ComfyUI partagé** = latence ×3-4.

### Décoloriage / segmentation (POC 2026-06-10)
- **`skimage.find_contours` ignore les contours de bord** → padding sentinel 1 px + décalage −1.
- **Chaikin arrondit les coins image** → skip Chaikin si vertex < 3 px d'un bord + snap-to-edges.
- **`cv2.fillPoly` ne respecte pas even-odd** (régions annulaires) → rasterisation pixel-perfect via masque booléen.
- **Palette crayons saturés vs pastels ERNIE → ΔE médian ~44** ; solution stylisée. Copy UX « 6 crayons pour s'exprimer ».
- **Crayon Prune jamais matché** (violets pastels proches d'Océan). Backlog b9 + b5 (crayon Noir). **« Variante colorable » = présence d'un `extract_preset`** (le moteur décoloriage ignore le nom du preset). Masque traits G2 = ground truth ink/shading.

### Pipeline / DB / Git
- **NULL-safe avant tri** : `int(w) if w is not None else 0`. **DuckDB FK eager** (legacy) : DELETE hors BEGIN. **Tests SQLite-portables**. **Singleton `start.py`** via `logs/start.lock`.
- **Working tree = backlog accumulé sur plusieurs cycles.** 2026-06-10 : écosystème pastel/vectorize/playground + décoloriage untracked ; fichiers partagés (`main.py`, `admin.html`) entrelacent plusieurs features → commit isolé bloqué sans `git add -p`. Règle : committer au fil de l'eau ; sinon commit thématique large par chemins explicites (jamais `git add -A`).
- **Force-push légitime** via `--force-with-lease` + amend (pas `--force` brut).

### Process / Coordination cross-repo
- **Ne pas se fier aux rapports cross-repo sans vérifier l'état réel** (`ls`/`grep` le repo cible). **Doc ≠ code : divergence silencieuse** (cas UC1 2026-05-27 ; vérifier le code réel avant doc opérationnelle).
- **Sync destructif vs ADD-ONLY = arbitrage par type** (Categories strict, Posts/Themes ADD-ONLY). **Registry wins acté AVANT divergence**. **Idempotence R2 = `master-md5`** (ETag fragile).
- **Patches en chaîne = confusion** (mini-brief unique post-livraison). **Briefs ≤1h30 + vérif état réel en tête**. **Mesurer chars Unicode d'un seed avant commit** (AR ~50 %). **Avant drop theme/category : grep cross-ref** côté rimalab.
- **Migration doc cross-repo (Pattern A) demande Étape 3 nettoyage explicite** — sinon 2 versions divergent. **Cas vécu 2026-06-10 : la copie in-repo non supprimée a fait charger une mémoire périmée → toujours lire le canonique (alwanbooks-docs).**
- **Obsidian `[[wikilinks]]` OFF** pour cohérence GitHub.

## Top 5 rapports à charger en priorité

1. **`reports/2026-06-10_poc-decoloriage-SYNTHESE.md`** — pipeline décoloriage validé G0→G5 + batch. Référence avant tout chantier coloriage interactif.
2. **`architecture/2026-06-10_plan-migration-decoloriage-prod.md`** — roadmap migration POC→prod (Phases 1-5 + dépendance cross-repo). Tracker vivant.
3. **`architecture/workflow-pipeline-multi-sites.md`** — référence git-as-CMS multi-sites.
4. **`architecture/exploiter-plateforme-comme-cms.md`** — manuel d'exploitation 10 UCs (toute opération réelle plateforme).
5. **`notes/2026-05-26_point-fonctionnel-cadrage-plateforme.md`** — cadrage fonctionnel + questions ouvertes à arbitrer.

## Notes pour le prochain cycle

- **POC 2 décoloriage-styles — EXPLORATION capitalisée T20 (2026-06-12)** : pivot vers styles **coloriables par construction**. **Architecture 2-modes actée** : *décoloriage* (image colorée → régions+encre, T19) pour pastel/kawaii/low-poly ; ***lineart-fill*** (line-art N&B → composantes connexes du blanc, `poc/decoloriage_styles/lineart_fill_v2.py`) pour mandala/zentangle/zellige/mosaïque + **tout line-art** (dont les prompts lineart d'origine). lineart-fill **production-ready** : expansion Voronoi des cellules sous le trait → couverture 100 % / **0 halo** ; encre **vectorisée VTracer** → traits lisses. Insight produit : **ne pas forcer la taxonomie sujet** sur les styles ornementaux (sujet natif — cf. `feedback_styles_ornementaux_sujet_natif`). Pistes catalogue adulte : 4 styles ornementaux natifs (zellige = différenciant marque Alwan ; mandala = standard marché) + low-poly/kawaii (mode décoloriage chromakey). Outils S2 dispo (SAM 2, informative-drawings contour) pour styles durs si retour. Capitalisé `references/techniques.md` §T20 + `poc/decoloriage_styles/EXPLORATION_LOG.md`. **Backlog prod T20 (c1-c6)** : intégrer lineart-fill = 3e moteur worker · alléger encre · appliquer aux lineart d'origine · re-gen artefacts · stained_glass/mosaïque colorée via chromakey/SAM 2 · figer variantes prod + décision catalogue. Rien figé prod.
- **Migration décoloriage interne TERMINÉE + PR #2 mergée sur main** (`589b12c`). Phase 4b (cross-repo) : brief dédié pour conso SVG par le colorieur rimalab (reco convention d'URL `{ASSETS}/coloriages/svg/{slug}.svg`, fallback PNG si 404) — couplé à l'**artefact Claude Fable** (pixel→vectoriel) attendu.
- **Phase 5** : déprécier extract_palette après N lots prod (MAJ CLAUDE.md + mémoire project_extract_palette_prod).
- **Cutover RÉACTIVÉ** : cadrage le 2026-06-16, cutover cible ~2026-07-10. Phase 6 doc rimalab ~2026-07-03.
- **Hygiène / dette prioritaire** : (1) **Étape 3** — supprimer la copie mémoire in-repo + repointer les skills sur alwanbooks-docs (sinon re-chargement périmé) ; (2) **réconcilier le fil 2026-05-30/06-01** (workflow unifié Phase A.1 + ADR multi-variantes) dans cette mémoire ; (3) committer backlog multi-sites restant ; (4) corriger `.gitignore` + supprimer junk.
- **Cadrage fonctionnel** : 6 questions toujours en attente d'arbitrage utilisateur (`notes/2026-05-26_point-fonctionnel-cadrage-plateforme.md`).
- **Vérifs prod décoloriage** : coût ~2,2 s/image en lot ; masque traits G2 = ground truth ink/shading.
- **Backlog passif** : Vague 2 MEP v0 · POC birds 14 leaves · Plans B+C SubjectQualifier · Niveau 2 multi-sites · enrichir themes_registry · étoffer letters_arabic.
