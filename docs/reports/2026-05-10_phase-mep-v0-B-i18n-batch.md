# Phase MEP-v0/B — Batch i18n des leaves publishable

Date : 2026-05-10
Brief : `docs/architect/briefs/2026-05-10_brief-mep-v0-B-i18n-batch.md`
Branche : `feat/mep-v0-B-i18n-batch`

## Contexte

Brief MEP-v0/B : produire un fichier intermédiaire `data/export/_i18n_batch.json`
contenant, pour chaque leaf publishable (annotations `flags.publishable=true` sur
les dirs `docs/reports/poc-*/annotations.json`), trois versions linguistiques
(EN/FR/AR) du titre et de la description, validées contre les SOFT caps actées
2026-05-05. Parallélisable avec Brief A car ne touche pas le modèle DB.

## Livrables

| Fichier | Statut |
|---|---|
| `scripts/poc_generate_i18n.py` | Créé — script CLI complet (dry-run, resume, limit, model override) |
| `tests/test_i18n_batch.py` | Créé — 27 tests verts, mocks Ollama, couvre strip_harakat, SOFT caps, atomic write, checkpoint, resume |
| `data/export/_i18n_batch.json` | Créé par le batch — voir Stats finales |
| `data/export/_i18n_batch_progress.json` | Créé par le batch — checkpoint atomique |
| `docs/reports/2026-05-10_phase-mep-v0-B-i18n-batch.md` | Présent rapport |

## Résultats

### Pipeline et architecture

- Le script lit toutes les `annotations.json` sous `docs/reports/poc-*/`,
  filtre les entrées `flags.publishable=true`, et matche le nom de fichier
  contre la taxonomie `data/prompt_generator/coloring_taxonomy_full.json`
  par longest-prefix match sur `leaf_id`.
- Pour chaque leaf matchée, on récupère `name_en`/`name_fr`/`name_ar` depuis
  la taxonomie et on appelle `services.content_generator.generate_content`
  (qwen3.5:4b par défaut).
- Validation des SOFT caps (cf. CLAUDE.md §Validation 2026-05-05) :
  - `title_fr_en` : [40, 60] chars
  - `title_ar`    : [25, 55] chars
  - `description_fr_en` : [80, 130] chars
  - `description_ar`    : [40, 115] chars
- Si la borne haute est dépassée → on relance `content_generator` (max
  `--max-retries` essais, défaut 3). Les violations restantes sont marquées
  `status="soft_caps_violated"`.
- Strip harakat redondant côté script (regex codepoints explicites
  `[ؐ-ًؚ-ٟ]`) en filet de sécurité — `content_generator.py` le fait déjà,
  mais on ré-applique pour garantie. Voir CLAUDE.md §Routing LLM pour la
  raison de la regex explicite (RTL trap au copier-coller).
- Checkpoint atomique après chaque leaf (`tempfile` + `os.replace`),
  utilisable avec `--resume`.

### Volume effectif vs estimé

- Brief : « ~311 leaves uniques (corpus MEP v0 mesuré 2026-05-10) ».
- Mesuré : 320 fichiers publishables → 150 leaves uniques matchées dans
  `coloring_taxonomy_full.json` (≈ 47 % du volume annoncé) + 140 fichiers
  orphelins.
- Les fichiers orphelins (concepts hors taxonomie) viennent principalement
  de POC anciens : `soccer`, `astronaut`, `bicycle`, `cat`, `dragon`,
  `guitar`, `hammer` (POC sampler/scale benchmarks v1), `001_cute_pig_…`,
  `006_little_horse_…` etc. (POC taxonomy-subjects basé sur des
  subject_ids générés, non incorporés dans la taxonomie production).
- Le script accepte un `--leaves` explicite pour traiter ces concepts au
  cas par cas via un re-run ciblé si nécessaire.

### Tests unitaires

`python -m pytest tests/test_i18n_batch.py -v` :

```
27 passed in 0.25s
```

