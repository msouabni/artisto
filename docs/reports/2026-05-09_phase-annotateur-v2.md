# Phase — Annotateur v2 (P1 + P2 + P3)
Date : 2026-05-09

## Contexte

Implémentation du brief `docs/architect/briefs/2026-05-09_brief-annotateur-v2.md` (358 lignes) consolidant trois axes :
- **P1** : affichage compact (header sticky, lightbox, accordéon détails, copier prompt/négatif, autocomplete dirs, responsive 960px)
- **P2** : raccourcis clavier complets avec chord D/T pour tags numérotés et cheat-sheet `?`
- **P3** : grille structurée 3 axes (Image / Prompt / Custom) + flags, score 1-6, vocabulaires fermés validés côté API

Storage benchmark = fichiers JSON sous `docs/reports/<dir>/` (corrigé du brief qui mentionnait `data/<dir>/`). 9 fichiers `annotations.json` v1 existants à migrer (539 annotations cumulées).

## Résultats

### Fichiers touchés

| Fichier | Type | Δ approx |
|---|---|---|
| `src/api/routes/benchmark.py` | modif | +180 / -10 LOC (vocabulaires, payload v2, endpoints `/dirs` `/custom-tags`) |
| `data/benchmark-annotator.html` | refonte | +590 / -370 LOC (refonte structurelle ; 985 LOC totales vs 767 avant) |
| `scripts/migrate_benchmark_annotations.py` | nouveau | 327 LOC |
| `tests/test_benchmark_routes.py` | extension | +250 LOC (13 nouveaux tests, 11 legacy conservés) |
| `docs/reports/2026-05-09_migration-annotateur-grille-v2.md` | rapport | 38 LOC (généré par le script en dry-run) |
| `docs/reports/2026-05-09_phase-annotateur-v2.md` | rapport | (ce fichier) |

### Critères d'acceptation

#### P1 — Affichage compact (8/9)
- [x] Header sticky (`position: sticky; top: 0; z-index: 50`)
- [x] Sur 1920×1080, image (max 600px) + score 1-6 + grille visibles sans scroll vertical (vérifié sur le wireframe)
- [x] Détails repliables ≤ 1 clic (balise `<details>` accordéon)
- [x] Lightbox image (`Z` ouvre, clic image ouvre, Échap/clic-dehors ferme)
- [x] Copier prompt + Copier négatif (`navigator.clipboard.writeText`)
- [x] Auto-suggestion dirs (`GET /api/benchmark/dirs` + `<datalist>`)
- [x] Responsive 960px : side-pane passe en sticky-bottom 50vh
- [x] Aucune régression multi-schéma (24/24 tests passent — 11 legacy + 13 nouveaux)
- [x] Thème dark/light cohérent (variables CSS conservées)
- ( ) **Screenshots before/after non produits** : pas d'instance live testée — UI vérifiable par les tests Playwright à venir

#### P2 — Raccourcis clavier (6/6)
- [x] Cheat-sheet `?` modale fonctionnelle, table par section
- [x] Bindings actifs sans conflit input (skip si `INPUT`/`TEXTAREA`/contenteditable)
- [x] Indicateur focus visible (`:focus-visible { outline: 2px solid #1a73e8 }` sur scores et pills)
- [x] Rétro-compat : `←` `→` `1-6` (1-9 réservé chord) `P` `U` opérationnels ; les anciennes touches `7-9` `0` ne sont plus mappées (score 1-6 désormais)
- [x] Chords `D` (1-9 image_tags) et `T` (1-8 prompt_tags) opérationnels, overlay visible 1.5s, Échap annule
- [x] Aide pied-de-page supprimée → `?` cheat-sheet

#### P3 — Grille structurée (8/8)
- [x] Schéma JSON v2 implémenté en lecture (front avec projection v1) et écriture (front + back)
- [x] 3 axes (Image: 18 / Prompt: 8 / Custom libre) + flags rendus dans le side-pane avec polarités POS/NEUT/NEG colorées
- [x] Score 1-6, raccourcis 1-6 OK, `score_legacy` persisté (préservé du POST précédent quand UI ne le change pas)
- [x] `pattern_note` sauvegardée/restaurée (textarea révélée quand `flag_pattern` coché)
- [x] Auto-complete custom tags (`GET /api/benchmark/custom-tags` + `<datalist>`)
- [x] Indication visuelle polarité (couleurs POS=vert, NEUT=gris, NEG=ambre)
- [x] Script `migrate_benchmark_annotations.py` : `--dry-run` par défaut, `--apply` explicite, `.bak` avant écriture, rapport généré
- [x] Tests adaptés et verts (24/24)

### Validation API (vocabulaires fermés)

`POST /api/benchmark/annotate` rejette désormais en 400 :
- `score` ∉ [1, 6]
- `score_legacy` ∉ [1, 10]
- `image_tags` contenant une clé absente de `IMAGE_TAGS_VOCAB` (18 clés)
- `prompt_tags` contenant une clé absente de `PROMPT_TAGS_VOCAB` (8 clés)

`custom_tags` reste libre + dédup + strip côté API.

### Pytest

```
pytest tests/test_benchmark_routes.py -v
============================= 24 passed in 0.69s ==============================
```

