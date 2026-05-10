# Whitelist FILT contextuelle — fruits / contenants comestibles

## Contexte

Le rapport de livraison T2T3T23 (`docs/reports/2026-05-10_transfert-skill-T2T3T23-grille-imagier.md` §Découverte FILT × T2) signale que `prompt_filters.apply_all_filters` strippe systématiquement des mots utiles pour les items de grille :

- **Couleurs** : `orange` (fruit), `red` → contournés en `round citrus fruit`, etc.
- **Surfaces** : `glass` (drinking glass) → contourné en `cup with handle`.
- **Luminosité** : `bright`, `dark`.

L'agent T2T3T23 a mitigé en amont en adaptant le JSON (`grid_cell_contents.json`) pour éviter les collisions. Mais c'est fragile :

- Toute extension future du JSON doit être auditée contre `_COLOR_NOUNS` + `_GLOSSY_TERMS`.
- Sémantiquement appauvri (`citrus fruit` est moins clair pour le modèle que `orange`).

Cible : permettre à FILT de **préserver certains tokens dans des contextes nominaux comestibles/contenants** sans dégrader le strip prophylactique global.

## Objectif

Ajouter une whitelist contextuelle dans `prompt_filters.py` qui préserve des mots strippés normalement quand ils apparaissent dans un pattern nominal protégé (ex. `round orange with leaf` → garder `orange` parce que `with leaf` indique un fruit).

## Périmètre

**Modifier** :

- `src/services/prompt_filters.py` :
  - Ajouter une constante `_PROTECTED_NOMINAL_PATTERNS: list[tuple[str, re.Pattern]]` listant les paires (token_filtré, regex_de_contexte_protégé). Exemples :
    - `("orange", re.compile(r"\b(round|fresh|peeled|whole|sliced)\s+orange\s+(with|on|in)\b"))` → fruit, pas couleur.
    - `("glass", re.compile(r"\b(drinking|tall|small|empty|full|water|milk|juice)\s+glass\b"))` → contenant, pas surface 3D.
    - `("bright", re.compile(r"\b(bright)\s+(side|future|idea|child|smile)\b"))` → adjectif sémantique, pas luminosité.
  - Modifier `strip_color_nouns`, `strip_glossy_terms` pour vérifier les patterns protégés AVANT le strip : si le token apparaît dans un contexte protégé, ne pas le stripper localement.
  - Documenter la logique en commentaire (cite `2026-05-10_transfert-skill-T2T3T23-grille-imagier.md` §Découverte FILT × T2).
- `tests/test_prompt_filters.py` :
  - Tests positifs : `round orange with leaf` → préservé ; `drinking glass of milk` → préservé.
  - Tests négatifs (strip toujours actif hors contexte) : `orange car` → strippé en `car` ; `glass surface` → strippé en `surface`.
  - Tests intégration avec `apply_all_filters` (composition).
  - Test régression : tous les tests existants restent verts.

## Plan d'exécution suggéré (sous-agent unique)

Pas de parallélisation utile — petit scope (1 module + 1 fichier de test).

```
Phase 1 — Audit (Claude Code principal, ~10 min)
  - Lire tests/test_prompt_filters.py existants pour aligner le style.
  - Lister exhaustivement les collisions actuelles depuis grid_cell_contents.json
    (grep des tokens strippés vs items présents).

Phase 2 — Implémentation (Claude Code principal, ~30 min)
  - Ajouter _PROTECTED_NOMINAL_PATTERNS avec ~6-8 patterns prioritaires.
  - Modifier strip_color_nouns + strip_glossy_terms.
  - Tests unitaires + non-régression.

Phase 3 — Validation rétroactive sur grid_cell_contents.json
  - Re-générer les positives pour les 14 leafs grille.
  - Vérifier qu'on peut désormais utiliser orange / glass / bright dans le JSON
    sans collision — proposer revert des contournements (fruits → vrais noms)
    dans une PR de suivi (hors scope ici).
```

## Critères d'acceptation

- `_PROTECTED_NOMINAL_PATTERNS` défini avec ≥ 6 patterns documentés.
- Strip préservé hors contexte nominal protégé (tests négatifs).
- Strip court-circuité dans contexte protégé (tests positifs).
- 40+ tests verts dans `test_prompt_filters.py` (existants + nouveaux).
- Citation du rapport T2T3T23 + skill `references/techniques.md` en commentaire.

## Hors scope

- Revert des contournements dans `grid_cell_contents.json` (PR de suivi optionnelle).
- Élargissement des patterns au-delà des 6-8 cibles prioritaires (extension itérative).
- Refonte de `_COLOR_NOUNS` / `_GLOSSY_TERMS` (vocabulaires inchangés).

## Reporting

`docs/reports/2026-05-10_whitelist-filt-contextuelle.md` — Contexte / Modifications / Tests / Validation rétroactive / Décision.

## Estimation

~45-60 min dev + tests + rapport.
