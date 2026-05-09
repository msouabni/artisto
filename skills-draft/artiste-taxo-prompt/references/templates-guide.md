# Guide des templates PromptGenerator

Tous les templates sont dans `src/services/prompt_generator.py`.
Tous les templates Solo incluent `_ISOLATION` en fin de positif depuis 2026-05-09.

## STYLE_BLOCK (immuable)

```
"coloring book page for kids, black and white line art,
thick clean outlines, no shading, no fill, white background"
```

## template_solo_animal

**Classes cibles** : Solo animal (mammifères 4 pattes)

**Structure** :
```
{STYLE_BLOCK}, one single {name} standing in profile, full body view,
all four legs visible on the ground, simple ground line,
off-center composition, friendly expression, {_ISOLATION}
```

**Exemple** — `lion_in_savanna` :
```
coloring book page for kids, black and white line art, thick clean outlines,
no shading, no fill, white background, one single lion in savanna standing
in profile, full body view, all four legs visible on the ground, simple
ground line, off-center composition, friendly expression, isolated subject,
no other animals or objects nearby
```

**Risques** : 2_objets (companion animal), 3_jambes si running_* (pose dynamique)

**Fix possible** : Pour feuilles avec pose risquée (running_cheetah, running_giraffe), ajouter LEAF_OVERRIDE avec pose statique explicite.

---

## template_solo_insect

**Classes cibles** : Solo insect (insectes, araignées, scorpions)

**Pattes adaptatives** :
- spider, scorpion → 8 pattes
- snail, worm → pas de pattes
- ant, bee, ladybug, beetle, mantis, grasshopper → 6 pattes
- autre → 6 pattes + ailes ouvertes

**Structure** :
```
{STYLE_BLOCK}, one single {name}, top view,
{legs_clause}, on a simple leaf or flower,
off-center composition, friendly expression, {_ISOLATION}
```

---

## template_solo_fish

**Classes cibles** : Solo fish (poissons, mammifères marins, céphalopodes, crustacés)

**Corps/environnement adaptatifs** :
| Morphologie | body_clause | env_clause |
|-------------|------------|------------|
| octopus, squid, kraken | tentacles spread, side view | simple water bubbles |
| jellyfish | bell-shaped body, tentacles below | simple water bubbles |
| starfish | five arms, top view | on seabed line |
| crab, lobster | all legs visible, top view | on ground line |
| turtle | shell + 4 flippers, side view, swimming | simple water line |
| seahorse | curled tail, upright | simple water bubbles |
| whale, dolphin, orca | side view, horizontal, fins+tail | simple water line |
| autre | side view, swimming | simple water line |

---

## template_solo_bird

**Classes cibles** : Solo bird

**Pose adaptative selon le nom** :
| Mots-clés dans le nom | Pose |
|----------------------|------|
| flying, soaring, hunting, running, rising | En vol, ailes déployées |
| open tail, peacock | Queue étalée en éventail |
| in cage | Perché sur barreau dans cage |
| in lake, on pond, in pond | Debout dans l'eau, pattes visibles |
| in jungle, with flower, on branch, robin, lovebird | Perché sur branche |
| autre | Debout au sol, 3/4 vue |

**Insight critique** : Un oiseau "en vol" DOIT préciser `"wings spread open and body horizontal in flight pose"`, sinon ERNIE rabat sur pose de repos.

---

## template_solo_reptile

**Classes cibles** : Solo reptile

**Morphologie adaptative** :
- turtle, tortoise → top view, shell visible, 4 pattes
- snake, serpent, python, cobra → coiled, top view, head raised
- crocodile, alligator → side view, horizontal, 4 pattes + queue
- komodo, lizard, gecko, chameleon, iguana → side view, 4 pattes écartées

---

## template_solo_human

**Classes cibles** : Solo humain (générique), Solo humain + accessoires

**Structure** :
```
{STYLE_BLOCK}, one single {name}, three-quarter view from the side,
full body, simple ground line, off-center composition, friendly expression
```

**Note** : Pas de _ISOLATION (l'accessoire fait partie du sujet).

---

## template_solo_object

**Classes cibles** : Solo objet, Solo objet (véhicule), fallback universel

**Structure** :
```
{STYLE_BLOCK}, one {name} centered on the page,
viewed from a clear three-quarter angle, all main features fully visible,
simple ground line beneath, clean uncluttered composition
```

---

## LEAF_OVERRIDES — Cas spéciaux

Dict dans `src/services/prompt_generator.py` → override complet du positif pour les leaf_ids listés.

**Actuellement définis :**

| leaf_id | Raison | Override |
|---------|--------|---------|
| sheep_with_lamb | Nom implique 2 animaux | Adult sheep + small lamb outline tucked close (même poids de trait) |
| eid_al_adha_sheep | Contexte religieux → décoration | Decorated sheep + festive ribbon around neck |

**Pour ajouter un override** :
```python
LEAF_OVERRIDES["running_cheetah"] = (
    f"{STYLE_BLOCK}, one single running cheetah in a low-speed trot, "
    "full body side view, all four legs touching the ground at midstride, "
    "simple ground line, off-center composition, friendly expression, "
    + _ISOLATION
)
```

## TEMPLATE_DISPATCHER — Mapping class → template

```python
{
    "Solo animal": template_solo_animal,
    "Solo insect": template_solo_insect,
    "Solo fish": template_solo_fish,
    "Solo bird": template_solo_bird,
    "Solo reptile (hors tortue)": template_solo_reptile,
    "Solo humain en action": template_solo_human,
    "Solo humain + accessoires": template_solo_human,
    "Solo humain (générique)": template_solo_human,
    "Solo humain en pose": template_solo_human,
    "Solo humain pose active": template_solo_human,
    "Solo objet": template_solo_object,
    "Solo objet (véhicule)": template_solo_object,
    # ...
    # Fallback pour toute classe sans dispatcher → template_solo_object
}
```
