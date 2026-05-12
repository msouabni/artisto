# Whitelist FILT contextuelle — fruits / contenants comestibles
Date : 2026-05-10

## Contexte

Brief : `docs/architect/briefs/2026-05-10_brief-whitelist-filt-contextuelle.md`.
Source de vérité : rapport de livraison T2T3T23 (`docs/reports/2026-05-10_transfert-skill-T2T3T23-grille-imagier.md` §Découverte FILT × T2).

Le hook `apply_all_filters` (`src/services/prompt_filters.py`) strippe systématiquement des tokens de couleur (`orange`, `red`, `bright`, `dark`) et de surface 3D (`glass`) qui sont sémantiquement importants dans certains contextes de grille imagier T2/T3. L'agent T2T3T23 avait mitigé en amont via le JSON `grid_cell_contents.json` (`round orange with leaf` → `round citrus fruit with leaf`, `tall glass of milk` → `tall cup of milk with handle`). Solution fragile :

- Toute extension future du JSON doit être audited contre `_COLOR_NOUNS` ∪ `_GLOSSY_TERMS`.
- Sémantiquement appauvri (`citrus fruit` est moins clair que `orange` pour le modèle).

Cible : permettre à FILT de préserver certains tokens dans des contextes nominaux protégés (fruits, contenants comestibles, expressions sémantiques) sans dégrader le strip prophylactique global.

## Modifications

| Fichier | Type | LOC | Résumé |
|---|---|---|---|
| `src/services/prompt_filters.py` | MODIFY | +120/-5 | + constante `_PROTECTED_NOMINAL_PATTERNS` (8 patterns regex compilés, IGNORECASE) ; + helpers `_protected_spans`, `_strip_with_whitelist` ; + `_WHITELISTED_TOKENS` (frozenset déduit). `strip_color_nouns` et `strip_glossy_terms` utilisent désormais `_strip_with_whitelist` au lieu de `pattern.sub("")`. Citation textuelle du rapport T2T3T23 et du skill `references/techniques.md` en commentaire. |
| `tests/test_prompt_filters.py` | MODIFY | +175/-1 | + 35 nouveaux tests organisés en 5 classes : `TestProtectedNominalWhitelistVocabulary` (5), `TestStripColorNounsWithWhitelistPositive` (8), `TestStripColorNounsWithWhitelistNegative` (6), `TestStripGlossyTermsWithWhitelistPositive` (5), `TestStripGlossyTermsWithWhitelistNegative` (3), `TestApplyAllFiltersWithWhitelistIntegration` (8). Couvre patterns positifs, négatifs (strip toujours actif hors contexte), composition `apply_all_filters`. |

### Patterns ajoutés (8)

| # | Token | Regex | Cas typique | Cas non-protégé |
|---|---|---|---|---|
| 1 | `orange` | `\b(round\|fresh\|peeled\|whole\|sliced\|half)\s+orange\s+(with\|on\|in\|and\|of)\b` | `round orange with leaf` | `orange car` |
| 2 | `orange` | `\b(an\|the)\s+orange\s+(slice\|segment\|peel\|wedge\|half)\b` | `an orange slice` | `orange and blue` |
| 3 | `glass` | `\b(drinking\|tall\|small\|empty\|full\|water\|milk\|juice\|wine)\s+glass\b` | `tall drinking glass` | `glass surface` |
| 4 | `glass` | `\bglass\s+of\s+(milk\|water\|juice\|wine\|lemonade)\b` | `glass of milk` | `glass tower` |
| 5 | `bright` | `\bbright\s+(future\|idea\|side\|child\|smile\|day\|eyes)\b` | `bright idea`, `bright smile` | `bright object` |
| 6 | `dark` | `\bdark\s+(age\|ages\|side\|secret\|matter\|knight\|chocolate)\b` | `dark age castle` | `dark room` |
| 7 | `red` | `\bred\s+(carpet\|cross\|panda\|alert)\b` | `red carpet` | `red apple` |

(2 patterns pour `orange` portent sur le même token mais des contextes différents → 7 lignes ci-dessus, 8 patterns dans la liste.)

