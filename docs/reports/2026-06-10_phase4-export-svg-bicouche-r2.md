# Phase 4 — Export du SVG bicouche décoloriage vers R2 (ADD-ONLY)
Date : 2026-06-10
Plan parent : `docs/architect/2026-06-10_plan-migration-decoloriage-prod.md`
Brief : `docs/architect/briefs/2026-06-10_brief-phase4-export-svg-bicouche-r2.md`
Pré-requis : Phase 2 (backend) PASS — l'artefact `coloring_svg` existe sur disque.

## Contexte

`scripts/alwanbooks_pipeline.py` poussait, par leaf, 4 variantes d'asset sur
Cloudflare R2 (`coloriages/png|webp|thumbs|pdf/{slug}.*`). Phase 4 ajoute le
**SVG bicouche décoloriage** (produit en Phase 2, chemin reflété dans
`ImageOutput.model_config.coloring_svg_path`) comme **5e asset R2**, poussé en
**ADD-ONLY idempotent**, par convention d'URL prévisible — **sans toucher au
frontmatter des posts, au schéma Astro rimalab, ni au build/ColorierApp** (la
consommation côté site = dépendance cross-repo distincte, cf. dernière section).

On **consomme** l'artefact existant : aucune régénération, aucune écriture DB,
aucune migration. Les 4 autres assets (PNG/WebP/Thumb/PDF) sont inchangés.

## Résultats

### Point d'intégration (fichier:lignes)

Tout est dans `scripts/alwanbooks_pipeline.py` :

| Élément | Lignes (approx.) |
|---|---|
| Constantes `R2_SVG_PATH` + `R2_SVG_CONTENT_TYPE` | ~116-120 (après `R2_PATHS`) |
| Champs `LeafResult` : `svg_uploaded`/`svg_skipped`/`svg_missing` | dans `@dataclass LeafResult` |
| Compteurs `PipelineRunSummary` : `svg_uploaded`/`svg_skipped`/`svg_missing` | dans `@dataclass PipelineRunSummary` |
| `_resolve_coloring_svg(leaf_id, base_dir)` | après `_upload_variants_mock` |
| `_upload_svg_real(r2, slug, svg_body)` | idem (idempotence `master-md5`) |
| `_upload_svg_mock(slug, svg_body)` | idem (écrit `r2_simulated/`) |
| **Branche 3bis** dans `run_pipeline` (après upload des 4 variantes, avant la boucle posts) | bloc commenté `# 3bis. SVG bicouche décoloriage (Phase 4)` |
| Stats : `write_report` / `_print_summary` / `print_deployment_recap` + appel `main` | sections rapport/recap |

Le SVG est traité **après** l'upload des 4 variantes et **avant** l'écriture des
posts. C'est un étage **best-effort par leaf** : un échec d'upload SVG est loggé
(`logger.warning`) et compté, mais **ne fait pas échouer le leaf** (les 4
variantes sont déjà poussées, le post reste publiable). Critère 2 respecté.

### Résolution du SVG par leaf

`_resolve_coloring_svg(leaf_id)` réutilise la convention `coloring_storage` :
il scanne les variantes existantes (`list_existing_variants`) et retourne le
premier `coloring_svg` présent sur disque
(`data/generated/{leaf_id}__{variant}_coloriage.svg`) — c'est exactement le
fichier pointé par `model_config.coloring_svg_path`. Absent → `None` →
`svg_missing` (skip propre, log + compteur). Un `leaf_id` non conforme ne lève
jamais : `None` (défensif, publication non cassée).

### Convention de clé R2 + URL publique

- **Clé R2** : `coloriages/svg/{slug}.svg` (alignée sur les 4 variantes
  `coloriages/<kind>/{slug}.<ext>`).
- **Content-Type** : `image/svg+xml`.
- **URL publique résultante** : `{CLOUDFLARE_R2_PUBLIC_BASE}/coloriages/svg/{slug}.svg`
  (ex. `https://assets.alwanbooks.com/coloriages/svg/polar-bear-on-ice.svg`).

### Idempotence réutilisée (`master-md5`)

`_upload_svg_real` réutilise la mécanique custom-metadata `master-md5` des 4
variantes (`_upload_variants_real`, décision 2026-05-25). Le SVG n'ayant pas de
PNG master dont dériver le hash, l'empreinte d'idempotence est le **md5 du
contenu SVG lui-même**, posé en metadata `master-md5` au PUT :
- objet présent + `master-md5` == md5(svg) → **skip** (SVG inchangé) ;
- objet présent + `master-md5` != → **upload** (SVG régénéré) ;
- objet présent **sans** `master-md5` (legacy) → fallback ETag == md5(svg).

ADD-ONLY : un SVG inchangé n'est jamais re-poussé. Aucune nouvelle clé/secret,
aucun helper d'idempotence réinventé.

