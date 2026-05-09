# Phase — Vocabulaires annotateur : source unique back

Date : 2026-05-09
Brief : `docs/architect/briefs/2026-05-09_brief-vocabulaires-source-unique.md`
Cycle : finalisation de la moitié front. La moitié back avait déjà été acquise
le matin même via le greffon prod (commit `8b96c32`, qui a extrait
`IMAGE_TAGS_VOCAB` / `PROMPT_TAGS_VOCAB` dans `src/api/annotation_vocab.py`
partagé entre `benchmark.py` et `review.py`).

## Contexte

Avant ce cycle :
- Les **clés** des tags étaient unifiées côté back via `annotation_vocab.py` (frozensets de 18 + 8 clés).
- Les **labels FR** + **polarités** + **ordre chord** restaient dupliqués dans `data/benchmark-annotator.html` (constantes JS `IMAGE_AXIS` / `PROMPT_AXIS`).
- 2 sources de vérité subsistaient → risque de dérive sur ajout de tag.

Le brief demandait de finir le travail : enrichir le module Python pour
porter aussi les labels et la polarité, exposer l'ensemble via un endpoint
de découverte, et supprimer les hardcodes JS au profit d'un fetch au boot.

## Résultats

### Fichiers touchés

| Fichier | Action | LOC delta (env.) |
|---|---|---|
| `src/api/annotation_vocab.py` | Enrichi : ajout `AxisTag` TypedDict, listes ordonnées `IMAGE_AXIS` (18) et `PROMPT_AXIS` (8) avec `{key, label, polarity}`, frozensets dérivés, assertions garde-fou | +84 / -36 |
| `src/api/routes/benchmark.py` | Import élargi (`IMAGE_AXIS`, `PROMPT_AXIS`) + endpoint `GET /api/benchmark/vocabularies` ajouté | +35 |
| `data/benchmark-annotator.html` | Suppression des constantes `IMAGE_AXIS` / `PROMPT_AXIS` hardcodées (~50 lignes), ajout `fetchVocabularies()` + `showVocabularyError()` + bootstrap async, refonte `buildAxisPills()` pour consommer la liste plate (groupage par polarité local) | +60 / -55 |
| `tests/test_benchmark_routes.py` | Adaptation `test_vocabularies_match_brief_count` + nouveaux tests `test_image_axis_order_preserved`, `test_prompt_axis_order_preserved`, `test_vocabularies_endpoint_returns_axes` | +75 / -3 |
| `docs/architect/MEMORY.md` | Retrait de la dette "Vocabulaires annotateur dupliqués back/front" + ajout d'une ligne dans la table décisions | −1 / +1 |
| `docs/use-cases/use_cases.yaml` | `BENCHMARK_ANNOTATOR_V2.related_files` enrichi de `src/api/annotation_vocab.py`, brief et rapport | +3 / -0 |

### Critères d'acceptation

- [x] Une seule source côté back : `IMAGE_AXIS` / `PROMPT_AXIS` listes ordonnées (`{key, label, polarity}`) dans `annotation_vocab.py`, labels et polarités extraits à l'identique du HTML actuel (pas de dérive cosmétique).
- [x] `IMAGE_TAGS_VOCAB` / `PROMPT_TAGS_VOCAB` dérivés (`frozenset(t["key"] for t in …)`). Les imports existants côté `benchmark.py` et `review.py` restent stables.
- [x] `GET /api/benchmark/vocabularies` retourne le payload spécifié (image_axis 18, prompt_axis 8, score_range, schema_version=2).
- [x] Front : aucune constante de tag codée en dur ne reste. Bootstrap async fetch + fallback bannière rouge "Vocabulaires inaccessibles — recharger la page" en cas d'échec.
- [x] Numérotation chord D 1-9 / T 1-8 cohérente avec l'ordre des listes back (les 9 premières clés de `IMAGE_AXIS` sont celles attendues par l'utilisateur, vérifié par test).
- [x] Test `test_vocabularies_endpoint_returns_axes` ajouté (présence des clés top-level, structure `key/label/polarity`, schema_version, comptes 18+8).
- [x] Test `test_vocabularies_match_brief_count` adapté (source désormais sur `IMAGE_AXIS` / `PROMPT_AXIS`, garde la cohérence avec les frozensets).
- [x] Tests d'ordre `test_image_axis_order_preserved` et `test_prompt_axis_order_preserved` ajoutés (verrouillent la première et la dernière clé + les 9 premières d'image_axis pour détecter une permutation accidentelle).
- [x] Aucun test cassé : 27/27 verts dans `test_benchmark_routes.py`, 21/21 dans `test_review_routes.py` (le module `annotation_vocab` est partagé).