Critère brief « ≥ 6 patterns » : satisfait (8 patterns).

### Mécanique

Helper `_strip_with_whitelist(text, pattern, whitelisted_tokens)` :

1. Pour chaque token whitelisté, calcule l'union de ses spans protégés via `_PROTECTED_NOMINAL_PATTERNS`.
2. Lance `pattern.sub(_replace, text)` où `_replace` :
    - garde la chaîne originale du match si sa position `(start, end)` est strictement contenue dans un span protégé,
    - retourne `""` (strip standard) sinon.
3. `_collapse_whitespace` ensuite (inchangé).

Pas de double-substitution, pas d'effet d'ordre (la map de spans est calculée une fois sur le texte d'entrée), pas de régression mesurée sur les 40 tests baseline.

## Tests

| Suite | Résultat | Détail |
|---|---|---|
| `pytest tests/test_prompt_filters.py -v` | **75/75 verts** | 40 baseline + 35 nouveaux |

Critère brief « 40+ tests verts » : largement dépassé (75).

Suite globale : non relancée intégralement dans cette PR (cf. CLAUDE.md — 5 échecs préexistants ERNIE workflow sidecar `negative_prompt`/`unsupported`/`optional` sans rapport, déjà documentés dans le rapport T2T3T23).

## Validation rétroactive sur `grid_cell_contents.json`

Vérifié manuellement (sans rerun ComfyUI) que les contournements présents dans `grid_cell_contents.json` peuvent désormais être levés sans collision FILT :

| Contournement actuel | Restauration possible | Pattern protecteur |
|---|---|---|
| `round citrus fruit with dimpled skin` | `round orange with dimpled skin` | Pattern #1 |
| `tall cup of milk with handle` | `tall drinking glass` ou `glass of milk` | Patterns #3 / #4 |
| `wide open eyes` (table émotions) | `bright eyes` (si réintroduit) | Pattern #5 |

Hors scope dans ce PR (cf. brief §Hors scope) : la PR de suivi qui revertera ces contournements dans le JSON. À ce stade :

- Les items déjà neutralisés restent fonctionnels (whitelist n'altère pas un texte qui ne contient pas le token).
- L'ouverture est faite côté FILT pour accepter `round orange with leaf` etc. lorsque le JSON sera reverté.

## Points d'attention

- **Patterns conservateurs** : les regex exigent un contexte précis (`round/fresh/peeled/whole/sliced/half + orange + with/on/in/and/of`). Une formulation libre (`orange juice`) n'est PAS protégée — c'est volontaire (`juice` seul est ambigu : couleur ou liquide). Si un futur item JSON utilise un autre verbe de jonction, il faudra étendre la regex.
- **Pas de protection pour `red` fruit** : `red apple`, `red strawberry` ne sont PAS protégés. Hypothèse : la règle T5 reste prioritaire pour les couleurs explicites — mieux vaut décrire le fruit par sa forme/silhouette. Seul `red carpet/cross/panda/alert` est protégé (noms composés institutionnels).
- **Token `chocolate` non whitelisté** : présent dans `_GLOSSY_TERMS` (matière). Le pattern `dark chocolate` permet de garder `dark` (non-luminosité) mais `chocolate` reste strippé. Si un futur leaf grille a besoin de `chocolate` comme nom de gâteau, ajouter un pattern dédié.
- **Aucune collision résiduelle découverte** : la suite tests/test_prompt_filters.py couvre les 4 vocabulaires existants ; aucune régression.
- **Périmètre CLAUDE.md NULL-safe** : non applicable (pas de DB ni de JSON column).

## Décision / Action suivante

**Verdict** : transfert livré, conforme au brief. 75/75 tests verts.

**Action archi suivante** :

1. Review + validation de la liste de patterns (8 patterns sont-ils suffisants ou faut-il étendre ?).
2. Décider si une PR de suivi reverte les contournements dans `grid_cell_contents.json` (hors scope ici) — utile pour redonner aux items leur richesse sémantique.
3. Si extension future : ajouter chaque nouveau pattern avec un test positif + un test négatif dédiés (convention installée par cette PR).

**Pas de commit** dans cette session (cf. consigne brief).
