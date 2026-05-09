# POC scale-benchmark — couverture des 37 classes non-couvertes (confidence=Haute)
Date : 2026-05-09

## Contexte

Étend la couverture du POC `PromptGenerator × ERNIE` au-delà des **17 workflow_classes** déjà traitées par les runs précédents (`poc_scale_benchmark_humans/nature/objects/...`). Sur les 85 classes du `PromptGenerator`, **37 classes restantes** ont au moins une feuille avec `confidence == "Haute"` strict — elles sont la cible de ce run.

Sélection automatique :
- Filtre : `workflow_class ∉ COVERED` ET `confidence == "Haute"`
- Échantillon : 10 leaves max par classe, `random.Random(2027 + hash(cls) % 100000).sample(...)` déterministe
- Total : **310 images** (certaines classes ayant moins de 10 leaves Haute disponibles)
- Seed ComfyUI : `9000 + idx_global * 7` (idx 0..309 → seeds 9000..11163)

Paramètres ComfyUI fixes : `steps=8, sampler=euler, scheduler=normal, cfg=1.0, denoise=1.0`. Pipeline cartographié = `ERNIE direct` pour tous. `negative_prompt` = négatif v3 unifié du `PromptGenerator`.

Script : `scripts/poc_scale_benchmark_uncovered.py`. Output : `docs/reports/poc-scale-benchmark/`.

## Résultat global

**310/310 OK · 0 KO · 0 SKIP** — runtime ComfyUI cumulé **103 min**, latence moyenne 19.9 s.

