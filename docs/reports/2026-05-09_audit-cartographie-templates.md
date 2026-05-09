# Audit — cartographie & templates PromptGenerator
Date : 2026-05-09

## Contexte

Audit du dispatcher de templates dans `docs/xchange/prompt_generator.py` couplé
à `docs/xchange/taxonomy_production_cartography.json` (et sa copie active
`data/prompt_generator/taxonomy_production_cartography.json`).

**Cas déclencheur :** la classe `Solo animal` utilise un template générique :

```
one single {name} standing in profile, full body view,
all four legs visible on the ground, simple ground line, ...
```

Ce template impose **« four legs visible on the ground »** à tous les sujets, ce qui
est anatomiquement incorrect pour les insectes (6 pattes), araignées (8 pattes),
poissons / mammifères marins (pas de pattes — nageoires), oiseaux (perchés ou
en vol, 2 pattes au mieux) et reptiles non-quadrupèdes (tortue vue dessus,
serpent enroulé, crocodile au sol allongé).

## Périmètre

11 sous-catégories sont actuellement classées `Solo animal` :

| Sous-catégorie | #leaves | Composition | Verdict |
|---|---:|---|---|
| `pet_animals` | 15 | 14 mammifères + 1 reptile (`pet_turtle`) | ⚠ 1 outlier |
| `farm_animals` | 12 | 7 mammifères + 5 oiseaux (rooster, hen, duck, goose, turkey) | ⚠ mixte fort |
| `african_wild_animals` | 13 | 13 mammifères | ✅ adapté |
| `asian_wild_animals` | 10 | 9 mammifères + 1 reptile (`komodo_dragon`) | ⚠ 1 outlier |
| `american_wild_animals` | 12 | 11 mammifères + 1 oiseau (`bald_eagle`) | ⚠ 1 outlier |
| `arctic_animals` | 9 | 6 mammifères + 2 oiseaux (`emperor_penguin`, `snowy_owl`) + 1 mammifère marin (`beluga_whale`) | ⚠ 3 outliers |
| **`marine_animals`** | 15 | 0 mammifère 4-pattes (poissons, baleines, dauphins, octopus, méduses, etc.) | ❌ totalement inadapté |
| **`insects_and_minibeasts`** | 12 | 6/8 pattes, ailes, vol — pas « 4 legs on ground » | ❌ totalement inadapté |
| **`birds`** | 14 | Bec, plumes, perchés ou en vol | ❌ totalement inadapté |
| `dinosaurs_and_prehistoric` | 12 | 10 dinos 4-pattes + 1 volant (`flying_pterodactyl`) + 1 œuf (`dinosaur_egg_in_nest`) | ⚠ 2 outliers |
| `fantasy_animals` | 12 | Variable : licorne/centaure/sirène/phénix/dragon/yeti… | ⚠ très variable |

## Corrections appliquées

### 1. Nouvelles fonctions de template — `docs/xchange/prompt_generator.py`

Ajout de **4 fonctions** (`template_solo_insect`, `template_solo_fish`, `template_solo_bird`, `template_solo_reptile`) avec sous-routage interne par sous-string du `name_en` pour gérer les variations morphologiques au sein de chaque grand groupe.

Ajout de **4 entrées** dans `TEMPLATE_DISPATCHER` (juste après `Solo animal`) :

```python
"Solo insect":  template_solo_insect,
"Solo fish":    template_solo_fish,
"Solo bird":    template_solo_bird,
"Solo reptile": template_solo_reptile,
```

### 2. Mise à jour cartographie (les 2 copies)

Édition appliquée atomiquement (`.tmp` → `Path.replace`) sur :
- `data/prompt_generator/taxonomy_production_cartography.json` (copie active)
- `docs/xchange/taxonomy_production_cartography.json` (source)

| Sous-catégorie | `production_strategy.class` avant | après |
|---|---|---|
| `insects_and_minibeasts` | `Solo animal` | **`Solo insect`** |
| `marine_animals` | `Solo animal` | **`Solo fish`** |
| `birds` | `Solo animal` | **`Solo bird`** |

Aucune autre modification (pas de touche aux `technique`, `pitfalls`, `notes`, `pipeline`, `confidence`).

### 3. Templates avant / après

#### Solo insect (`insects_and_minibeasts`)

**Avant** (générique, hérité de `Solo animal`) :
```
one single {name} standing in profile, full body view,
all four legs visible on the ground, simple ground line,
off-center composition, friendly expression
```

