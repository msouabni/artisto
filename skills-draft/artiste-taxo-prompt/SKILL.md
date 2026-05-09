---
name: artiste-taxo-prompt
description: >
  Skill pour le projet Artiste Coloriage (D:\projets\artiste-coloriage). Charge automatiquement
  tout le contexte nécessaire pour travailler sur la taxonomie et les prompts ERNIE sans
  réexpliquer le projet à chaque fois. À utiliser dès que la discussion porte sur :
  la taxonomie (feuilles, sous-catégories, workflow_class, confidence), les prompts de génération
  d'image (PromptGenerator, ERNIE, templates Solo animal/insect/fish/bird/humain/objet),
  les défauts observés (2_objets, 3_jambes, prompt_incohérent, traits_flous), l'optimisation
  du NEGATIVE_V3, la création de LEAF_OVERRIDES, le benchmark annotations, ou toute discussion
  d'optimisation autour de la génération coloriage. Trigger aussi si l'utilisateur mentionne
  "taxonomie", "prompt ERNIE", "leaf", "workflow_class", "Solo animal", "coloring book",
  "benchmark annotations", ou demande de comparer/améliorer des prompts pour des feuilles spécifiques.
---

# Artiste Coloriage — Taxonomie & Prompts ERNIE

## Contexte projet

Pipeline Python : taxonomie → PromptGenerator (template, sans LLM) → ComfyUI/ERNIE → validation humaine → publication.

**Chemins clés :**
- Projet : `D:\projets\artiste-coloriage\`
- PromptGenerator : `src/services/prompt_generator.py`
- Données taxonomie : `data/prompt_generator/` (3 JSON)
- Benchmark annotations : `docs/reports/poc-scale-benchmark/annotations.json`
- Rapports : `docs/reports/`

**Lancer le PromptGenerator depuis le projet :**
```bash
cd D:\projets\artiste-coloriage
PYTHONPATH=src python -c "
from services.prompt_generator import PromptGenerator
gen = PromptGenerator()
r = gen.build_prompt('lion_in_savanna')
print(r['positive'])
print('---')
print(r['negative'])
print(r['workflow_class'], r['confidence'])
"
```

## Structure taxonomie

- **1376 feuilles** (leaf_id), organisées en catégories → sous-catégories → feuilles
- Chaque sous-catégorie a une `production_strategy` dans `taxonomy_production_cartography.json` :
  - `class` → workflow_class (ex: "Solo animal", "Solo fish", "Lettre + objet")
  - `confidence` → "Haute", "Moyenne", "Basse"
  - `technique`, `pipeline`, `resolution`, `pitfalls`, `negative_extra`
- **898 feuilles haute confiance** (65.3%) — priorité de génération

**Lister les feuilles par critère :**
```bash
cd D:\projets\artiste-coloriage && PYTHONPATH=src python -c "
from services.prompt_generator import PromptGenerator
from collections import Counter
gen = PromptGenerator()
classes = Counter()
for lid in gen.leaf_index:
    r = gen.build_prompt(lid)
    classes[r['workflow_class']] += 1
for cls, n in sorted(classes.items(), key=lambda x: -x[1])[:15]:
    print(f'{cls}: {n}')
