# Brief d'exécution — Phase 4 : Export du SVG bicouche vers R2 (ADD-ONLY)
Date : 2026-06-10
Destinataire : Claude Code d'exécution
Plan parent : `docs/architect/2026-06-10_plan-migration-decoloriage-prod.md`
Pré-requis : Phase 2 (backend) PASS — l'artefact `coloring_svg` est produit dans `ImageOutput.model_config.coloring_svg_path`.

## Contexte

`scripts/alwanbooks_pipeline.py` publie, par leaf, 4 variantes d'asset sur Cloudflare R2 (`coloriages/png|webp|thumbs|pdf/{slug}.*`) + des posts Astro `.md` par locale. **Il ne véhicule pas le SVG coloriage.** Phase 4 ajoute le **SVG bicouche décoloriage** (produit en Phase 2) comme **5e asset R2**, poussé en **ADD-ONLY idempotent**, par convention d'URL — **sans modifier le frontmatter des posts ni le schéma Astro côté rimalab** (cette intégration site est une coordination cross-repo distincte, hors périmètre, à remonter comme dépendance).

État réel à connaître AVANT d'éditer (lis en entier) :
- `scripts/alwanbooks_pipeline.py` (pipeline complet : lecture manifest, résolution master PNG, génération + upload R2 des 4 variantes, conventions de clés, modes `--mock`/`--no-git-push`)
- le module d'export sous-jacent (résolution master PNG, ex. `export_mep_v0._resolve_master_png` — repérer le fichier réel) et la structure du `manifest.json`
- le helper d'upload R2 (idempotence **custom metadata `master-md5`** — cf. décision 2026-05-25, ETag legacy fallback) : RÉUTILISER ce helper, ne pas réinventer l'idempotence
- `src/services/coloring_storage.py` (où vit `coloring_svg`) et la forme de `ImageOutput.model_config` (`coloring_svg_path`, `coloring_engine`) — cf. `tests/test_decoloriage_phase2.py`
- `data/destination_sites.json` (registry sites)

## Objectif

Pour chaque leaf publiable disposant d'un `coloring_svg` décoloriage, pousser ce SVG sur R2 sous une **clé conventionnelle** (`coloriages/svg/{slug}.svg` — aligne-toi sur le nommage existant des 4 variantes), en **ADD-ONLY + idempotent** (même mécanique `master-md5` que les autres assets), de sorte que le SVG soit accessible à une URL prévisible (`{CLOUDFLARE_R2_PUBLIC_BASE}/coloriages/svg/{slug}.svg`). **Aucun changement de frontmatter / build Astro.**

