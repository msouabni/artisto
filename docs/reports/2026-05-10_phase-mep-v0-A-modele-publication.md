# Phase MEP-v0/A — Modèle publication
Date : 2026-05-10

## Contexte

Implémentation stricte du brief `docs/architect/briefs/2026-05-10_brief-mep-v0-A-modele-publication.md`
sur la branche `feat/mep-v0-A-modele-publication`. Couche publication
i18n ajoutée au modèle (1 image × 3 locales = 3 lignes), avec helpers Python
internes pour les transitions de statut (`pending → ready_for_export →
published_alwan`). Aucun endpoint HTTP nouveau ni modifié. Périmètre orthogonal
aux briefs B (génération i18n) et C (export disque + slugs).

## Modifications

| Fichier | Statut | LOC | Rôle |
|---|---|---|---|
| `alembic/versions/0007_image_publication.py` | NEW | 84 | Migration Postgres (CREATE TABLE + index + FK CASCADE + UNIQUE) |
| `src/api/models.py` | MODIF (+48 LOC) | 311 | Ajout du modèle SQLAlchemy `ImagePublication` (autres modèles non touchés) |
| `src/api/image_publication.py` | NEW | 239 | Module dédié : 3 helpers Python purs (`mark_image_approved`, `mark_image_ready_for_export`, `mark_image_published_alwan`) + constante `PUBLICATION_LOCALES` |
| `tests/test_image_publication.py` | NEW | 482 | 24 tests : schéma, contraintes, FK CASCADE, 3 helpers (transitions + idempotence + ValueError) |
| `docs/reports/2026-05-10_phase-mep-v0-A-modele-publication.md` | NEW | — | Ce rapport |

Choix d'implémentation : helpers placés dans un **nouveau module** `src/api/image_publication.py`
plutôt que dans `src/api/routes/images.py` (option offerte par la whitelist du
brief). Avantages : (1) module dédié, plus orthogonal aux briefs B/C qui
toucheront probablement `images.py` ou `export.py` ; (2) pas de pollution de
routes.images avec du code qui n'est pas un endpoint ; (3) imports plus
clairs côté futur worker post-v0.

## Tests

### Suite ciblée (24 tests, nouveau fichier)

```
tests/test_image_publication.py::TestSchemaAndConstraints (4 tests)
  - test_3_locales_par_image                         PASSED
  - test_unicite_locale_post_slug                    PASSED
  - test_meme_post_slug_locales_differentes_ok       PASSED
  - test_fk_cascade_delete_image                     PASSED

tests/test_image_publication.py::TestMarkImageApproved (5 tests)
  - test_transition_generated_vers_approved          PASSED
  - test_idempotence_noop_si_deja_approved           PASSED
  - test_image_inconnue_leve_value_error             PASSED
  - test_statut_invalide_leve_value_error            PASSED
  - test_statut_scheduled_leve_value_error           PASSED

tests/test_image_publication.py::TestMarkImageReadyForExport (9 tests)
  - test_transition_si_3_locales_pretes              PASSED
  - test_value_error_si_une_locale_manquante         PASSED
  - test_value_error_si_title_vide                   PASSED
  - test_value_error_si_description_null             PASSED
  - test_value_error_si_post_slug_null               PASSED
  - test_value_error_si_r2_slug_null                 PASSED
  - test_idempotence_noop_si_deja_ready              PASSED
  - test_value_error_si_statut_invalide              PASSED
  - test_transition_partielle_si_certaines_deja_ready PASSED

tests/test_image_publication.py::TestMarkImagePublishedAlwan (6 tests)
  - test_transition_met_external_url_et_published_at PASSED
  - test_idempotence_si_deja_published               PASSED
  - test_value_error_locale_inconnue                 PASSED
  - test_value_error_external_url_vide               PASSED
  - test_value_error_ligne_absente                   PASSED
  - test_value_error_transition_invalide_depuis_pending PASSED

24 passed in 0.19s
```

### Suite complète (régression baseline)

```
pytest --ignore=tests/test_content_generator.py -q --tb=no
5 failed, 212 passed in 2.86s
```

Baseline avant intervention : `5 failed, 188 passed`. Delta : **+24 nouveaux
tests passants, 0 régression**. Les 5 échecs préexistants sont les tests
ERNIE / sidecar (`test_bulk_generation_jobs.py`, `test_create_image_job_workflow.py`,
`test_workflow_template_sidecar.py`) explicitement signalés comme non-bloquants
dans le brief.