**Après** (`template_solo_insect`, avec sous-routage par nom) :
```
one single {name}, top view,
{6 legs / 8 legs spider / 0 legs snail|worm / scorpion+stinger / 6 legs+wings spread},
on a simple leaf or flower,
off-center composition, friendly expression
```

Sous-routage spécifique :
- `*spider*` → `eight legs clearly visible`
- `*snail*`, `*worm*` → `no legs, soft body fully visible`
- `*scorpion*` → `eight legs and curved tail with stinger clearly visible`
- `*ant*`, `*bee*`, `*ladybug*`, `*beetle*`, `*mantis*`, `*grasshopper*` → `six legs clearly visible`
- défaut (papillons, libellules…) → `six legs and wings spread open clearly visible`

#### Solo fish (`marine_animals`)

**Avant** : générique 4-legs.

**Après** (`template_solo_fish`, avec sous-routage par nom) :
```
one single {name}, {body_clause}, {env_clause},
off-center composition, friendly expression
```

Sous-routage :
- `*octopus*`, `*squid*`, `*kraken*` → tentacles spread + bubbles
- `*jellyfish*` → bell-shaped + flowing tentacles + bubbles
- `*starfish*` → 5 arms top view + seabed
- `*crab*`, `*lobster*` → all legs+claws top view + ground
- `*turtle*` → shell+4 flippers side view swimming + water line
- `*seahorse*` → curled tail upright + bubbles
- `*whale*`, `*dolphin*`, `*orca*` → side view swimming + water line
- défaut (poissons) → side view swimming + fins+tail + water line

#### Solo bird (`birds`)

**Avant** : générique 4-legs.