## Décisions de cadrage à respecter
- **ADD-ONLY** : ne (re)pousse que les SVG absents ou réellement modifiés (idempotence `master-md5`). Jamais d'overwrite aveugle. Override explicite seulement si un flag `--regen`/équivalent existant le couvre.
- **D1/D6** : on consomme l'artefact décoloriage existant (`coloring_svg_path`) ; pas de régénération, pas de DB en écriture, pas de migration.
- **Pas de modification cross-repo** : ni frontmatter des posts, ni `src/content.config.ts` rimalab, ni `ColorierApp.tsx`. La consommation côté site = dépendance à remonter, hors périmètre.
- Conserver `--mock` et `--no-git-push` fonctionnels (le SVG suit le même régime que les autres assets : pas d'upload réel en `--mock`).

## Périmètre

### DANS le périmètre
1. **Résolution du SVG coloriage par leaf** : à l'image de la résolution du master PNG, localiser le `coloring_svg` (depuis `model_config.coloring_svg_path`, ou la convention `coloring_storage` si le manifest porte déjà l'info). Si absent pour un leaf → **skip ce SVG proprement** (log + compteur), ne pas faire échouer la publication du leaf.
2. **Upload R2 du SVG** sous `coloriages/svg/{slug}.svg` (Content-Type `image/svg+xml`), via le **helper d'upload existant** avec idempotence `master-md5` (md5 du contenu SVG en custom metadata, skip si inchangé). ADD-ONLY.
3. **Comptage / logs** : intégrer le SVG dans les stats de run du pipeline (uploaded / skipped / missing), au même format que les autres variantes.
4. **Tests** (`tests/test_pipeline_svg_export.py` ou extension d'un test pipeline existant), portables SQLite / `--mock` :
   - Un leaf avec `coloring_svg` présent → le SVG est planifié pour upload à la bonne clé `coloriages/svg/{slug}.svg` (vérifiable en mode mock : pas d'upload réel, mais la cible/clé et l'intention sont assertables).
   - Idempotence : 2e passe sur SVG inchangé → skip (md5 identique).
   - Un leaf sans `coloring_svg` → pas d'erreur, SVG compté comme « missing/skip ».
   - `--mock` n'effectue aucun appel R2 réel.
5. **Lancer** `pytest` sur les tests pipeline (nouveau + existants) et garder la sortie. Si possible, un **smoke `--mock`** du pipeline sur le manifest courant pour prouver l'intégration sans toucher R2.

### HORS périmètre (ne pas faire)
- Frontmatter des posts / schéma Astro / build rimalab / `ColorierApp.tsx` (coordination cross-repo distincte).
- Génération/régénération d'images ou de SVG (on consomme l'existant).
- PDF/WebP/PNG (inchangés). Cutover, sync-themes/categories (autres verbes).
- Push git réel, migration Alembic.

## Critères d'acceptation
1. Le pipeline planifie/pousse le `coloring_svg` sous `coloriages/svg/{slug}.svg` (Content-Type SVG) via le helper R2 existant, en ADD-ONLY idempotent (`master-md5`).
2. Leaf sans SVG → skip propre (log + compteur), publication du leaf inchangée ; `--mock` n'appelle pas R2.
3. Idempotence prouvée par test (2e passe SVG inchangé → skip).
4. `pytest` vert (nouveau test + non-régression pipeline existants), sans Postgres ; smoke `--mock` OK si faisable.
5. Aucune modif cross-repo (frontmatter/schéma/site), aucune migration, autres assets inchangés.
6. **Rapport** `docs/reports/2026-06-10_phase4-export-svg-bicouche-r2.md` (Contexte / Résultats / Points d'attention / Décision) : point d'intégration (fichier:lignes), convention de clé R2 + URL publique résultante, mécanique d'idempotence réutilisée, sortie pytest/smoke, ET une section **« Dépendance cross-repo à remonter »** décrivant précisément ce qu'il faudra faire côté rimalab pour que le site consomme ce SVG (champ frontmatter ou convention d'URL, impact schéma Zod). Verdict explicite : **Phase 4 PASS** / **blocage** / **pivot**.

## Conventions (rappel projet)
- Reporting obligatoire AVANT de clore.
- `PYTHONPATH=src`. Tests portables SQLite, jamais Postgres. Placeholders SQL `?` via `DBConnAdapter` si tu touches du SQL.
- Réutiliser l'idempotence `master-md5` existante (ne pas réinventer). NULL-safe + types natifs.
- `--mock` / `--no-git-push` doivent rester fonctionnels et sûrs.
- Pas de `git commit`/`push`, pas de migration sauf demande explicite.
- Vérifier l'état réel du pipeline + du helper R2 AVANT d'éditer ; ne pas inventer la structure du manifest.

## Reporting attendu
Fichier `docs/reports/2026-06-10_phase4-export-svg-bicouche-r2.md`. Le fichier est le livrable principal. Conclure : **Phase 4 PASS** (SVG exporté en R2 ADD-ONLY → reste la dépendance cross-repo site) / **blocage : <quoi/où>** / **pivot : <ajustement>**.
Ton message final DOIT contenir : verdict, chemin du rapport, résultat pytest/smoke, point d'intégration (fichier:lignes), convention de clé R2, liste des fichiers créés/modifiés, et le résumé de la dépendance cross-repo.