### `--mock` / `--no-git-push`

- `--mock` : `_upload_svg_mock` écrit dans
  `data/export/r2_simulated/coloriages/svg/{slug}.svg`. **Aucun appel réseau**
  (le client R2 n'est même pas construit en mock — prouvé par
  `test_run_pipeline_mock_no_real_r2_client`).
- `--no-git-push` : inchangé (le SVG suit le régime R2 réel comme les 4
  variantes ; pas de push git).

### Stats de run (même format que les variantes)

Ajout `svg uploaded / skipped (master-md5) / missing` dans : `write_report`,
`_print_summary`, et la ligne `R2 svg décoloriage:` de `print_deployment_recap`.

## Sortie pytest / smoke

### Tests Phase 4 + non-régression pipeline

```
$ python -m pytest tests/test_pipeline_svg_export.py tests/test_pipeline_multi_variantes.py \
    tests/test_pipeline_addonly.py tests/test_alwanbooks_pipeline.py \
    tests/test_pipeline_autotag_themes.py -q
61 passed in 0.77s

$ python -m pytest tests/test_pipeline_cutover.py tests/test_pipeline_bot_push_integration.py \
    tests/test_pipeline_push_branch.py -q
16 passed in 0.13s
```

`tests/test_pipeline_svg_export.py` (14 tests) couvre : résolution présent/absent/
dossier-vide/leaf-invalide ; clé R2 + Content-Type ; upload mock → `r2_simulated`
à la bonne clé ; upload réel ADD-ONLY (PUT au 1er passage) ; **idempotence
2e passe SVG inchangé → skip** ; contenu changé → re-upload ; fallback ETag
legacy ; intégration `run_pipeline --mock` (SVG présent → uploaded ; SVG absent
→ missing + leaf OK ; mock = aucun client R2).

### Suite complète (hors module pré-cassé)

```
$ python -m pytest tests/ -q --ignore=tests/test_content_generator.py
886 passed in 16.55s
```

`tests/test_content_generator.py` échoue à la **collection**
(`ImportError: HARAKAT_RE` absent de `services.ollama_json`) — **pré-existant**
(noté en Phase 1 et 2), module non touché par cette phase.

### Smoke `--mock` réel (leaf `polar_bear_on_ice`)

```
$ python scripts/alwanbooks_pipeline.py --mock --leaf-id polar_bear_on_ice --rimalab-path <tmp>
[svg] leaf=polar_bear_on_ice uploaded → coloriages/svg/polar-bear-on-ice.svg
[MOCK] leaves=1 ok=1 failed=0 no_master=0
  variants uploaded=4 skipped=0 posts=3
  svg uploaded=1 skipped=0 missing=0
R2 svg décoloriage: 1 uploadés / 0 skipped (master-md5) / 0 missing
```

Le SVG bicouche réel (26 KB,
`data/generated/polar_bear_on_ice__pastel_chromakey_coloriage.svg`) a été écrit
dans `data/export/r2_simulated/coloriages/svg/polar-bear-on-ice.svg` — intégration
prouvée sans toucher R2.

## Points d'attention

1. **Hash d'idempotence = md5(contenu SVG)**, pas md5 du master PNG. Choix
   assumé : le SVG est dérivé du PNG mais le pipeline ne véhicule pas ce lien
   au moment de l'upload SVG. La metadata reste nommée `master-md5` pour rester
   homogène avec le helper existant et son fallback ETag. Conséquence : si le
   moteur décoloriage régénère un SVG **strictement identique** au précédent, il
   est skippé (souhaité) ; s'il change d'un octet, il est re-poussé (souhaité).
2. **Sélection de variante** : `_resolve_coloring_svg` prend le **premier**
   `coloring_svg` présent (ordre alphabétique des variantes). En prod actuelle
   une seule variante colorable existe par leaf (`pastel_chromakey`). Si
   plusieurs variantes colorables coexistent un jour, il faudra arbitrer
   laquelle exporter (clé R2 unique par slug). À surveiller.
3. **Mock ≠ idempotent** : en `--mock` le SVG est toujours ré-écrit (pas de
   store `master-md5` simulé) — cohérent avec le comportement mock des 4
   variantes. L'idempotence réelle est prouvée par les tests unitaires sur
   `_upload_svg_real` (FakeR2 en mémoire), pas par le mock.
4. **Best-effort** : l'upload SVG n'incrémente pas `leaves_failed` en cas
   d'échec (le leaf reste OK). C'est volontaire (le SVG est un bonus, pas un
   bloqueur de publication). L'erreur est tracée dans `LeafResult.errors` + log.

## Dépendance cross-repo à remonter (rimalab-v2)

Le SVG est désormais **disponible** sur R2 à une URL prévisible, mais **rien ne
le consomme côté site** — c'est hors périmètre Phase 4 (et explicitement
interdit par le brief). Pour que le colorieur charge le SVG vectoriel :

