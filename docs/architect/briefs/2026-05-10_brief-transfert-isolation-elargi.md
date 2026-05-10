# Transfert _ISOLATION élargi — templates Solo humain / Solo objet / Humain+entité

## Contexte

L'analyse `docs/reports/2026-05-10_analyse-annotations-transferts-skill.md` §3 #4 et §5.A identifie **~12 occurrences `image_duplication`** sur des templates **non-Solo-animal** où `_ISOLATION` n'est pas appliqué :

- `Solo humain (générique)`, `Solo humain + accessoires`, `Humain + entité (cheval)`, `Humain + entité (instrument)`, `Humain + entité OU Solo humain pose statique`, `Scène ou solo personnage`, `Solo objet ou Humain + entité`.

Diagnostic : seuls `template_solo_animal/insect/fish/bird/reptile` ont reçu le suffixe `_ISOLATION` (`isolated subject, no other animals or objects nearby`). NEGATIVE_V3 contient des termes anti-multi-animaux mais **pas anti-multi-humains/objets** explicites.

Règle skill : T9 + règle générale « moins de mise en scène = plus de fiabilité ».

## Objectif

Étendre `_ISOLATION` aux templates Solo humain / Solo objet / Humain+entité, et compléter NEGATIVE_V3 avec termes anti-multi-humains/objets.

## Périmètre

**Modifier** :

- `src/services/prompt_generator.py` :
  - Ajouter suffixe `_ISOLATION_HUMAN` (`isolated subject, no other people or objects nearby`) injecté dans : `template_solo_human`, `template_solo_human_accessories`, `template_personality_action`, `template_pose_static`, `template_human_plus_entity`, `template_scene_or_solo_character`.
  - Ajouter suffixe `_ISOLATION_OBJECT` (`isolated subject, no other items nearby`) injecté dans : `template_solo_object` (et variantes routées dessus).
  - Étendre `NEGATIVE_V3` avec : `multiple people, group of people, second person, person in background, multiple objects, group of objects, second object`.
- `tests/test_prompt_generator.py` :
  - Test : chaque template ciblé contient le suffixe `_ISOLATION_*` correspondant.
  - Test : `NEGATIVE_V3` contient les nouveaux termes.
  - Test non-régression : templates Solo animal/insect/fish/bird/reptile inchangés.

## Critères d'acceptation

- Suffixes `_ISOLATION_HUMAN` et `_ISOLATION_OBJECT` injectés dans les templates ciblés.
- `NEGATIVE_V3` étendu.
- Tests pytest verts.
- Citation T9 + règle générale en commentaire.

**Mesure post-transfert (optionnelle)** : rerun ComfyUI sur les leafs `image_duplication` non-Solo-animal du corpus (`child_with_test_tubes`, `gaming_setup_with_keyboard`, `horse_racing`, `laptop_open_with_code`, `optometrist_eye_test`, `three_little_pigs`, `house_painter_with_roller`, `animal_superhero`) — seed offset +500. Comparer `image_duplication` post vs baseline.

## Reporting

`docs/reports/2026-05-10_transfert-skill-isolation-elargi.md` — Contexte / Modifications / Tests / Mesure post (ou « à planifier ») / Décision.

## Hors scope

- Modification des templates Solo animal/insect/fish/bird/reptile.
- Création de `LEAF_OVERRIDES` supplémentaires.

## Estimation

~30-45 min dev + tests + rapport.
