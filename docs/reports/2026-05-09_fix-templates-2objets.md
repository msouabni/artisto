# Fix — 2_objets defect in PromptGenerator templates
Date : 2026-05-09

## Contexte

Analyse des 196 annotations du poc-scale-benchmark : 16 images annotées `2_objets` (score 1 dans 14/16 cas). Tous les cas affectent des templates "Solo" (Solo animal, Solo insect, Solo fish) où le modèle ERNIE génère un second sujet non demandé malgré "one single X" dans le prompt positif.

## Racine du problème

- `NEGATIVE_V3` ne contenait aucune contrainte contre les sujets multiples.
- Les templates Solo ne forçaient pas l'isolation explicitement dans le positif.
- Certaines feuilles (`sheep_with_lamb`, `eid_al_adha_sheep`) ont des noms qui induisent la génération de 2 animaux.

## Corrections appliquées — `src/services/prompt_generator.py`

### 1. NEGATIVE_V3 étendu
Ajout en queue :
```
"multiple animals, other animals, companion animal, group of animals, "
"animal in background, second subject, multiple subjects"
```
S'applique à **toutes les feuilles** sans exception.

### 2. Clause `_ISOLATION` dans les positifs Solo
Nouveau suffixe : `"isolated subject, no other animals or objects nearby"`

Injecté à la fin de **5 templates** :
- `template_solo_animal`
- `template_solo_insect`
- `template_solo_fish`
- `template_solo_bird`
- `template_solo_reptile`

### 3. `LEAF_OVERRIDES` — prompts manuels

| leaf_id | Action |
|---|---|
| `sheep_with_lamb` | Override → "one single adult sheep + very small lamb outline (not a separate subject)" |
| `eid_al_adha_sheep` | Override → "one single decorated sheep, festive ribbon around neck" |

### 4. `_RISKY_MULTI_PATTERNS` — renforcement négatif

Patterns détectés dans leaf_id : `_with_friend`, `_with_chicks`, `_and_`, `_in_anemone`, `_with_school`, `_with_cub`, `_with_pup` → ajout au négatif de `"two animals, pair of animals, multiple animals together"`.

## Vérification

Validation sur 8 feuilles cibles :
- `chimpanzee`, `golden_retriever`, `running_cheetah` : isolation_in_pos=True, multi_in_neg=True ✓
- `sheep_with_lamb`, `eid_al_adha_sheep` : LEAF_OVERRIDE actif ✓
- `playful_dolphin` (Solo fish), `grasshopper` (Solo insect) : isolation OK ✓
- 1376 feuilles buildées, 0 erreurs ✓

## Cas restants à surveiller

- `letter_z_with_zebre` → 2_objets **intentionnel** (classe Lettre + objet) : pas de fix
- `animal_superhero` → classe Solo humain/animal cartoon, prompt_incohérent aussi → sujet difficile, pas de fix template
- `house_painter_with_roller` → Solo humain + accessoires (roller = accessoire, pas un 2e sujet) → template_solo_human
- `mountain_gorilla`, `running_cheetah` : fix via `_ISOLATION` + NEGATIVE_V3 étendu

## Décision / Action suivante

Prêt pour un re-run ciblé sur les 14 cas critiques (score=1, 2_objets) pour valider l'efficacité. Ou intégrer dans le prochain batch scale benchmark. Mettre à jour CLAUDE.md avec les règles empiriques.
