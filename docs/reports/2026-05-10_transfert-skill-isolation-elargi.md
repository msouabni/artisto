# Transfert skill — _ISOLATION élargi (humain / objet / humain+entité)
Date : 2026-05-10

## Contexte

Le transfert T9 initial (2026-05-10 matin) a appliqué `_ISOLATION` aux 5 templates morphologiques animaux (`template_solo_animal`, `_insect`, `_fish`, `_bird`, `_reptile`). L'analyse `docs/reports/2026-05-10_analyse-annotations-transferts-skill.md` (§3 #4 + §5.A) identifie **~12 occurrences `image_duplication`** restantes sur des templates **non-Solo-animal** (Solo humain, Solo objet, Humain+entité, personnalité, pose statique). Ce transfert élargit l'application de l'isolation aux templates concernés et complète `NEGATIVE_V3` avec des termes anti-multi-humains et anti-multi-objets, en s'appuyant sur la règle générale skill « Moins de mise en scène = plus de fiabilité » (`references/techniques.md` L582+).

## Modifications

### `src/services/prompt_generator.py`

| Élément | Changement | Lignes |
|---|---|---|
| `NEGATIVE_V3` | Étendu avec `multiple people, group of people, second person, person in background, multiple objects, group of objects, second object`. Citation skill ajoutée en commentaire. | ~55-71 |
| `_ISOLATION_HUMAN` | Nouvelle constante : `"isolated subject, no other people or objects nearby"` | ~88-91 |
| `_ISOLATION_OBJECT` | Nouvelle constante : `"isolated subject, no other items nearby"` | ~93-94 |
| `template_solo_human` | Suffixe `_ISOLATION_HUMAN` injecté en fin de positive (couvre classes « Solo humain », « Solo humain (générique) », « Solo humain + accessoires », « Solo humain (mère) », « Solo humain pose active », « Solo humain en action »). Docstring + citation skill mises à jour. | template touché |
| `template_solo_object` | Suffixe `_ISOLATION_OBJECT` injecté en fin de positive (couvre toutes les variantes routées dessus : véhicule, drapeau, plante, scène intérieure, scène spatiale, pattern décoratif, etc.). Docstring + citation skill. | template touché |
| `template_human_plus_entity` | Suffixe `_ISOLATION_HUMAN` injecté pour empêcher l'introduction d'un 3e sujet sur la scène duo (cas observé `child_with_test_tubes`, `house_painter_with_roller`). | template touché |
| `template_personality_action` | Suffixe `_ISOLATION_HUMAN` injecté (couvre « Solo humain (personnalité) », « Solo humain ou animal cartoon », « Scène ou solo personnage », « Solo humain ou créature »). | template touché |
| `template_pose_static` | Suffixe `_ISOLATION_HUMAN` injecté (couvre « Solo humain en pose » — yoga, méditation). | template touché |

LOC ajoutées/modifiées dans `prompt_generator.py` : ~55 lignes (commentaires + suffixes + docstrings + extension NEGATIVE_V3).

### Hors périmètre (intacts conformément au brief)
- Templates `template_solo_animal/insect/fish/bird/reptile` (zone T9) — `_ISOLATION` animal préservé.
- `template_before_after` (zone T25) — logique propre, pas de suffixe d'isolation.
- `template_grid_3x3_imagier`/`_annotated`, `template_solo_expressive_face` (zones T2/T3/T23) — logiques propres.
- `template_frieze_1xN`, `template_landscape_2plane`, `template_multiplane_stacked` — non listés au brief, intacts.
- `prompt_filters.py` (zone FILT) — non touché. Vérifié : les filtres FILT ne strippent ni `isolated`, ni `nearby`, ni `people`, ni `items` → suffixe propagé tel quel via le hook FILT dans `build_prompt`.

### `tests/test_prompt_generator.py`

16 tests ajoutés (section `Transfert _ISOLATION élargi`) :
- 2 tests sur les constantes (`_ISOLATION*` distincts et non vides ; `isolated subject` partagé).
- 2 tests sur `NEGATIVE_V3` (extension humans+objects présente ; legacy animals non régressé).
- 4 tests d'injection sur les nouveaux templates (`template_solo_human`, `template_personality_action`, `template_pose_static`, `template_human_plus_entity`).
- 1 test sur `template_solo_object` (suffixe OBJECT, pas HUMAN/animal).
- 5 tests de non-régression sur les templates Solo animal/insect/fish/bird/reptile (gardent `_ISOLATION` animal, pas HUMAN/OBJECT).
- 2 tests d'exclusion (`template_before_after` et `template_grid_3x3_imagier` ne reçoivent pas `_ISOLATION_*`).
- 1 test smoke `build_prompt` complet sur un leaf Solo humain (vérifie propagation à travers le hook FILT).

## Tests

```
pytest tests/test_prompt_generator.py
55 passed in 0.12s
```

- 39 tests pré-existants : verts (zéro régression).
- 16 tests nouveaux : verts.

Suite complète (hors `test_content_generator.py` cassé en collection par un import préexistant `HARAKAT_RE` non lié) :
```
283 passed, 5 failed
```
Les 5 échecs sont **préexistants et non liés** à ce transfert :
- `test_create_image_job_workflow.py` (2) : contrat capabilities ERNIE `negative_prompt: optional` vs `unsupported`.
- `test_bulk_generation_jobs.py` (2) : dédup + preflight négatif ERNIE.
- `test_workflow_template_sidecar.py` (1) : sidecar `negative_prompt: unsupported` attendu.

Aucun de ces fichiers n'importe `prompt_generator` (vérifié par grep).

## Mesure post-transfert

À planifier — rerun ComfyUI sur les 8 leafs `image_duplication` non-Solo-animal listés au brief (`child_with_test_tubes`, `gaming_setup_with_keyboard`, `horse_racing`, `laptop_open_with_code`, `optometrist_eye_test`, `three_little_pigs`, `house_painter_with_roller`, `animal_superhero`) avec seed offset +500, comparer `image_duplication` post vs baseline. Hors scope dev — l'archi déclenche le rerun après livraison.

## Points d'attention

- **Non-doublonnage des termes négatifs** : `NEGATIVE_V3` contient déjà `second subject, multiple subjects` (génériques). On a ajouté `second person`/`second object` (spécifiques) — la redondance est volontaire pour saturer le canal négatif sur les classes ciblées (cf. patron T9 qui empile aussi `multiple animals` + `second subject`).
- **`template_human_plus_entity` reçoit `_ISOLATION_HUMAN`** — choix sémantique : la formule « no other people or objects nearby » couvre à la fois l'ajout d'une 3e personne et l'ajout d'un objet de décor parasite, ce qui correspond aux défauts observés (`house_painter_with_roller` avec un 2e peintre, `child_with_test_tubes` avec un microscope intrus). Variante non testée : un suffixe dédié `_ISOLATION_DUO` plus permissif. À évaluer si la mesure post montre un sur-strict.
- **Templates non listés au brief** mais qui pourraient mériter un suffixe (Frise, Paysage, Multiplan) : laissés intacts pour rester strictement dans le périmètre du brief — l'archi tranchera après mesure.

## Décision / Action suivante

**Go pour ANAT suivant** — le transfert _ISOLATION élargi est livré, testé (55/55 verts), sans régression sur les zones préservées (T9/T25/T2/T3/T23/FILT). Pas de commit (l'archi commit après livraison).

Suivant suggéré : transfert ANAT (3_jambes) si brief disponible.
