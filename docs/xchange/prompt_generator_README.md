# Prompt Generator — Mode d'emploi

Générateur automatique de prompts pour la plateforme coloriage Alwan Books.

Lit la taxonomie + cartographie + SEO et produit des prompts conformes à la
checklist v2.2 pour ERNIE-Image-Turbo Q8 dans ComfyUI.

---

## Installation

Le générateur a besoin de 3 fichiers de données dans le même dossier :

```
mon_dossier/
├── prompt_generator.py
├── coloring_taxonomy_full.json          # taxonomie complète
├── taxonomy_production_cartography.json # cartographie (livrable 2)
└── coloring_taxonomy_seo.json           # SEO enrichi (optionnel)
```

Le script ne nécessite aucune dépendance externe — uniquement la stdlib Python 3.7+.

---

## Utilisation en CLI

### Statistiques globales

```bash
python prompt_generator.py --stats
```

Sortie :
```
Total feuilles : 1376
Feuilles haute confiance : 898 (65.3%)
```

### Générer un prompt pour une feuille

```bash
python prompt_generator.py --leaf lion_in_savanna
```

Sortie complète avec :
- Métadonnées (catégorie, sous-catégorie)
- Classe, technique, pipeline, confiance
- Résolution recommandée
- Pièges connus pour cette catégorie
- Prompt positif prêt à coller
- Prompt négatif (v3 + extras spécifiques)
- Données SEO si disponibles

### Générer un workflow ComfyUI complet

```bash
python prompt_generator.py --leaf lion_in_savanna --workflow lion_workflow.json
```

→ Crée un fichier JSON ComfyUI prêt à drag&drop dans l'interface, avec :
- Le bon modèle (ERNIE-Turbo Q8)
- La résolution adaptée à la classe (1024² ou 848×1264 ou 1376×768)
- Le negative prompt v3 + extras
- Le positive prompt généré
- Le préfixe de fichier `alwan_<leaf_id>` pour retrouver tes générations

### Générer tous les prompts d'une sous-catégorie

```bash
python prompt_generator.py --subcategory african_wild_animals --output animals.json
```

→ Crée un fichier JSON contenant tous les prompts de la sous-catégorie.

### Générer un lot prédéfini

```bash
# Toutes les feuilles haute confiance (898 prompts)
python prompt_generator.py --batch high_confidence --output high_conf_batch.json

# Toutes les feuilles (1376 prompts, inclut celles à pipeline alternatif)
python prompt_generator.py --batch all --output full_batch.json
```

---

## Utilisation en API Python

```python
from prompt_generator import PromptGenerator

# Initialisation (charge les 3 JSON une fois)
gen = PromptGenerator()

# Générer un prompt
result = gen.build_prompt("lion_in_savanna")
print(result['positive'])
print(result['negative'])
print(f"Résolution : {result['resolution']}")

# Générer un workflow ComfyUI
gen.build_workflow_json("lion_in_savanna", "lion_workflow.json")

# Générer en lot
leaf_ids = ["lion_in_savanna", "monarch_butterfly", "firefighter_with_hose"]
results = gen.batch(leaf_ids)
for r in results:
    if 'error' in r:
        print(f"Erreur sur {r['leaf_id']} : {r['error']}")
    else:
        print(f"{r['leaf_name_en']} : {r['positive'][:80]}...")

# Lister les feuilles haute confiance
high = gen.list_high_confidence_leaves()
print(f"{len(high)} feuilles haute confiance")
```

---

## Structure du résultat

Chaque prompt généré retourne un dictionnaire avec les champs suivants :

| Champ | Description |
|---|---|
| `leaf_id` | ID unique de la feuille |
| `leaf_name_en` / `leaf_name_fr` / `leaf_name_ar` | Noms multilingues |
| `subcategory_id` / `subcategory_name` | Sous-catégorie d'appartenance |
| `category_root` | Catégorie racine |
| `positive` | Prompt positif prêt à utiliser |
| `negative` | Prompt négatif (v3 + extras spécifiques) |
| `resolution` | Tuple (width, height) — par exemple (1024, 1024) ou (848, 1264) |
| `workflow_class` | Classe de prompt selon checklist (Solo animal, Humain+entité, etc.) |
| `technique` | Pattern de composition appliqué |
| `pipeline` | ERNIE direct / SVG / Composition PIL / Hybride |
| `confidence` | Niveau de confiance basé sur les tests empiriques |
| `pitfalls` | Liste des pièges connus pour cette catégorie |
| `notes` | Notes éditoriales |
| `seo` | Données SEO (volume, priorité multilingue, saisonnalité) si dispo |

---

## Workflow recommandé pour produire en masse