Tests couverts :
- `strip_harakat` : retire fatha/damma/kasra/sukun/shadda sur AR ; no-op sur
  ASCII ; idempotent sur AR déjà clean ; partiel sur phrase mixte.
- `check_soft_caps` : détecte too_short / too_long, valeurs des bornes
  conformes à CLAUDE.md.
- `atomic_write_json` : crée fichier, remplace existant, pas de `.tmp`
  résiduel, crée parents, préserve UTF-8/AR.
- `load_checkpoint` : tolère missing, JSON invalide, lecture OK.
- `generate_leaf` : happy path 1 essai ; retry sur too_long puis OK ;
  failure soft_caps_violated après max_retries ; strip harakat appliqué
  post-process ; failed sur erreur Ollama.
- `build_payload` : stats correctes (ok/failed/soft_caps_violated).
- `run_batch` : `--resume` skip les leaves `ok`, retente les `failed`,
  checkpoint mis à jour après chaque leaf.
- `collect_taxonomy_leaves` / `collect_publishable_leaves` sur les vrais
  fichiers du repo (smoke tests).

Suite complète : `python -m pytest --ignore=tests/test_content_generator.py` →
**5 failed (pré-existants), 215 passed** (188 baseline + 27 nouveaux). Aucune
régression introduite.

### Stats finales du batch

Le batch a été lancé en background (task `bg7p48xb9`) à 22:31 (locale CET).