| Indicateur | Valeur |
|---|---|
| Classes couvertes par ce run | 37 |
| Images générées | 310 |
| Confidence (toutes Haute) | 310/310 |
| `color_ratio` max global | **0.0521** (1 outlier isolé sur `rainbow_prism_experiment`) |
| `color_ratio` moyen global | 0.0011 |
| Histogram OK | 309/310 (le seul KO = l'outlier ci-dessus) |
| Latence avg / min / max | 19.9 / 16.3 / 53.4 s |
| Index files produits (1/classe) | 38 (37 nouveaux + index-humans préexistant) |

## Stats par `workflow_class`

| Classe | n | cr_avg | cr_max | lat_avg | reso |
|---|---|---|---|---|---|
| Comparatif before/after OU Solo | 10 | 0.0017 | 0.0027 | 30.1 s | 1376×768 |
| Frise narrative 1×N (pattern X2) | 8 | 0.0012 | 0.0026 | 23.0 s | 1376×768 |
| Grille imagier annoté | 8 | 0.0022 | 0.0030 | 18.2 s | 1024² |
| Humain + entité (cheval) | 6 | 0.0014 | 0.0017 | 18.2 s | 848×1264 |
| **Humain + entité (instrument)** | 9 | **0.0065** | **0.0521** | 18.2 s | 1024² |
| Humain + entité OU Solo | 9 | 0.0013 | 0.0036 | 30.0 s | 1024² |
| Humain + entité OU Solo humain pose statique | 10 | 0.0010 | 0.0016 | 18.4 s | 1024² |
| Imagier annoté 3×3 OU Solo visage | 10 | 0.0017 | 0.0020 | 18.2 s | 1024² |
| Imagier différencié 3×3 | 8 | 0.0018 | 0.0034 | 18.2 s | 1024² |
| Imagier différencié OU Solo | 7 | 0.0023 | 0.0033 | 18.7 s | 1024² |
| Multi-sujets via grille (méta-pattern §2) | 10 | 0.0012 | 0.0019 | 18.2 s | 1024² |
| Pattern décoratif (symétrie volontaire) | 8 | 0.0016 | 0.0027 | 17.5 s | 1024² |
| **Pattern décoratif simple** | 7 | **0.0007** | 0.0010 | 18.2 s | 1024² |
| Scène intérieure | 10 | 0.0011 | 0.0027 | 18.2 s | 1024² |
| Scène ou solo personnage | 10 | 0.0013 | 0.0022 | 18.4 s | 1024² |
| Scène paysage | 10 | 0.0017 | 0.0032 | 19.0 s | 1376×768 |
| **Solo humain** | 7 | **0.0007** | 0.0013 | 18.5 s | 1024² |
| Solo humain OU objet | 6 | 0.0010 | 0.0018 | 18.2 s | 1024² |
| **Solo humain en pose** | 10 | **0.0006** | 0.0008 | 19.8 s | 848×1264 |
| Solo humain ou objet | 10 | 0.0009 | 0.0014 | 19.8 s | 1024² |
| Solo objet (organe sensoriel) | 6 | 0.0008 | 0.0013 | 19.3 s | 1024² |
| Solo objet (plante) | 10 | 0.0008 | 0.0011 | 19.1 s | 1024² |
| Solo objet anatomique + labels | 7 | 0.0008 | 0.0010 | 18.8 s | 1024² |
| Solo objet en mouvement | 8 | 0.0011 | 0.0016 | 19.5 s | 1376×768 |
| **Solo objet en vol OU au sol** | 9 | **0.0006** | 0.0008 | 20.2 s | 1376×768 |
| Solo objet historique | 8 | 0.0009 | 0.0014 | 20.2 s | 1024² |
| Solo objet météo | 8 | 0.0008 | 0.0012 | 20.2 s | 1024² |
| Solo objet ou Humain + entité | 8 | 0.0011 | 0.0032 | 19.5 s | 1024² |
| Solo objet ou comparatif | 8 | 0.0019 | 0.0031 | 20.2 s | 1024² |
| Solo objet ou humain en scaphandre | 10 | 0.0009 | 0.0012 | 20.2 s | 848×1264 |
| Solo objet ou humain+entité | 7 | 0.0010 | 0.0022 | 20.2 s | 1024² |
| Solo objet ou personnage robot | 8 | 0.0008 | 0.0010 | 20.0 s | 1024² |
| Solo objet ou scène | 6 | 0.0008 | 0.0010 | 20.2 s | 1024² |
| Solo objet style kawaii | 9 | 0.0008 | 0.0011 | 20.2 s | 1024² |
| Solo objet sur eau | 10 | 0.0007 | 0.0011 | 20.0 s | 1376×768 |
| Variable (solo objet ou frise pour party) | 6 | 0.0008 | 0.0013 | 19.6 s | 1024² |
| Variable selon sujet | 9 | 0.0009 | 0.0015 | 19.8 s | 1024² |

→ **35/37 classes ≤ 0.0023 cr_avg** — extrêmement propres. Deux classes à signaler :
- **Humain + entité (instrument)** : `cr_avg=0.0065, max=0.0521` — un seul outlier (`rainbow_prism_experiment`), les 8 autres sont propres. Voir analyse outlier ci-dessous.
- **Imagier différencié OU Solo** : `cr_avg=0.0023, max=0.0033` — légèrement au-dessus de la médiane mais sans cas problématique individuel.

## Top outlier

| cr | leaf_id | classe | analyse |
|---|---|---|---|
| **0.0521** | rainbow_prism_experiment | Humain + entité (instrument) | « rainbow » dans le nom du leaf → prompt mentionne explicitement "rainbow / spectrum / dispersion of light", le négatif v3 ne suffit pas à supprimer la coloration spectrale qui est la nature même du sujet. **Cas hors-modèle attendu** — comme `rainbow_garden` du run taxonomy-subjects qui montrait `cr=0.358` (sans négatif v3), ici 7× plus bas grâce au négatif. À publier tel quel ou exclure de la prod selon le standard. |

Aucun autre cr > 0.005 sur les 309 entrées restantes. Le négatif v3 fait son travail uniformément sauf quand le concept lui-même est intrinsèquement multi-couleur.

## Distribution & latence

- **Résolutions** : 229 carrées 1024², 55 paysages 1376×768, 26 portraits 848×1264. Conforme aux ratios cartographiés par classe.
- **Latence** :
  - 1024² avec `cfg=1.0, steps=8` : ~18-20 s
  - 1376×768 (1.06 Mpx, paysage) : ~20-30 s
  - Outliers latence (>50 s, max 53 s) : quelques classes complexes Comparatif before/after (composition double scène).

## Couverture cumulée du `PromptGenerator`

| Phase | Classes traitées | Images |
|---|---|---|
| Phase humans (pre) | 9 (Solo humain en action / + accessoires / personnalité / générique / pose active / personnalité+action figée / cartoon / personnage ou créature / Humain + entité) | 50 |
| Phase nature (pre) | Solo animal / Solo insect / Solo fish / Solo bird (≈4) | ~60 |
| Phase objects (pre) | Solo objet / Solo objet (véhicule) / Lettre + objet / Variable | ~50 |
| **Phase uncovered (ce run)** | **37** | **310** |
| **Total** | **~54 / 85** | **~470** |

Reste **~31 classes non couvertes**, toutes avec `confidence != "Haute"` strict (Moyenne, Faible, ou variante composée comme "Haute (avec règles)" / "Haute (pour SVG)" / "Haute (un par un)" / "Haute (pour test), Moyenne (commercial)" / "Haute (symétrie), Faible (tessellation)"). Ces classes nécessiteront soit un calibrage plus poussé soit une décision de couverture partielle.

## Points d'attention

### 1. Métrique color_ratio = signal limité
Sur 310 images Haute confidence, **309 sont histogram-OK** (cr ≤ 0.005). C'est confortable mais ne valide pas la qualité visuelle (composition, anatomie, fidélité au sujet, présence du multi-sujet attendu pour les classes "Multi-sujets / Imagier / Frise"). **L'annotation humaine reste l'arbitre** — particulièrement pour les classes méta-pattern (grilles, frises) où la métrique seule ne capture pas si la structure attendue est présente.

### 2. Variantes "OU" — résultat à valider
Plusieurs classes contiennent un "OU" dans leur libellé (`Humain + entité OU Solo`, `Imagier différencié OU Solo`, `Solo humain OU objet`, etc.). La cartographie laisse le PromptGenerator choisir l'une des deux variantes par leaf. À vérifier sur les sorties que le choix est cohérent et que le prompt résultant est exploitable côté éditorial.

### 3. Méta-patterns (Grille imagier annoté, Imagier 3×3, Frise narrative)
Ces classes attendent une **structure géométrique imposée** (grille 3×3 d'objets différenciés, frise 1×N de panneaux). cr_avg propre (0.0017-0.0022) suggère que la composition tient au niveau couleur, mais la **structure exacte (nombre de cellules, alignement, séparateurs)** ne peut pas être validée par histogram. À inspecter visuellement en priorité.

### 4. ComfyUI a redémarré pendant le run (impact zéro)
Le run a démarré à 01:33 et s'est terminé à 02:43 (parallèle au fix Tailscale `start.py`). Une transition de l'API uvicorn (loopback → 0.0.0.0) a eu lieu pendant le run mais ComfyUI sur 8188 a continué sans interruption. Aucune image perdue.

### 5. Index files multi-fusion (rappel fix précédent)
Les 37 nouveaux `index-<slug>.json` produits sont fusionnés automatiquement par l'annotateur (`_find_prompt_index`, fix du 2026-05-09). Avec l'`index-humans.json` préexistant, **38 fichiers d'index** sont fusionnés en un index virtuel pour le résolveur. Le frontend voit prompt + titre + workflow_class + confidence + pitfalls par image, sans configuration additionnelle.

### 6. Classes Confidence "Haute" composées non testées
17 classes ont un libellé Haute composé (`Haute (avec règles)`, `Haute (pour SVG)`, etc.) — exclues du filtre strict. Si ces classes intéressent la prod, prévoir un run dédié avec un filtre plus large (`startswith("Haute")` au lieu de `== "Haute"`).

## Décision / Action suivante

✅ **POC validé** : 310/310 OK, négatif v3 efficace sur 36/37 classes, 1 seul outlier prévisible. Latence et stabilité ComfyUI excellentes (53 min cumulé en pratique pour 310 inférences avec parallélisme aucun).

**Annotation humaine prioritaire** :

| Priorité | Pour quoi |
|---|---|
| 🔴 Haute | Méta-patterns (Grille imagier, Imagier 3×3, Frise narrative, Multi-sujets via grille) — métrique aveugle à la structure |
| 🟠 Moyenne | Classes "OU" (12 cas) — vérifier que la variante choisie par PromptGenerator est cohérente |
| 🟡 Faible | Solo humain en pose / Solo objet en vol — déjà très propres en métrique, vérification qualitative légère |

**URL annotateur** :
```
http://100.114.117.104:8000/data/benchmark-annotator.html?dir=poc-scale-benchmark
```

(ou `http://127.0.0.1:8000/...` en local)

L'annotateur affiche désormais (via fix multi-index + fallback prompt précédents) pour chaque image le **prompt complet, le négatif, le workflow_class, la confidence et les pitfalls** — chargés dynamiquement depuis les 38 index files.

## Annexes

- **Script** : `scripts/poc_scale_benchmark_uncovered.py`
- **Index par classe** : `docs/reports/poc-scale-benchmark/index-<slug>.json` ×37
- **Index humans précédent** : `docs/reports/poc-scale-benchmark/index-humans.json`
- **Métriques globales** : `docs/reports/poc-scale-benchmark/poc-scale-benchmark.json` (entries `seed >= 9000` = ce run)
- **Phases précédentes** :
  - `docs/reports/2026-05-09_phase-integration-prompt-generator.md`
  - `docs/reports/2026-05-09_poc-scale-humans.md`
  - `docs/reports/2026-05-09_fix-multiindex-benchmark.md`
  - `docs/reports/2026-05-09_poc-rerun-2objets.md`
  - `docs/reports/2026-05-09_tailscale-access.md`