1. **Convention d'URL (recommandé, zéro changement de schéma)** : le front
   dérive l'URL du SVG depuis le slug du post :
   `{PUBLIC_ASSETS_BASE}/coloriages/svg/{slug}.svg`. C'est le chemin le moins
   couplant — aucun champ frontmatter ni migration Zod. `ColorierApp.tsx`
   (ou son successeur Fable) doit : tenter de charger ce SVG bicouche
   (`<g id="fills">` cliquables + `<g id="strokes">`), avec **fallback** sur le
   flux pixel actuel (PNG flood-fill in-app) si le SVG renvoie 404.
2. **Alternative — champ frontmatter explicite** : ajouter dans le bloc
   `variants.<variant>` un champ `coloring_svg_r2` (URL absolue R2) en plus du
   `coloring_svg` actuel (qui pointe vers `/assets/coloriages/...` copié dans le
   repo site). Impact : extension du schéma Zod `variants` côté
   `src/content.config.ts` rimalab (champ optionnel `coloring_svg_r2: z.string().url().optional()`).
   Plus explicite mais couplant (sync schéma + pipeline).
3. **Paradigme front** : passer du flood-fill pixel (PNG) au remplissage
   vectoriel natif (SVG `data-region-id` / `data-color`) est le changement
   structurant identifié au plan parent. C'est le périmètre de l'artefact
   Claude Fable (refonte UX), pas de Phase 4.

**Recommandation** : option 1 (convention d'URL) pour découpler le site du
schéma ; n'ajouter un champ frontmatter (option 2) que si le site a besoin de
distinguer les leaves qui ont un SVG R2 de ceux qui n'en ont pas (sinon le 404
+ fallback suffit). À trancher avec le repo rimalab dans un brief cross-repo.

## Vérification des 6 critères d'acceptation

| # | Critère | Statut |
|---|---|---|
| 1 | SVG poussé sous `coloriages/svg/{slug}.svg` (CT SVG) via helper R2 existant, ADD-ONLY idempotent `master-md5` | ✓ (`_upload_svg_real`, smoke + tests) |
| 2 | Leaf sans SVG → skip propre (log+compteur), publication inchangée ; `--mock` n'appelle pas R2 | ✓ (`svg_missing`, `test_run_pipeline_mock_svg_missing_skips_clean`, `test_run_pipeline_mock_no_real_r2_client`) |
| 3 | Idempotence prouvée par test (2e passe SVG inchangé → skip) | ✓ (`test_upload_svg_real_idempotent_second_pass_skips`) |
| 4 | `pytest` vert (nouveau + non-régression), sans Postgres ; smoke `--mock` OK | ✓ (886 passed ; smoke polar_bear_on_ice) |
| 5 | Aucune modif cross-repo, aucune migration, autres assets inchangés | ✓ (seul `alwanbooks_pipeline.py` + nouveau test modifiés) |
| 6 | Rapport (intégration, clé R2+URL, idempotence, pytest/smoke, dépendance cross-repo) | ✓ (ce document) |

## Fichiers créés / modifiés

Créés :
- `tests/test_pipeline_svg_export.py` — 14 tests portables SQLite / `--mock`.
- `docs/reports/2026-06-10_phase4-export-svg-bicouche-r2.md` — ce rapport.

Modifiés :
- `scripts/alwanbooks_pipeline.py` — constantes `R2_SVG_PATH`/`R2_SVG_CONTENT_TYPE` ;
  champs SVG sur `LeafResult` + `PipelineRunSummary` ; `_resolve_coloring_svg`,
  `_upload_svg_real`, `_upload_svg_mock` ; branche 3bis dans `run_pipeline` ;
  stats SVG dans `write_report`, `_print_summary`, `print_deployment_recap` +
  appel `main`.

## Décision / Verdict

**Phase 4 PASS.**

Le pipeline pousse désormais le SVG bicouche décoloriage comme 5e asset R2 sous
`coloriages/svg/{slug}.svg` (Content-Type `image/svg+xml`), en **ADD-ONLY
idempotent** (`master-md5` sur le contenu SVG), best-effort par leaf (un SVG
absent ou un échec d'upload ne casse pas la publication). `--mock` n'effectue
aucun appel R2 réel. Les 4 autres assets, le frontmatter, le schéma Astro et le
build rimalab sont **inchangés**. 886 tests verts (hors module pré-cassé sans
rapport), smoke `--mock` validé sur un leaf réel.

**Reste la dépendance cross-repo** : faire consommer ce SVG par le colorieur
côté rimalab (convention d'URL recommandée, ou champ frontmatter + extension
Zod) — à traiter dans un brief cross-repo dédié (probablement avec l'artefact
Claude Fable pour le passage pixel → vectoriel).