### Phase 1 — Pilote sur 10-20 feuilles

```bash
# Génère les workflows pour quelques feuilles ciblées
for leaf in lion_in_savanna firefighter_with_hose fruit_imagier_with_names; do
    python prompt_generator.py --leaf $leaf --workflow ${leaf}_wf.json
done
```

Charge les 3 fichiers dans ComfyUI, génère, valide la qualité.

### Phase 2 — Production par sous-catégorie

Une fois la qualité validée sur le pilote :

```bash
# Génère tous les prompts d'une sous-catégorie qu'on attaque en masse
python prompt_generator.py --subcategory african_wild_animals --output animals.json

# Tu peux ensuite itérer en Python pour créer les workflows
python -c "
from prompt_generator import PromptGenerator
import json

gen = PromptGenerator()
with open('animals.json') as f: prompts = json.load(f)

for p in prompts:
    if 'error' not in p:
        gen.build_workflow_json(p['leaf_id'], f\"workflows/{p['leaf_id']}.json\")
"
```

### Phase 3 — Production en lot stratégique

Croise avec les données SEO pour identifier les quick wins :

```python
from prompt_generator import PromptGenerator

gen = PromptGenerator()
high_conf = gen.list_high_confidence_leaves()

# Filtre par bucket SEO
priority_leaves = []
for lid in high_conf:
    p = gen.build_prompt(lid)
    if p.get('seo') and p['seo']['volume_bucket'] in ('very_high', 'high'):
        priority_leaves.append(lid)

print(f"{len(priority_leaves)} feuilles prioritaires (haute confiance + haut volume SEO)")
```

---

## Limitations et améliorations possibles

### Ce que le générateur fait

- Construit un prompt baseline conforme à la checklist v2.2
- Applique le bon pattern selon la classe de la sous-catégorie
- Adapte la résolution selon le sujet
- Ajoute les negatives spécifiques connus
- Préserve les pièges et notes pour rappel

### Ce qu'il ne fait pas (volontairement)

- **Personnalisation fine par feuille** : le template applique un pattern générique pour la sous-catégorie. Pour des feuilles particulièrement complexes (`life_cycle_full_poster`, `solar_system_with_planets`), un prompt manuel sera meilleur.
- **Pipeline alternatif** : pour les feuilles en SVG/PIL, le template indique simplement le pipeline à utiliser sans générer le prompt ERNIE (qui n'aurait pas de sens).
- **Itération sur résultats** : le template ne réécrit pas les prompts en fonction des résultats de génération précédents. C'est à toi de noter les feuilles qui marchent moins bien et d'enrichir leur entrée dans la cartographie.

### Pistes d'amélioration

Si tu veux pousser plus loin :

1. **Enrichir les templates** par feuille : actuellement c'est par sous-catégorie. Tu peux ajouter dans la cartographie un champ `leaf_specific_overrides` qui surcharge le template générique pour des feuilles particulières.

2. **Apprentissage par feedback** : après génération, noter manuellement le résultat (1-10) et enrichir un fichier de feedback. Les feuilles ayant échoué peuvent recevoir un override spécifique au prochain run.

3. **Variantes de seed** : générer 4 versions de chaque feuille (4 seeds différents) pour avoir le choix.

4. **Pipeline alternatif intégré** : pour les cas SVG (zellige, géométrie 3D), créer des templates SVG paramétrés appelés automatiquement.

---

## Liens vers les autres livrables

| Livrable | Fichier | Usage |
|---|---|---|
| 1. Checklist | `prompt_generation_checklist_v2.2.md` | Guide stratégique pour comprendre les patterns |
| 2. Cartographie | `taxonomy_production_cartography.{json,xlsx,md}` | Décisions éditoriales et stratégies par sous-catégorie |
| 3. **Générateur (ce fichier)** | `prompt_generator.py` | Production automatisée des prompts |
| Bonus | `sample_prompts_validation.md` | 15 prompts validés empiriquement |

---

## Validation empirique

Le générateur a été validé sur 898 feuilles haute confiance (65.3% de la taxonomie totale) sans erreur de génération.

Distribution par classe sur les 898 prompts générés :
- Solo objet : 126
- Solo animal : 110
- Solo humain en action : 63
- Solo humain + accessoires : 55
- Solo objet (véhicule) : 37
- Solo humain (personnalité) + action figée : 28
- Lettre + objet : 26
- ... et 9 autres classes

Tous les prompts sortent prêts à coller dans ComfyUI avec leur résolution adaptée et leur negative spécifique. La qualité du prompt généré dépend de la qualité du template de sa classe — qui peut être amélioré au fil des productions et des retours empiriques.