### Résultat pytest

```
tests/test_benchmark_routes.py ..........................  [27/27 passed]
tests/test_review_routes.py   ......................        [21/21 passed]
============================= 48 passed in 1.15s ==============================
```

Aucune régression. Aucun test ignoré.

## Points d'attention

- **Cache front** : le fetch n'a lieu **qu'au boot**, conformément au brief. Pas de polling. `window.__VOCAB__` expose le payload reçu pour debug. Si on veut un hot-reload des vocabulaires, c'est un cycle ultérieur.
- **Ordre = chord numbers** : l'ordre des listes back **est** la numérotation chord D 1-9 / T 1-8. Les tests `test_image_axis_order_preserved` et `test_prompt_axis_order_preserved` verrouillent les premières clés ; toute permutation casse les tests immédiatement. Pas de risque de dérive silencieuse.
- **Fallback fetch** : si `/api/benchmark/vocabularies` répond non-2xx ou si le payload est malformé, une bannière rouge s'affiche en haut de page avec le message "Vocabulaires inaccessibles (<détail>) — recharger la page". Le bootstrap s'arrête là (pas de tentative de rendu sans vocab — l'UI serait inutilisable). C'est un fail-loud volontaire.
- **Mode prod (greffon)** continue de fonctionner identiquement : les pills sont rendues à partir du même vocab fetché, quelle que soit la valeur de `state.mode` (benchmark | production). Le switch de mode ne re-fetch pas le vocab — il est partagé.
- **Compatibilité descendante** : aucun consommateur des `frozenset` n'a été cassé (test `test_vocab_module_is_single_source_of_truth` dans `test_review_routes.py` toujours vert). Les imports `from api.annotation_vocab import IMAGE_TAGS_VOCAB, PROMPT_TAGS_VOCAB` continuent de fonctionner sans modification.
- **Pas de validation manuelle UI** dans ce cycle : l'agent dev n'ouvre pas le navigateur. Le rendu visuel des pills (couleurs, badges 🟢⚪🔴, hints chord 1-9) suit la même logique qu'avant — seule la source de données change. À vérifier rapidement à la prochaine session humaine.

## Décision / Action suivante

- **Cycle clos côté technique.** La duplication back/front est éliminée. Modifier un tag = modifier un seul endroit (`src/api/annotation_vocab.py`).
- **Pas de commit fait** — l'archi review puis commit selon convention.
- **Pas d'arbitrage architecte requis.** Aucune discrepancy détectée pendant l'extraction des labels/polarités du HTML : l'ordre POS → NEUT → NEG du HTML matche exactement la convention chord (1-9 image, 1-8 prompt).

### Pour suite éventuelle (non-bloquant)

- Si on ajoute un nouveau tag dans le futur, il faut maintenant juste éditer `IMAGE_AXIS` ou `PROMPT_AXIS` dans `annotation_vocab.py`. Les tests `test_..._order_preserved` doivent alors être mis à jour pour refléter la nouvelle attente.
- Le `schema_version: 2` exposé par l'endpoint permettra un mécanisme de migration côté client si on bumpe à v3 (ex: ajout d'un champ `description` par tag, localisation, etc.). Non utilisé pour l'instant.
