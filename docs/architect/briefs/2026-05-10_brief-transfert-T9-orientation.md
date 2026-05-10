# Transfert T9 — profil + orientation directionnelle (Solo animal résiduels)

## Contexte

Le rerun-2objets a déjà transféré v1 → v2 (NEGATIVE_V3 + `_ISOLATION` + `LEAF_OVERRIDES` partiels). Mesure factuelle sur les 13 paires v1/v2 (cf. `docs/reports/2026-05-10_analyse-annotations-transferts-skill.md` §5.A) :

- v1 `image_duplication` : 13/13 (100%)
- v2 `image_duplication` : 6/13 (46%) — résiduels persistent

**6 leafs résiduels** : `bactrian_camel`, `golden_retriever`, `mountain_gorilla`, `playful_dolphin`, `running_cheetah`, `running_giraffe`. Caractéristique commune : morphologie à élément qui s'étend derrière le sujet (queue ample, cou long, patte arrière, fin dorsale) déclenchant la duplication par symétrie.

Le skill `prompt-taxonomy-ecosystem` règle T9 (`references/techniques.md`) documente précisément ce pattern et propose un fix validé hors-circuit :

> Le modèle perd la cohérence du point de vue sur tout élément qui s'étend derrière le sujet → duplication symétrique. Contraintes de comptage inefficaces. Fix : Profil strict + orientation directionnelle explicite.
>
> Formule : `one single [sujet] in profile facing [left/right], [élément] pointing/curving [direction]`

## Objectif

Transférer T9 dans `src/services/prompt_generator.py` (templates `template_solo_animal` et `template_solo_fish`) pour que les morphologies à élément étendu soient générées en profil strict + orientation directionnelle. Mesurer la réduction du défaut sur les 6 leafs résiduels.

## Périmètre

**Modifier** :

- `src/services/prompt_generator.py` :
  - Ajouter une constante `_RISKY_BACKWARD_ELEMENTS` (vocabulaire skill T9 : `tail_ample`, `long_neck`, `mane`, `dorsal_fin`, `extended_limb`, etc.)
  - Ajouter un mapping `_DIRECTIONAL_OVERRIDES: dict[str, dict]` couvrant au minimum les 6 leafs résiduels :
    ```python
    _DIRECTIONAL_OVERRIDES = {
        "bactrian_camel":   {"facing": "right", "backward": "tail curving right"},
        "golden_retriever": {"facing": "left",  "backward": "tail curving left"},
        "mountain_gorilla": {"facing": "right", "backward": None},
        "playful_dolphin":  {"facing": "left",  "backward": "tail and dorsal fin pointing left"},
        "running_cheetah":  {"facing": "right", "backward": "tail extended right"},
        "running_giraffe":  {"facing": "right", "backward": "neck and tail extended right"},
    }
    ```
  - Modifier `template_solo_animal` et `template_solo_fish` :
    - Si `leaf_id in _DIRECTIONAL_OVERRIDES` → injecter `in profile facing [left/right]` + clause `backward` au lieu de `standing in profile` ou équivalent.
    - Sinon : conserver le comportement actuel (l'isolation existante reste en place).
  - **Priorité override** : `LEAF_OVERRIDES` (existant) > `_DIRECTIONAL_OVERRIDES` (nouveau) > template par défaut. Ne pas casser `sheep_with_lamb` ni `eid_al_adha_sheep`.
- `tests/test_prompt_generator.py` :
  - Test : les 6 leafs résiduels produisent un positive contenant `facing [direction]`.
  - Test non-régression : `sheep_with_lamb` et `eid_al_adha_sheep` continuent d'utiliser leur `LEAF_OVERRIDE` (vérifier l'ordre de priorité).
  - Test non-régression : un leaf Solo animal hors mapping (ex: `cat`) garde son template standard.

**Ne pas modifier** :

- `NEGATIVE_V3` (transfert dédié si besoin futur).
- Les autres templates (`template_solo_human`, `template_solo_object`, etc.) — transfert _ISOLATION élargi traité dans un brief séparé (cf. démarche).

## Critères d'acceptation

- 6 leafs résiduels génèrent un positive avec `facing [direction]` après modif.
- Tests pytest verts (24+ existants + nouveaux).
- `sheep_with_lamb` et `eid_al_adha_sheep` continuent de fonctionner (LEAF_OVERRIDE prioritaire).
- Citation T9 en commentaire de code (référence `references/techniques.md`).

**Mesure post-transfert (optionnelle, si temps)** :

- Rerun ComfyUI sur les 6 leafs résiduels (1 image / leaf, seed offset +200).
- Annoter manuellement avec la grille v2 (au moins le tag `image_duplication`).
- Comparer image_duplication v3 vs v2 : 6/13 → cible < 2/13.
- Si la mesure n'est pas faite, signaler dans le rapport pour que l'archi la planifie.

## Reporting

Rapport obligatoire : `docs/reports/2026-05-10_transfert-skill-T9-orientation-directionnelle.md`
Sections : Contexte / Modifications / Tests / Mesure post-transfert (ou "à planifier") / Décision (Go pour les briefs T2+T3+T23 et T25 si ce transfert n'a pas révélé de blocage structurel).

## Conventions à respecter

- Reporting daté `docs/reports/YYYY-MM-DD_transfert-skill-<règle>-<sujet>.md`.
- NULL-safe : `int(w) if w is not None else 0` avant tri si applicable.
- Tests SQLite-portables (in-memory).
- Placeholders SQL `?` via `DBConnAdapter` (non concerné ici).
- Citation T9 en commentaire de code.

## Hors scope

- Étendre `_DIRECTIONAL_OVERRIDES` au-delà des 6 leafs résiduels (extension par PR ultérieure).
- Modifier `NEGATIVE_V3` (transfert dédié).
- Transfert _ISOLATION aux templates non-Solo-animal (brief séparé).
- Régénération massive du corpus (uniquement les 6 leafs résiduels en mesure post si possible).

## Estimation

~30-45 min dev + tests + rapport.

Si dépassement marqué : signaler à l'archi via le rapport et proposer un découpage.