**Après** (`template_solo_bird`, respecte l'**Insight D** — flying DOIT être explicite) :
```
one single {name}, {body_clause}, {env_clause},
off-center composition, friendly expression
```

Sous-routage :
- `*flying*`, `*soaring*`, `*hunting*`, `*running*`, `*rising*` → `flying with wings spread open and body horizontal in flight pose, tail feathers fan visible, beak forward` + cloud/sky line (no ground)
- `*open tail*`, `*peacock*` → tail fan spread + standing + ground line
- `*in cage*` → perched on bar inside cage frame
- `*in lake*`, `*on pond*`, `*in pond*` → standing in shallow water + water line at legs
- `*in jungle*`, `*with flower*`, `*on branch*`, `*robin*`, `*lovebird*` → perched on branch (no ground)
- défaut → standing on ground + 3/4 view + folded wings

#### Solo reptile (template prêt mais **non encore activé** sur une sous-catégorie)

Aucune sous-catégorie n'est actuellement `Solo reptile` parce qu'aucun cluster homogène de reptiles n'existe (les reptiles sont disséminés dans `pet_animals`, `asian_wild_animals`). Le template est prêt et appelable via le dispatcher si on décide plus tard de re-router des leaves spécifiques. Sous-routage prévu :

- `*turtle*`, `*tortoise*` → top view + shell + 4 short legs
- `*snake*`, `*serpent*`, `*python*`, `*cobra*` → coiled spiral + scales + head raised
- `*crocodile*`, `*alligator*` → side view horizontal + 4 legs + long tail + jaws closed
- `*komodo*`, `*lizard*`, `*gecko*`, `*chameleon*`, `*iguana*` → side view + 4 legs splayed + tail
- défaut → side view + all visible limbs

## Vérification empirique

### `monarch_butterfly` (test cible demandé)

```
$ cd docs/xchange && python prompt_generator.py --leaf monarch_butterfly
…
Classe : Solo insect
POSITIVE PROMPT:
coloring book page for kids, black and white line art, thick clean outlines,
no shading, no fill, white background, one single monarch butterfly, top view,
six legs and wings spread open clearly visible, on a simple leaf or flower,
off-center composition, friendly expression
```

✅ La phrase « four legs visible on the ground » a **disparu**, remplacée par
« six legs and wings spread open clearly visible, on a simple leaf or flower ».

### Spot-check sur 5 autres leaves

| Leaf | Classe routée | Extrait positive | Verdict |
|---|---|---|---|
| `playful_dolphin` | Solo fish | `side view, swimming horizontally, fins and tail clearly visible, simple water line at bottom` | ✅ |
| `clownfish_in_anemone` | Solo fish | `side view, swimming horizontally, fins and tail clearly visible, simple water line at bottom` | ✅ |
| `garden_spider` | Solo insect | `top view, eight legs clearly visible, on a simple leaf or flower` | ✅ |
| `soaring_eagle` | Solo bird | `flying with wings spread open and body horizontal in flight pose, tail feathers fan visible, beak forward, no ground, simple cloud or sky line for context` | ✅ Insight D respecté |
| `peacock_with_open_tail` | Solo bird | `standing with tail feathers spread wide open in a fan, three-quarter view, beak visible, simple ground line at bottom` | ✅ |
| `sea_turtle_swimming` | Solo fish | `shell and four flippers clearly visible, side view, swimming, simple water line at bottom` | ✅ |

### Régression contrôlée — mammifères 4-pattes inchangés

| Leaf | Classe | Verdict |
|---|---|---|
| `golden_retriever` | Solo animal | ✅ template d'origine (4 pattes au sol — correct pour un chien) |
| `dairy_cow` | Solo animal | ✅ idem |
| `polar_bear_on_ice` | Solo animal | ✅ idem |

## Outliers connus — non corrigés dans cet audit

Ces leaves restent rattachées à une sous-catégorie `Solo animal` dont le template
générique ne leur convient pas. Pour les corriger, il faudrait soit :
1. **Sortir la leaf vers une autre sous-catégorie** (refactor taxonomie),
2. **Ajouter un mécanisme `template_override` par leaf** dans la cartographie
   (nouveau champ `production_strategy.leaf_overrides`), ce qui demande une
   évolution du dispatcher dans `prompt_generator.py`,
3. **Subdiviser la sous-catégorie** (ex. séparer farm_animals_mammals vs
   farm_animals_birds), ce qui change la structure taxonomie publique.

| Leaf | Sous-cat actuelle | Problème | Template idéal |
|---|---|---|---|
| `pet_turtle` | `pet_animals` | Tortue ≠ 4 pattes au sol classique | Solo reptile (turtle variant) |
| `rooster`, `hen_with_chicks`, `duck_in_pond`, `farm_goose`, `turkey_bird` | `farm_animals` | Oiseaux ≠ 4 pattes | Solo bird |
| `komodo_dragon` | `asian_wild_animals` | Reptile au sol | Solo reptile (lizard variant) |
| `bald_eagle` | `american_wild_animals` | Oiseau en vol | Solo bird (flying variant) |
| `emperor_penguin`, `snowy_owl` | `arctic_animals` | Oiseaux | Solo bird |
| `beluga_whale` | `arctic_animals` | Mammifère marin | Solo fish (whale variant) |
| `flying_pterodactyl` | `dinosaurs_and_prehistoric` | Vol, pas 4 pattes au sol | Solo bird (flying variant) |
| `dinosaur_egg_in_nest` | `dinosaurs_and_prehistoric` | Œuf statique | Solo objet |
| `swimming_mermaid`, `kraken_sea_monster`, `loch_ness_monster` | `fantasy_animals` | Pas 4 pattes, créature aquatique | Solo fish (variant fantasy) |
| `rising_phoenix`, `fairy_with_wings` | `fantasy_animals` | Créature volante | Solo bird (variant fantasy) |
| `centaur` | `fantasy_animals` | Humanoïde | Solo humain ou Humain + entité |

→ **Recommandation** : ouvrir un suivi pour ajouter le mécanisme `leaf_overrides`
dans `production_strategy` (option 2 ci-dessus). C'est la moins invasive et
préserve la structure publique de la taxonomie. Estimation : ~30 min de patch
sur `prompt_generator.PromptGenerator.build_prompt` + 12-15 entrées d'override
à curer manuellement dans la cartographie.

## Résumé chiffré

- **3 sous-catégories** ré-routées vers de nouvelles classes (insects, marine, birds).
- **41 leaves** (12 + 15 + 14) bénéficient d'un template adapté à leur morphologie.
- **4 fonctions de template** ajoutées au générateur (`solo_insect`, `solo_fish`, `solo_bird`, `solo_reptile`).
- **~12-15 leaves outliers** restent dans une mauvaise classe (à traiter en suivi
  via mécanisme `leaf_overrides` ou refactor taxonomie).
- **0 régression** sur les mammifères 4-pattes (golden_retriever, dairy_cow,
  polar_bear vérifiés inchangés).

## Annexes

- Fichiers modifiés :
  - `docs/xchange/prompt_generator.py` (ajout 4 fonctions + 4 entrées dispatcher)
  - `docs/xchange/taxonomy_production_cartography.json` (3 classes changées, écriture atomique)
  - `data/prompt_generator/taxonomy_production_cartography.json` (idem, copie active)
- Commande de vérif : `cd docs/xchange && python prompt_generator.py --leaf monarch_butterfly`
- Pas de modification : `coloring_taxonomy_full.json`, `coloring_taxonomy_seo.json`, `prompt_generation_checklist_v2.2.md`.