## Points d'attention

- **FK CASCADE côté SQLite** : SQLite n'applique pas `ON DELETE CASCADE` sans
  `PRAGMA foreign_keys=ON`. Le test `test_fk_cascade_delete_image` utilise une
  fixture locale (`conn_fk`) qui active le PRAGMA via event listener
  `connect`. Côté Postgres (prod), la cascade est nativement appliquée. La
  cascade est portée par la migration (FK explicite avec `ondelete="CASCADE"`)
  ET par le modèle SQLAlchemy (cohérent).

- **Unicité `(locale, post_slug)`** : la contrainte SQLite accepte plusieurs
  `NULL` (pas d'erreur sur 3 slugs NULL simultanés). C'est conforme au standard
  SQL et autorise la phase intermédiaire (image créée → slugs calculés plus
  tard par le brief C). L'intégrité finale est garantie par `mark_image_ready_for_export`
  qui exige `post_slug` non NULL avant la transition.

- **Sentinel `_UNSET` dans les tests** : pour passer explicitement `post_slug=None`
  vs. laisser le défaut, j'ai introduit un sentinel local au fichier de test.
  Pas d'impact production.

- **Idempotence** : les 3 helpers retournent un `bool` (`True` = transition
  effectuée, `False` = NoOp). Permet aux callers (script export brief C,
  futur worker) de logger la transition sans relire la base.

- **Helper `mark_image_ready_for_export` — transition partielle** : si certaines
  locales sont déjà `ready_for_export` (ou `published_alwan`) et d'autres
  `pending`, seules les `pending` sont transitionnées. Décision design pour
  rester idempotent sur re-runs partiels. Couvert par
  `test_transition_partielle_si_certaines_deja_ready`.

- **Validation `mark_image_approved`** : volontairement strict (`generated → approved`
  uniquement, NoOp si `approved`). Toute autre transition (depuis `draft`,
  `prompt_ready`, `scheduled`, `rejected`, `published`) lève `ValueError`.
  Conséquence : si un caller veut promouvoir une image déjà `published`, il
  faut un helper séparé (hors scope MEP v0).

- **Pas de mise à jour `image.status`** dans `mark_image_ready_for_export` ni
  dans `mark_image_published_alwan` : ces deux helpers ne modifient que la
  table `image_publication`. La synchronisation `image.status → "published"`
  (ancien état machine décrit dans le README) reste à arbitrer hors-scope
  brief A (probablement brief C ou v0.1).

- **Cross-dialect** : la migration utilise `sa.Text()` partout (compatible
  Postgres et SQLite). Aucun opérateur JSONB. Aucun `RETURNING`. Tests
  in-memory SQLite verts.

- **Aucun endpoint HTTP** : le brief interdisait l'exposition d'endpoints
  publics. Le module `src/api/image_publication.py` n'est importé nulle part
  côté routes ; il n'apparaît pas non plus dans `src/api/main.py`. Ses
  consommateurs futurs seront le script `scripts/export_mep_v0.py` (brief C)
  et un éventuel worker post-v0.

## Décision / Action suivante

- **Brief B** peut consommer le modèle `ImagePublication` pour générer les
  3 lignes i18n par image (insertion via SQL ou ORM). Le helper
  `mark_image_ready_for_export` vérifie les pré-requis et donne un retour
  clair sur les champs manquants — utile pour la regen loop côté brief B.

- **Brief C** peut consommer les 3 helpers pour les transitions de statut
  côté script export (`mark_image_approved` au début, puis génération des
  slugs + `mark_image_ready_for_export`, puis `mark_image_published_alwan`
  par locale au moment du push vers Alwan).

- **Post-v0** : à capitaliser après tests live, possible besoin de :
  (a) un endpoint HTTP `POST /api/images/{id}/approve` qui wrappe le helper ;
  (b) un job_type `image_publication` (capitalisation explicite après volume) ;
  (c) un helper inverse `mark_image_rejected` / `mark_image_unpublished` si
  besoin de rétroaction.

- **Whitelist respectée** : aucun fichier hors whitelist modifié (vérification
  `git status` : `models.py`, `image_publication.py` (NEW), migration 0007 (NEW),
  test (NEW), rapport (NEW) — c'est tout). `images.py`, `prompt_generator.py`,
  `annotation_vocab.py`, `benchmark-annotator.html`, `routes/{benchmark,review,jobs}.py`,
  `workers/*`, `data/prompt_generator/*`, `data/<dir>/annotations.json` non
  touchés.
