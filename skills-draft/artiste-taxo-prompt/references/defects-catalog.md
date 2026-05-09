# Catalogue des défauts — poc-scale-benchmark (196 annotations, 2026-05-09)

## Vue d'ensemble

| Défaut | Total | % | Publishable malgré défaut |
|--------|-------|---|--------------------------|
| 2_objets | 16 | 8.2% | 2/16 (score ≥ 5) |
| 3_jambes | 12 | 6.1% | 0/12 |
| prompt_incohérent | 8 | 4.1% | 1/8 |
| traits_flous | 4 | 2.0% | 0/4 |
| perspective_KO | 1 | 0.5% | 0/1 |
| gris_résiduel | 1 | 0.5% | 1/1 |

---

## Défaut : 2_objets

**Symptôme** : L'image montre 2 animaux distincts au lieu d'un seul. Ou un sujet principal + un fond animé non désiré.

**Fix déjà appliqué (2026-05-09)** :
- NEGATIVE_V3 étendu avec `"multiple animals, other animals, companion animal, group of animals, animal in background, second subject, multiple subjects"`
- `_ISOLATION` ajouté en fin de positif sur tous les templates Solo

**Cas encore à risque :**
| leaf_id | Raison | Action recommandée |
|---------|--------|-------------------|
| running_cheetah | Pose course → "pursuit" implicite | LEAF_OVERRIDE avec trot lent |
| running_giraffe | Idem | LEAF_OVERRIDE |
| mountain_gorilla | Groupe implicite | LEAF_OVERRIDE avec contexte rocher isolé |
| playful_dolphin | "playful" → groupe | LEAF_OVERRIDE, retirer "playful" |
| chimpanzee | Groupe implicite | Ajouter `"solitary chimpanzee"` |

**Cas intentionnels (ne pas corriger)** :
- `letter_z_with_zebre` → Lettre + objet par conception
- `animal_superhero` → Animal en costume (classe Solo humain/animal cartoon)

---

## Défaut : 3_jambes

**Symptôme** : Mammifère ou humain avec un membre surnuméraire (3 pattes, 6 doigts, etc.).

**Cause** : Pose dynamique + ERNIE interprète les pattes en mouvement comme des membres distincts.

**Règle fondamentale** : cfg=1.0 obligatoire. cfg>1.0 réintroduit systématiquement le défaut.

**Cas observés :**
| leaf_id | Classe | Situation |
|---------|--------|-----------|
| captain_marvel | Solo humain | 3_jambes + prompt_incohérent |
| rapunzel_with_long_hair | Solo humain | 3_jambes + prompt_incohérent |
| lamine_yamal_cartoon | Solo humain | Cartoon footballeur en action |
| rafael_nadal_cartoon | Solo humain | Tennismen en action |
| husky_dog | Solo animal | Chien en position ambigu |
| maine_coon_cat | Solo animal | Chat en position ambigu |
| pegasus | Solo animal | Cheval volant (4 pattes + ailes) |
| running_cheetah | Solo animal | Course → pattes en mouvement |
| beluga_whale | Solo fish | Nageoires interprétées comme pattes |
| snowboarder_jump | Solo humain | Saut = pose anatomique risquée |
| tango_couple | Solo humain | Deux personnes en plus (hors scope Solo) |

**Fixes templates :**
- Humanss en action : `batch_size=3`, garder la meilleure des 3
- Animaux en course : LEAF_OVERRIDE avec pose statique ou trot lent
- Mythologiques (pegasus) : décrire explicitement le nombre de membres → `"four legs and two wings, total six appendages"`

---

## Défaut : prompt_incohérent

**Symptôme** : L'image ne correspond pas du tout au sujet — personnage différent, scène incompréhensible, ou le modèle a "halluciné" un concept non demandé.

**Cause principale** : Leaf_id correspond à un personnage célèbre, une personnalité sportive, ou un concept culturel que ERNIE ne reconnaît pas correctement.

**Cas observés :**
| leaf_id | Raison | Fix |
|---------|--------|-----|
| captain_marvel | Personnage Marvel ambigu | LEAF_OVERRIDE avec description physique explicite |
| animal_superhero | Animal + costume = concept composite | Downgrade confidence, LEAF_OVERRIDE descriptif |
| fishmonger_at_market | Scène de marché complexe | LEAF_OVERRIDE simplifié (un poissonnier seul) |
| rapunzel_with_long_hair | Long hair + tower → scène complexe | LEAF_OVERRIDE centré sur le personnage seul |
| grasshopper | Ambiguïté insecte vs personnage Grasshopper | LEAF_OVERRIDE explicite "a real grasshopper insect" |
| firefighter_with_hose_b3 | Batch 3 dégénéré | Normal sur b3, exclure de la production |
| bungee_jumper b2/b3 | Batches 2/3 dégénérés | Normal, utiliser b1 uniquement |

**Stratégie générale** :
1. Si personnalité nommée → ajouter `"a cartoon version of {sport} player wearing {team_color} jersey, solo full body"` dans LEAF_OVERRIDE
2. Si scène complexe → simplifier à `"one single {simplified_subject}"` dans LEAF_OVERRIDE
3. Si le leaf est structurellement incohérent → downgrade confidence à "Basse" dans cartographie

---

## Défaut : traits_flous

**Symptôme** : Contours imprécis, traits qui se fondent les uns dans les autres, manque de clarté sur les détails fins.

**Cause** : Résolution trop haute pour un sujet simple, ou sujet trop petit dans l'image.

**Cas observés :** `dairy_cow` (1024×1024, objet simple)

**Fix** : Passer à 768×768 pour les sujets simples (objets, animaux sans détails fins). Ajouter `"768x768"` dans la stratégie de la sous-catégorie concernée dans `taxonomy_production_cartography.json`.

---

## Défaut : gris_résiduel

**Symptôme** : Zones grises sur l'image (pas des vrais noirs ou blancs purs).

**Cause** : Steps trop élevés (20s) sur sujets simples.

**Fix** : Rester à 8 steps euler. Pour les scènes complexes où 20s est utilisé, accepter le gris résiduel ou ajouter `"pure black strokes only, stark contrast"` dans le positif.

---

## Requêtes utiles d'analyse

**Taux de réussite par workflow_class :**
```python
import json
from pathlib import Path
from collections import defaultdict

ann_data = json.loads(Path("docs/reports/poc-scale-benchmark/annotations.json").read_text())
annotations = ann_data["annotations"]

# Charger les class depuis les index
import sys; sys.path.insert(0, "src")
from services.prompt_generator import PromptGenerator
gen = PromptGenerator()

results = defaultdict(lambda: {"ok": 0, "ko": 0})
for filename, ann in annotations.items():
    leaf_id = filename.replace("_1024x1024_euler8s.png", "").replace("_848x1264_euler8s.png", "").replace("_1376x768_euler8s.png", "")
    # simplification: strip suffixes
    leaf_id = leaf_id.split("_b")[0]  # remove batch suffix
    try:
        r = gen.build_prompt(leaf_id)
        cls = r["workflow_class"]
    except:
        cls = "UNKNOWN"
    if ann.get("publishable"):
        results[cls]["ok"] += 1
    else:
        results[cls]["ko"] += 1

for cls, r in sorted(results.items(), key=lambda x: -(x[1]["ok"]+x[1]["ko"])):
    total = r["ok"] + r["ko"]
    pct = 100 * r["ok"] / total if total else 0
    print(f"{cls}: {r['ok']}/{total} ({pct:.0f}%)")
```