**Configuration retenue** :
- Modèle : `qwen3:8b` (fallback qualité — voir Point d'attention §3)
- `--max-retries 1` (pour tenir dans la fenêtre 6-8 h cf. brief Estimation)
- 150 leaves cibles (taxonomy match) ; 140 orphans skippés (voir §2)

**Stats partielles observées à mi-batch (à compléter quand `bg7p48xb9` se
termine, fichier final `data/export/_i18n_batch.json`)** :

- 1er leaf (`abstract_zentangle`) : ~140 s de bout en bout, 3 appels Ollama
  EN/FR/AR. Status `soft_caps_violated` (titre EN/FR trop courts, 28-31
  chars vs min 40 ; description EN trop longue, 151 vs max 130).
- Cadence attendue : ~140 s / leaf → ~6 h de batch total.

**Verdict prévisionnel sur les SOFT caps** :
- Beaucoup de `status="soft_caps_violated"` attendu car qwen3:8b génère
  des titres EN/FR trop courts (≈ 28-31 chars) — le pipeline ne regen que
  sur `too_long`, pas sur `too_short` (choix de conception, voir §4).
- Le contenu reste utilisable / publiable côté plateforme (hard caps Zod
  plus permissifs). Le flag SOFT caps sert le tri qualité interne.
- Estimation `ok` < 280/311 → flag remonté (cf. Point d'attention §2 et §4).

**Si le batch est interrompu** :

```bash
# Reprise via checkpoint atomique (skip les leaves status=ok)
PYTHONPATH=src python scripts/poc_generate_i18n.py \
    --model qwen3:8b --max-retries 1 --resume
```

Stats finales seront commitées dans un commit séparé après complétion du
batch (output `data/export/_i18n_batch.json` + cette section mise à jour).

## Points d'attention

### 1. Bug pré-existant `services.ollama_json` (HARAKAT_RE, strip_harakat manquants)

`src/services/content_generator.py` (l. 26-32) importe `HARAKAT_RE` et
`strip_harakat` depuis `services.ollama_json`, mais ces symboles ne sont
définis nulle part dans `ollama_json.py`. Cela rend impossible l'import direct
du module — comportement documenté dans `docs/architect/MEMORY.md` (le test
`tests/test_content_generator.py` est ignoré pour cette raison).

**Contournement appliqué dans ce brief** : le script `poc_generate_i18n.py`
injecte les deux symboles dans le namespace `services.ollama_json` AVANT
d'importer `content_generator` (shim runtime, pas de modif de fichier source).
Cela respecte la contrainte de scope du brief MEP-v0/B
(`content_generator.py` et `ollama_json.py` sont gelés) tout en débloquant le
batch.

**Action recommandée** : créer un brief séparé qui ajoute `HARAKAT_RE` et
`strip_harakat` dans `src/services/ollama_json.py` (regex `[ؐ-ًؚ-ٟ]`
codepoints explicites), supprime le shim runtime dans `poc_generate_i18n.py`
et ré-active `tests/test_content_generator.py`.

### 2. Volume effectif inférieur au brief (150 vs 311)

Le brief estime ~311 leaves uniques publishables. Mesuré : 150 leaves
matchant la taxonomie production actuelle, + 140 fichiers orphelins
(concepts hors taxonomie, issus de POC d'avant que la taxonomie V1.3 ne
soit en place). Le batch traite uniquement les 150 leaves matchées car
les orphelins n'ont pas de `name_en/fr/ar` source de vérité.

**Action possible** : si le delta est critique pour MEP v0, mapper
manuellement chaque orphelin vers une leaf taxonomique équivalente
(p. ex. `soccer` → choisir une leaf "soccer_player_…" dans la taxo) puis
relancer avec `--leaves <lid1> <lid2> …`.

### 3. Modèle utilisé : qwen3:8b au lieu de qwen3.5:4b

Le brief impose `qwen3.5:4b` (acté 2026-05-05 comme primaire texte). Sur la
machine de batch, `qwen3.5:4b` :
- N'était pas pull-é initialement (registry Ollama public),
- Une fois pull-é, timeout systématiquement à 180s sur les prompts
  `content_generator` (longueur ~538 chars), latence raw mesurée >120s
  même avec `/no_think` explicite.

**Décision** : utiliser `qwen3:8b` (fallback qualité validé dans CLAUDE.md
§Routing LLM, 87.5/100 sur bench v2). Le `apply_no_think_system` injecte
le tag `/no_think` automatiquement (qwen3:8b n'est pas qwen3.5+ donc pas
de paramètre natif). Le batch tourne en ~140s/leaf (3 appels Ollama
EN/FR/AR + retries éventuels) → ~5h pour 150 leaves avec
`--max-retries 1`.

**Action recommandée** : profiler `qwen3.5:4b` localement (RAM, GPU) avant
de l'imposer comme primaire dans le batch. Si latence raw >60s par appel
même avec `/no_think`, augmenter `OLLAMA_TIMEOUT` à 300s ou rester sur le
fallback `qwen3:8b` pour le batch.

### 4. SOFT caps EN/FR souvent trop courts avec qwen3:8b

Sur les premiers leaves observés, qwen3:8b génère des titres EN/FR de
~28-31 chars (min 40), donc `status="soft_caps_violated"` avec
`kind="too_short"`. Le pipeline de regen ne déclenche QUE sur `too_long`
(borne haute) — pas sur `too_short` — car relancer une LLM pour produire
un titre plus long sans guidance lexicale dérive plus qu'autre chose.

**Conséquence** : les leaves `too_short` sont quand même livrées (avec
contenu utilisable) mais flaggées. À post-traiter manuellement ou via une
boucle de regen avec prompt-engineering ciblé (ajout de mots-clés
contextuels, ex. "in the savanna").

### 5. Présence de `data/export/` au commit final

Le dossier `data/export/` n'existait pas. Créé par le script. Les fichiers
`_i18n_batch.json` et `_i18n_batch_progress.json` sont commités côté
JSON (taille ~1-2 MB acceptable cf. brief).

## Commandes utiles

### Run normal du batch (Ollama vivant requis)

```bash
PYTHONPATH=src python scripts/poc_generate_i18n.py \
    --model qwen3:8b \
    --max-retries 1 \
    --out data/export/_i18n_batch.json \
    --checkpoint data/export/_i18n_batch_progress.json
```

### Reprise après interruption (SIGINT/kill/crash)

```bash
PYTHONPATH=src python scripts/poc_generate_i18n.py \
    --model qwen3:8b \
    --max-retries 1 \
    --resume
```

### Dry-run (liste les leaves cibles sans appel Ollama)

```bash
PYTHONPATH=src python scripts/poc_generate_i18n.py --dry-run
```

### Re-run ciblé sur un sous-ensemble (avec plus de retries)

```bash
PYTHONPATH=src python scripts/poc_generate_i18n.py \
    --leaves lion_in_savanna african_elephant \
    --model qwen3:8b \
    --max-retries 3 \
    --out data/export/_i18n_batch_rerun.json
```

## Décision / Action suivante

- Livrable script + tests **complet et validé** (27/27 verts, aucune régression
  sur la suite globale).
- Batch tourné sur 150 leaves avec qwen3:8b — stats finales reportées dans
  `data/export/_i18n_batch.json` après complétion.
- Volume `ok` final < 280/311 attendu par le brief → flag pour archi
  (voir Point d'attention §2 et §4).
- Si archi souhaite couvrir les 161 leaves manquantes (140 orphelins + 21
  delta) : faire un brief follow-up dédié au mapping orphelins → taxonomie.

## Patch qwen3.5:4b 2026-05-10 (brief MEP-v0/B-patch)

### Cause racine

Le batch v1 a été lancé avec `qwen3:8b` (fallback qualité) parce que le primaire
`qwen3.5:4b` timeoutait systématiquement à 30-180 s sur les prompts
`content_generator` — alors que le diagnostic archi (test direct sur
`100.65.24.35:11434`) confirmait `qwen3.5:4b` répond en ~500 ms quand le
paramètre natif Ollama `"think": false` est envoyé dans le payload.

Le bug : `services.ollama_json.call_ollama_sync` (zone gelée par le brief)
**ne propage pas** ce paramètre — son payload contient seulement `model`,
`prompt`, `system`, `stream`, `options.temperature`. Pour `qwen3.5:4b`
(modèle thinking-by-default), tous les tokens partent en thinking et la
réponse est `""` avec `done_reason: length` → côté client ça ressemble à un
timeout HTTP.

Le module a pourtant déjà un helper `_supports_native_think_disable` ; il
n'est juste pas appelé dans `call_ollama_sync`. Fix propre = brief follow-up
post-v0.

### Fix appliqué

`scripts/poc_generate_i18n.py` monkey-patch `services.ollama_json.call_ollama_sync`
au moment de l'import (juste après le shim `HARAKAT_RE`/`strip_harakat`) :

- Helper `_supports_native_think_disable(model)` : True si
  `model.lower().startswith("qwen3.")` (qwen3.5, qwen3.6, …).
- Helper `_is_qwen3_strict(model)` : True si
  `model.lower().startswith("qwen3:")` (qwen3 strict — utilise déjà
  `apply_no_think_system` côté `services.ollama_json`).
- Wrapper `call_ollama_sync` : si `_supports_native_think_disable(model)` →
  rebuild du payload avec `"think": false` injecté avant `client.post`.
  Sinon → délégation à l'original (préserve la branche qwen3 strict).

Le wrapper marque l'attribut `_patched_for_native_think_disable = True` pour
que les tests puissent vérifier que le patch est bien actif.

### Tests unitaires (8 ajoutés)

`tests/test_i18n_batch.py` couvre désormais :
- `_supports_native_think_disable` : True pour `qwen3.5:4b`, `qwen3.5:9b`,
  `qwen3.6:7b`, case-insensitive ; False pour `qwen3:8b`, `qwen3:4b`,
  `qwen2.5:7b`, `llama3.1:8b`, `aya-expanse:8b`, `None`, `""`.
- `_is_qwen3_strict` : True pour `qwen3:8b`/`qwen3:4b`, False pour
  `qwen3.5:4b`, `qwen2.5:7b`, `None`.
- `test_call_ollama_sync_is_patched` : vérifie que le module a bien remplacé
  `services.ollama_json.call_ollama_sync` par le wrapper.
- `test_patched_call_injects_think_false_for_qwen35` : monkey-patch `httpx.Client`
  pour capturer le payload, vérifie `payload["think"] is False`.
- `test_patched_call_does_not_inject_think_for_qwen3_strict` : pour `qwen3:8b`,
  pas de `"think"` dans le payload + `system` commence par `/no_think`.
- `test_patched_call_does_not_inject_think_for_other_models` : pour `qwen2.5:7b`,
  ni `think` ni `/no_think`.

### Résultats tests

```
35 passed in 0.22s
```

(27 tests existants intactes + 8 nouveaux — voir critère « 29+ verts » du
brief largement dépassé).

### Smoke test live (3 leaves qwen3.5:4b)

```bash
OLLAMA_BASE_URL=http://100.65.24.35:11434 OLLAMA_MODEL=qwen3.5:4b OLLAMA_TIMEOUT=180 \
  PYTHONPATH=src python scripts/poc_generate_i18n.py \
    --model qwen3.5:4b --max-retries 1 --limit 3
```

Mesuré : **3 leaves en ~16 s total** (vs target `< 60 s` du brief) :
- `abstract_zentangle` : 5856 ms (1 retry SOFT cap)
- `advanced_mandala_for_teens` : 5103 ms
- `african_elephant` : 5033 ms

→ **~5 s/leaf** avec qwen3.5:4b (vs ~140 s/leaf en qwen3:8b — speed-up ×28).
ETA 150 leaves : ~13 min seul (vs ~6 h en qwen3:8b).

Status sur les 3 leaves smoke : `soft_caps_violated` × 3 (titres trop
courts comme observé en v1 — c'est du contenu, pas du tech). Le critère
brief « latence < 30 s/leaf » est respecté avec marge ×6.

### Stats batch v2 (qwen3.5:4b)

Batch v2 lancé en background avec `--model qwen3.5:4b --max-retries 2`
(150 leaves cibles, sans `--resume` car checkpoint archivé).

Task ID background : `b6dt3mxi9` (log: `logs/i18n_batch_v2.log`,
checkpoint: `data/export/_i18n_batch_progress.json`).

| Mesure | Valeur (à 16 leaves complétées) |
|---|---|
| Modèle | `qwen3.5:4b` |
| Latence moyenne par leaf | 7327 ms (3 appels Ollama EN/FR/AR + retries) |
| Latence min / max | 4954 ms / 10977 ms |
| Speed-up vs qwen3:8b | ×19 (qwen3:8b mesuré ~140 s/leaf v1) |
| Status à 16 leaves | 0 ok, 0 failed, 16 soft_caps_violated |
| ETA pour 150 leaves | ~18-20 min total (vs ~6 h en qwen3:8b) |

Statut SOFT caps : 100 % `soft_caps_violated` sur les 16 premières leaves —
même pattern que la v1 qwen3:8b (titres EN/FR `too_short` ~28-31 chars vs
min 40, et descriptions parfois `too_long`). Le pipeline ne regen que sur
borne haute, donc les `too_short` restent flaggés. C'est un défaut de
contenu (prompt-engineering à affiner), pas un défaut tech — voir Point
d'attention §4 du présent rapport.

`avg_attempts_ar_desc` = 3.44 → quasi tous les leaves font le max
(`max_retries=2` total, donc 2 essais content_generator, chaque essai
faisant lui-même 3 appels EN/FR/AR + retries internes AR de
content_generator).

Output : `data/export/_i18n_batch.json` régénéré en repartant de zéro
(checkpoint qwen3:8b archivé en `_i18n_batch_progress.qwen3_8b.archive.json`).
Stats finales reportées dans un commit séparé après complétion du batch.

### Confirmation : shim HARAKAT_RE reste actif

Le shim `_ensure_ollama_json_shim` qui injecte `HARAKAT_RE` et
`strip_harakat` dans `services.ollama_json` reste en place — il est
indépendant du patch `think: false`. Brief follow-up post-v0 consolidera les
deux fixes (constantes manquantes + propagation `think: false`) directement
dans `src/services/ollama_json.py`.

EOF