"
```

**Workflow_classes principales :**
| Classe | Résolution | Particularité |
|--------|-----------|---------------|
| Solo animal | 1024×1024 | Mammifères 4 pattes, _ISOLATION obligatoire |
| Solo insect | 1024×1024 | Pattes adaptatives (6 ou 8 selon espèce) |
| Solo fish | 1024×1024 | Corps/env selon morphologie |
| Solo bird | 1024×1024 | Pose vol vs posée selon nom |
| Solo humain en action | 848×1264 | batch_size=3 recommandé, 3_jambes fréquent |
| Solo humain + accessoires | 1024×1024 | |
| Solo objet (véhicule) | 1376×768 | Paysage |
| Lettre + objet | 1024×1024 | 2 sujets intentionnels |

## Paramètres de génération prod (ne pas changer sans benchmark)

```
sampler : euler    steps : 8    cfg : 1.0
scheduler : normal    résolution : 1024×1024 (défaut)
```

- **karras** : banni sur sujets complexes (humains en action) — échec total validé
- **dpmpp_2m** : banni (tramage quasi-systématique)
- **cfg > 1.0** : réintroduit 3_jambes sur anatomie humaine/animale

## NEGATIVE_V3 (version courante — maj 2026-05-09)

```
"no colors, extra legs, third leg, duplicate limbs, fused legs,
malformed anatomy, wrong number of limbs, six fingers, deformed feet
no motion, no fill colors, no intersection, no change in ink
transparency for different plan only black stroke,
multiple animals, other animals, companion animal, group of animals,
animal in background, second subject, multiple subjects"
```

## Mécaniques importantes du PromptGenerator

- **`_ISOLATION`** : `"isolated subject, no other animals or objects nearby"` — ajouté en fin de positif pour tous les templates Solo (animal, insect, fish, bird, reptile)
- **`LEAF_OVERRIDES`** : dict `leaf_id → positive_override` pour feuilles à nom ambigu. Actuellement : `sheep_with_lamb`, `eid_al_adha_sheep`. Pour ajouter : éditer ce dict dans `src/services/prompt_generator.py`
- **`_RISKY_MULTI_PATTERNS`** : patterns dans le leaf_id (`_with_friend`, `_and_`, `_with_chicks`…) → renforcement automatique du négatif

## Défauts observés (196 annotations poc-scale-benchmark)

| Défaut | Cas | Cause principale | Fix |
|--------|-----|-----------------|-----|
| `2_objets` | 16 (8%) | Modèle génère second sujet | NEGATIVE_V3 étendu + _ISOLATION ✓ |
| `3_jambes` | 12 (6%) | Pose dynamique humaine/animale | cfg=1.0 + negative anatomy |
| `prompt_incohérent` | 8 (4%) | Sujet ambigu (personnalité, cartoon) | LEAF_OVERRIDES |
| `traits_flous` | 4 (2%) | Résolution trop haute pour sujet simple | Passer à 768×768 |

**Résultats globaux** : 142/196 publiables (72%). Distribution bimodale : 85 parfaits (score=10) + 29 catastrophiques (score=1).

**QC vision (3_jambes)** : qwen3.5:9b et gemma4:26b testés → **0% recall** en line-art N&B. Validation anatomie = humain uniquement.

## Référentiels disponibles

Pour une discussion approfondie, lire les fichiers de référence :

- **`references/empirical-rules.md`** : règles empiriques complètes (samplers, cfg, résolution par concept)
- **`references/templates-guide.md`** : guide détaillé de chaque template avec exemples de prompts générés
- **`references/defects-catalog.md`** : catalogue des défauts connus par workflow_class avec pistes de correction

## Mode opératoire pour une session d'optimisation

**1. Identifier les cibles :**
```bash
cd D:\projets\artiste-coloriage && PYTHONPATH=src python -c "
from services.prompt_generator import PromptGenerator
import json, pathlib
gen = PromptGenerator()
ann = json.loads(pathlib.Path('docs/reports/poc-scale-benchmark/annotations.json').read_text())
annotated = set(ann['annotations'].keys())
high_conf = gen.list_high_confidence_leaves()
print(f'Haute confiance: {len(high_conf)}, annotées: {len(annotated)}')
"
```

**2. Générer et inspecter un prompt :**
```bash
cd D:\projets\artiste-coloriage && PYTHONPATH=src python -c "
from services.prompt_generator import PromptGenerator
gen = PromptGenerator()
r = gen.build_prompt('LEAF_ID_ICI')
print('CLASS:', r['workflow_class'])
print('CONF:', r['confidence'])
print('POS:', r['positive'])
print('NEG:', r['negative'])
print('PITFALLS:', r['pitfalls'])
"
```

**3. Proposer une correction :**
- Défaut vient du template → modifier la fonction `template_solo_*` dans `src/services/prompt_generator.py`
- Défaut vient du nom de la feuille → ajouter dans `LEAF_OVERRIDES`
- Défaut systémique à une classe → modifier `NEGATIVE_V3` ou la stratégie dans `taxonomy_production_cartography.json`

**4. Valider :**
- Régénérer avec seed_original+100 pour comparer v1 vs v2
- Annoter dans `http://127.0.0.1:8000/data/benchmark-annotator.html?dir=poc-scale-benchmark`

## Exemples de discussions productives à ouvrir en parallèle

- "Optimise les templates Solo humain en action pour réduire 3_jambes"
- "Quelles feuilles Lettre + objet ont confidence Haute et n'ont pas encore été générées ?"
- "Compare les taux de réussite Solo animal vs Solo fish vs Solo insect"
- "Propose un LEAF_OVERRIDE pour running_cheetah qui limite les poses à risque"
- "Analyse les 8 cas prompt_incohérent et classifie-les par cause"