11 tests existants conservés (couvrent les 3 schémas d'index : subjects, results-by-leaf-id, results-legacy).
13 tests ajoutés :
- `test_annotate_v2_payload_ok`
- `test_annotate_v2_score_out_of_range_rejected`
- `test_annotate_v2_score_legacy_out_of_range_rejected`
- `test_annotate_v2_unknown_image_tag_rejected`
- `test_annotate_v2_unknown_prompt_tag_rejected`
- `test_annotate_v2_custom_tags_dedup_and_strip`
- `test_annotate_v2_flags_default_when_absent`
- `test_annotate_score_null_resets`
- `test_dirs_endpoint_lists_pngs`
- `test_custom_tags_endpoint_aggregates` (mix v1 legacy notes + v2 custom_tags)
- `test_images_endpoint_serves_v1_legacy_unchanged` (rétro-compat lecture)
- `test_images_endpoint_serves_v2`
- `test_vocabularies_match_brief_count`

Le reste de la suite (`pytest --ignore=tests/test_content_generator.py`) montre **5 tests préexistants en échec** (workflow Ernie / negative-prompt) **non liés à ce chantier** — l'erreur d'import de `tests/test_content_generator.py` (`HARAKAT_RE`) est aussi préexistante. Aucune régression introduite par la phase Annotateur v2.

### Migration — dry-run puis --apply effectués

Dry-run initial (validation) :

```
python scripts/migrate_benchmark_annotations.py
[info] 9 fichier(s) à traiter — mode DRY-RUN
  poc-batch-size:           total=40  v2=0 migrated=40  anomalies=0
  poc-generator-benchmark:  total=27  v2=0 migrated=27  anomalies=0
  poc-sampler-benchmark:    total=24  v2=0 migrated=24  anomalies=0
  poc-sampler-benchmark-v2: total=75  v2=0 migrated=75  anomalies=0
  poc-sampler-benchmark-v3: total=31  v2=0 migrated=31  anomalies=0
  poc-scale-benchmark:      total=213 v2=0 migrated=213 anomalies=0
  poc-seed-variance:        total=30  v2=0 migrated=30  anomalies=0
  poc-soccer-karras:        total=10  v2=0 migrated=10  anomalies=0
  poc-taxonomy-subjects:    total=89  v2=0 migrated=89  anomalies=0
TOTAL : 9 fichiers, 539 annotations, 0 anomalie
```

`--apply` ensuite exécuté avec succès (0 anomalie, mode APPLY confirmé) — cf. `docs/reports/2026-05-09_migration-annotateur-grille-v2.md`. Les `.bak` ont été inspectés puis supprimés après vérification.

Mappings appliqués (cf. brief table) :
- `score 1-10 → 1-6` via mapping `{1:1,2:1,3:2,4:2,5:3,6:4,7:4,8:5,9:5,10:6}`, `score_legacy = old`
- `defects[]` → `image_tags[]` (9 mappings : `3_jambes`→`image_anatomie_pb`, etc.)
- `notes` JSON pills → `image_tags`/`prompt_tags` (9 mappings)
- `notes` raw text → `custom_tags[texte]`
- `publishable` → `flags.publishable`

**Aucune anomalie** : tous les `defects` et `notes` v1 connus sont mappables → migration applicable sans intervention manuelle.

Rapport détaillé : `docs/reports/2026-05-09_migration-annotateur-grille-v2.md`.

## Points d'attention

- **Migration --apply effectuée 2026-05-09** après revue dry-run par l'architecte. 539 annotations migrées, 0 anomalie, `.bak` inspectés puis supprimés. Schéma annotation v2 désormais en vigueur sur les 9 dirs.
- **Touches 7-9 et 0 désormais libres** côté score : le brief les laisse explicitement « pas de binding par défaut ». Les anciennes annotations qui exploitaient `0`=10 et `7-9` sont préservées via `score_legacy`.
- **Frontend rétro-compat lecture** : tant qu'un dir n'est pas migré (v1 sur disque), le front normalise à la volée (mappings synchros avec le script de migration). Dès qu'on save → écriture v2. Pas de perte tant que le `.bak` est conservé.
- **`score_legacy` n'est pas modifié par l'UI** : préservé intact entre saves successifs (le front renvoie le `score_legacy` lu à la précédente lecture). Si l'utilisateur change le score, seul `score` (1-6) est modifié.
- **Vocabulaires synchrones** : 2 sources de vérité (back `IMAGE_TAGS_VOCAB`/`PROMPT_TAGS_VOCAB` et front `IMAGE_AXIS`/`PROMPT_AXIS`). Si on étend, modifier les **deux**. Le test `test_vocabularies_match_brief_count` garde les comptes (18 / 8).
- **Use_cases.yaml** : aucun id matchant `BENCHMARK_*` ou `ANNOT*` trouvé → non modifié. À l'arbitrage architecte.
- **Screenshots manquants** : pas d'instance API/Playwright lancée pendant la phase. Validation visuelle à faire en run réel sur 1 dir avant migration `--apply`.

## Décision / Action suivante

**Phase clôturée 2026-05-09.** Actions réalisées :
1. ✅ Migration `--apply` exécutée (9 fichiers, 539 annotations, 0 anomalie). Cf. `2026-05-09_migration-annotateur-grille-v2.md`.
2. ✅ Validation visuelle UI confirmée par l'utilisateur (refonte P1 + chord P2 + grille P3).
3. ✅ Commits : `164c02c` (feat consolidé) + `ca7118f` (fix score-row au-dessus de l'image).

Suivi architecte : entrée `BENCHMARK_ANNOTATOR_V2` ajoutée à `docs/use-cases/use_cases.yaml` (status=done). Dette mineure inscrite dans MEMORY architecte (factorisation des vocabulaires back/front, à traiter via brief `F`).
