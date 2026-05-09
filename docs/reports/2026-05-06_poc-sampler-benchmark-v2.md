# POC sampler benchmark v2 — euler vs dpmpp_2m vs dpmpp_2m_sde

Date : 2026-05-06

## Contexte

Annotation humaine de **75 images** générées par ComfyUI sur 8 concepts × 3 samplers × 3 steps (+ 3 variantes de prompt soccer). Données brutes : `docs/reports/poc-sampler-benchmark-v2/annotations.json`. Tous les paramètres communs : `cfg=10`, scheduler `normal`, seed fixe par concept (≠ par sampler), workflow `ernie-image-turbo-q8-api`.

**Schéma de notation :** score `1-10` (10 = parfait line art publiable, 1 = inutilisable), `defects` (liste finie : `couleurs_résiduelles`, `gris_résiduel`, `traits_flous`, `perspective_KO`, `3_jambes`, `2_objets`), `publishable` ∈ {`true`, `null`}.

## Annotations brutes par image (75)

| Filename | Score | Defects | Pub. | Notes |
|---|---:|---|:---:|---|
| astronaut_08s_normal_euler_cfg10_42006.png | 9 | — | ✅ | — |
| astronaut_12s_normal_euler_cfg10_42006.png | 5 | — | — | un peu de couleur, ciel bleu |
| astronaut_20s_normal_euler_cfg10_42006.png | 6 | couleurs_résiduelles, gris_résiduel | — | — |
| astronaut_08s_normal_dpmpp_2m_cfg10_42006.png | 1 | — | — | des trames de gris partout |
| astronaut_12s_normal_dpmpp_2m_cfg10_42006.png | 1 | — | — | trames de gris |
| astronaut_20s_normal_dpmpp_2m_cfg10_42006.png | 6 | — | — | trames de gris |
| astronaut_08s_normal_dpmpp_2m_sde_cfg10_42006.png | 5 | — | ✅ | un peu de deformation |
| astronaut_12s_normal_dpmpp_2m_sde_cfg10_42006.png | 7 | — | ✅ | trames de gris |
| astronaut_20s_normal_dpmpp_2m_sde_cfg10_42006.png | 5 | — | — | trames de gris |
| bicycle_08s_normal_euler_cfg10_42007.png | 8 | — | ✅ | trop simple |
| bicycle_12s_normal_euler_cfg10_42007.png | 7 | gris_résiduel | ✅ | — |
| bicycle_20s_normal_euler_cfg10_42007.png | 6 | — | ✅ | — |
| bicycle_08s_normal_dpmpp_2m_cfg10_42007.png | 1 | — | — | trames de gris |
| bicycle_12s_normal_dpmpp_2m_cfg10_42007.png | 2 | — | — | trames gris |
| bicycle_20s_normal_dpmpp_2m_cfg10_42007.png | 3 | couleurs_résiduelles | — | — |
| bicycle_08s_normal_dpmpp_2m_sde_cfg10_42007.png | 1 | traits_flous, gris_résiduel | — | — |
| bicycle_12s_normal_dpmpp_2m_sde_cfg10_42007.png | 4 | gris_résiduel | — | — |
| bicycle_20s_normal_dpmpp_2m_sde_cfg10_42007.png | 7 | — | ✅ | — |
| cat_08s_normal_euler_cfg10_42004.png | 8 | gris_résiduel | ✅ | — |
| cat_12s_normal_euler_cfg10_42004.png | 6 | gris_résiduel | ✅ | — |
| cat_20s_normal_euler_cfg10_42004.png | 6 | gris_résiduel | ✅ | — |
| cat_08s_normal_dpmpp_2m_cfg10_42004.png | 4 | gris_résiduel | — | — |
| cat_12s_normal_dpmpp_2m_cfg10_42004.png | 5 | gris_résiduel | ✅ | — |
| cat_20s_normal_dpmpp_2m_cfg10_42004.png | 6 | gris_résiduel | — | — |
| cat_08s_normal_dpmpp_2m_sde_cfg10_42004.png | 6 | — | ✅ | — |
| cat_12s_normal_dpmpp_2m_sde_cfg10_42004.png | 3 | couleurs_résiduelles, gris_résiduel | — | — |
| cat_20s_normal_dpmpp_2m_sde_cfg10_42004.png | 5 | couleurs_résiduelles | — | — |
| dragon_08s_normal_euler_cfg10_42003.png | 8 | couleurs_résiduelles | ✅ | — |
| dragon_12s_normal_euler_cfg10_42003.png | 7 | couleurs_résiduelles, gris_résiduel | ✅ | — |
| dragon_20s_normal_euler_cfg10_42003.png | 9 | gris_résiduel | ✅ | — |
| dragon_08s_normal_dpmpp_2m_cfg10_42003.png | 3 | couleurs_résiduelles | — | trames gris |
| dragon_12s_normal_dpmpp_2m_cfg10_42003.png | 4 | couleurs_résiduelles | — | — |
| dragon_20s_normal_dpmpp_2m_cfg10_42003.png | 8 | gris_résiduel | ✅ | — |
| dragon_08s_normal_dpmpp_2m_sde_cfg10_42003.png | 5 | couleurs_résiduelles, gris_résiduel | — | — |
| dragon_12s_normal_dpmpp_2m_sde_cfg10_42003.png | 3 | couleurs_résiduelles, gris_résiduel | — | — |
| dragon_20s_normal_dpmpp_2m_sde_cfg10_42003.png | 7 | couleurs_résiduelles | ✅ | — |
| guitar_08s_normal_euler_cfg10_42008.png | 8 | — | ✅ | simple |
| guitar_12s_normal_euler_cfg10_42008.png | 8 | — | ✅ | — |
| guitar_20s_normal_euler_cfg10_42008.png | 6 | — | ✅ | — |
| guitar_08s_normal_dpmpp_2m_cfg10_42008.png | 3 | gris_résiduel | — | trames grises |
| guitar_12s_normal_dpmpp_2m_cfg10_42008.png | 6 | — | ✅ | — |
| guitar_20s_normal_dpmpp_2m_cfg10_42008.png | 7 | — | ✅ | — |
| guitar_08s_normal_dpmpp_2m_sde_cfg10_42008.png | 6 | — | ✅ | — |
| guitar_12s_normal_dpmpp_2m_sde_cfg10_42008.png | 6 | — | ✅ | — |
| guitar_20s_normal_dpmpp_2m_sde_cfg10_42008.png | 6 | — | ✅ | traits en gris |
| hammer_08s_normal_euler_cfg10_42005.png | 10 | — | ✅ | — |
| hammer_12s_normal_euler_cfg10_42005.png | 10 | — | ✅ | — |
| hammer_20s_normal_euler_cfg10_42005.png | 10 | — | ✅ | — |
| hammer_08s_normal_dpmpp_2m_cfg10_42005.png | 3 | — | — | trames gris |
| hammer_12s_normal_dpmpp_2m_cfg10_42005.png | 7 | gris_résiduel | ✅ | — |
| hammer_20s_normal_dpmpp_2m_cfg10_42005.png | 8 | — | ✅ | — |
| hammer_08s_normal_dpmpp_2m_sde_cfg10_42005.png | 4 | gris_résiduel | ✅ | trames gris, traits gris |
| hammer_12s_normal_dpmpp_2m_sde_cfg10_42005.png | 5 | gris_résiduel | — | position objet sur un plan |
| hammer_20s_normal_dpmpp_2m_sde_cfg10_42005.png | 6 | gris_résiduel | ✅ | — |
| refrigerator_08s_normal_euler_cfg10_42002.png | 1 | couleurs_résiduelles, perspective_KO | — | — |
| refrigerator_12s_normal_euler_cfg10_42002.png | 2 | couleurs_résiduelles, perspective_KO | — | — |
| refrigerator_20s_normal_euler_cfg10_42002.png | 1 | couleurs_résiduelles, gris_résiduel | — | — |
| refrigerator_08s_normal_dpmpp_2m_cfg10_42002.png | 1 | couleurs_résiduelles | — | tramage |
| refrigerator_12s_normal_dpmpp_2m_cfg10_42002.png | 2 | couleurs_résiduelles | — | — |
| refrigerator_20s_normal_dpmpp_2m_cfg10_42002.png | 1 | — | — | — |
| refrigerator_08s_normal_dpmpp_2m_sde_cfg10_42002.png | 6 | couleurs_résiduelles | — | perspective ok |
| refrigerator_12s_normal_dpmpp_2m_sde_cfg10_42002.png | 2 | couleurs_résiduelles, gris_résiduel | — | tramage |
| refrigerator_20s_normal_dpmpp_2m_sde_cfg10_42002.png | 1 | couleurs_résiduelles | — | tramage |
| soccer_08s_normal_euler_cfg10_074319.png | 8 | — | ✅ | — |
| soccer_12s_normal_euler_cfg10_074319.png | 1 | 3_jambes, gris_résiduel | — | — |
| soccer_20s_normal_euler_cfg10_074319.png | 9 | gris_résiduel | ✅ | — |
| soccer_08s_normal_dpmpp_2m_cfg10_074319.png | 3 | — | — | tamage |
| soccer_12s_normal_dpmpp_2m_cfg10_074319.png | 1 | 3_jambes | — | — |
| soccer_20s_normal_dpmpp_2m_cfg10_074319.png | 4 | couleurs_résiduelles | — | — |
| soccer_08s_normal_dpmpp_2m_sde_cfg10_074319.png | 1 | 3_jambes | — | — |
| soccer_12s_normal_dpmpp_2m_sde_cfg10_074319.png | 3 | 2_objets, couleurs_résiduelles, gris_résiduel | — | tramage |
| soccer_20s_normal_dpmpp_2m_sde_cfg10_074319.png | 1 | 3_jambes, 2_objets | — | tramage |
| soccer_prompt_v1_08s_normal_euler_cfg10_074319.png | 8 | gris_résiduel | ✅ | — |
| soccer_prompt_v2_08s_normal_euler_cfg10_074319.png | 2 | 3_jambes | — | — |
| soccer_prompt_v3_08s_normal_euler_cfg10_074319.png | 2 | 3_jambes | — | — |

## 1. Comparaison globale euler vs dpmpp_2m vs dpmpp_2m_sde

Sur 24 cellules par sampler (8 concepts × 3 steps), variantes de prompt soccer exclues pour comparaison propre.

| Sampler | n | Score moyen | Médiane | Min | Max | Publishable | Defects principaux |
|---|---:|---:|---:|---:|---:|:---:|---|
| **euler** | 24 | **6.33** | 7 | 1 | 10 | **17/24 (71 %)** | gris_résiduel ×10, couleurs_résiduelles ×6, 3_jambes ×1, perspective_KO ×2 |
| dpmpp_2m_sde | 24 | 4.38 | 5 | 1 | 7 | 10/24 (42 %) | gris_résiduel ×10, couleurs_résiduelles ×9, 2_objets ×2, 3_jambes ×2, traits_flous ×1 |
| dpmpp_2m | 24 | 3.75 | 3 | 1 | 8 | 6/24 (25 %) | gris_résiduel ×6, couleurs_résiduelles ×6, 3_jambes ×1 — **+ tramage massif dans les notes** |

**Lecture** : `euler` gagne franchement — score moyen **+1.95 pt** vs `dpmpp_2m_sde`, **+2.58 pt** vs `dpmpp_2m`. Le taux publishable euler **71 %** est presque 3× celui de `dpmpp_2m`.

**Pattern caché — tramage (notes texte, pas dans `defects`)** :
- `dpmpp_2m` : **9/24** annotations mentionnent « trames », « tramage » ou « trames gris » dans les notes (alors qu'aucune n'est tagguée `gris_résiduel`/`traits_flous` dans les defects). Quasi-systématique sur 8s et 12s. Si on ajoute le tramage aux defects, `dpmpp_2m` aurait ~15/24 défauts.
- `dpmpp_2m_sde` : 7/24 mentions tramage en notes (s'ajoutent aux defects formels) → ~17/24 avec défaut détecté.
- `euler` : **0** mention de tramage dans les notes.

→ **`dpmpp_2m` introduit un défaut systémique de tramage** que les annotations defects ne capturent pas mais que l'œil humain a noté à 9 reprises. C'est le défaut différenciant principal entre samplers, en plus du score brut.

## 2. Meilleur sampler par concept

Score moyen sur 3 steps (8/12/20). Variantes de prompt soccer exclues.

| Concept | euler | dpmpp_2m | dpmpp_2m_sde | Gagnant |
|---|---:|---:|---:|---|
| astronaut | **6.7** | 2.7 | 5.7 | euler |
| bicycle | **7.0** | 2.0 | 4.0 | euler |
| cat | **6.7** | 5.0 | 4.7 | euler |
| dragon | **8.0** | 5.0 | 5.0 | euler |
| guitar | **7.3** | 5.3 | 6.0 | euler |
| hammer | **10.0** | 6.0 | 5.0 | euler |
| refrigerator | 1.3 | 1.3 | **3.0** | dpmpp_2m_sde (mais publishable 0/3 partout) |
| soccer | **6.0** | 2.7 | 1.7 | euler |

**7/8 concepts → euler.** Le seul écart est `refrigerator`, où aucun sampler ne produit un résultat publiable (max 3.0 sur sde, 1.3 sur les autres). Ce n'est pas une victoire de `dpmpp_2m_sde` mais un échec uniforme : `refrigerator` reste un cas problématique structurel (color prior + perspective KO), traité par les POC précédents (`poc-color-to-lineart` et `poc-prompt-filter`) plutôt que par un changement de sampler.

`hammer` est l'unique concept où **euler obtient 10/10 sur les 3 steps** — c'est le concept témoin qui montre le plafond de qualité atteignable.

## 3. Impact des steps par sampler

Score moyen pour chaque combinaison `(sampler, steps)` :

| Sampler | 8 steps | 12 steps | 20 steps | Tendance |
|---|---:|---:|---:|---|
| **euler** | **7.50** | 5.75 | 6.62 | **8s est l'optimum**, 12s creux, 20s rebond mais en dessous du 8s |
| dpmpp_2m | 2.38 | 3.50 | **5.38** | **Monotone croissant** — 20s nécessaire, 8s catastrophique |
| dpmpp_2m_sde | 4.25 | 4.12 | **4.75** | **Quasi-plat** — les steps n'aident pas significativement |

**Lectures :**

- **`euler` n'a pas besoin de plus de steps** : 8s est le sweet spot, ajouter des steps **dégrade** (12s) ou ne rattrape pas (20s). Confirme le plafond ERNIE — le modèle converge vite et sur-étapes introduisent du bruit (gris résiduel sur cat/bicycle 12s/20s par exemple).
- **`dpmpp_2m` a besoin de bien plus de steps** : à 8s, score moyen **2.38/10**, totalement inexploitable. À 20s, ça remonte à 5.38 — toujours en dessous du 7.50 d'euler à 8s. Coût supplémentaire = 2.5× le compute, qualité finale inférieure.
- **`dpmpp_2m_sde` est plat** : 4.25 → 4.12 → 4.75. Aucun gain à payer plus de steps. Suggère que les défauts (couleurs résiduelles ×9, gris ×10) sont structurels au sampler et pas un problème de convergence.

**Cas particulier 12s euler — creux à 5.75** : 4 scores faibles (5, 7, 6, 7) + 1 catastrophe (soccer 12s = 1, 3 jambes). Le 12s d'euler n'est ni un bon plateau ni un bon checkpoint — soit on reste à 8s, soit on monte à 20s pour de la robustesse, mais 12s n'apporte rien.

## 4. Variantes de prompt soccer (euler 8s, seed identique)

Le concept soccer a aussi servi à tester 3 variantes de prompt à euler 8s :

| Variante | Score | Defects | Lecture |
|---|---:|---|---|
| **soccer_08s_normal_euler** (prompt baseline) | **8** | — | Anatomie OK, base solide |
| soccer_prompt_v1 | 8 | gris_résiduel | Equivalent qualité, juste un peu de gris |
| soccer_prompt_v2 | 2 | **3_jambes** | Régression anatomie |
| soccer_prompt_v3 | 2 | **3_jambes** | Régression anatomie |

→ Le défaut **3_jambes n'est pas une faute du sampler** (euler 8s baseline = score 8, parfait côté anatomie). C'est une régression du **prompt** — à creuser concept par concept. Confirme le besoin du fix `anatomy_static_pose` du POC prompt-filter.

## 5. Règles à mettre à jour dans la base de connaissance

Comparé à ce qu'on supposait jusqu'ici (analyse euler-only POC image quality + POC color-to-lineart) :

### Confirmé (renforce les conclusions précédentes)

| Règle | Statut | Source |
|---|---|---|
| `euler` est le sampler de défaut pour ERNIE-Image-Turbo | ✅ confirmé empiriquement (7/8 concepts gagnants, +2 pts moyens) | `ImageWorker._ERNIE_SAMPLER_DEFAULTS["sampler_name"]="euler"` était le bon choix |
| 8 steps suffit pour euler ; +steps ne fait pas mieux | ✅ confirmé (8s=7.50 > 12s=5.75 < 20s=6.62) | déjà dans `_ERNIE_SAMPLER_DEFAULTS["steps"]=8` |
| `refrigerator` = cas problématique structurel, pas un problème de sampler | ✅ confirmé (1.3-3.0 partout) | déjà traité par POC color-to-lineart (two-step) et POC prompt-filter |

### Nouvelles découvertes — règles à ajouter

| ID | Règle | Justification |
|---|---|---|
| `SAMPLER_BLACKLIST` | **`dpmpp_2m` est inutilisable sur ERNIE coloriage line art** sans 20+ steps, et même là reste sous euler 8s. À ne pas exposer dans les choix utilisateur. | Score moyen 3.75/10, 25 % publishable, **tramage de gris quasi-systématique** dans les notes (9/24) que les defects formels ne capturent pas. |
| `SAMPLER_DPMPP_2M_SDE_FALLBACK` | **`dpmpp_2m_sde` est mieux que `dpmpp_2m` mais reste 2 pts en dessous d'euler.** Considérer comme fallback uniquement si euler produit un défaut bloquant sur un concept précis (ex. déformation anatomique non résolue par retry). | Score moyen 4.38/10, 42 % publishable. Cas isolé : refrigerator où `_sde` fait 3.0 vs 1.3 — mais 0 publishable de toute façon. |
| `STEPS_12_AVOID_FOR_EULER` | **Ne pas générer en `euler 12s` pour ERNIE.** C'est le pire ratio des 9 combinaisons sampler×steps testées (5.75/10, en dessous de `euler 8s` ET `euler 20s`). Si on veut plus de marge qualité que `euler 8s`, monter à `euler 20s`, pas à 12s. | euler 8s=7.50 / 12s=5.75 / 20s=6.62 — creux pour 12s. Hypothèse : 12 steps avec scheduler `normal` tombe sur un schedule défavorable au modèle ERNIE Turbo. |
| `DEFECT_TRAMAGE_NOTES_AUDIT` | **Le tag `defects` actuel ne couvre pas le tramage** (le terme apparaît dans les notes texte de 16/75 annotations, surtout sur dpmpp_2m). Ajouter une catégorie formelle `tramage_gris` ou élargir `gris_résiduel` pour le couvrir. | Le QC vision et le histogram Pillow le détecteraient, mais la taxonomie defects actuelle force l'annotateur à le mettre en notes. Sans tag formel, l'agrégation rate la moitié du défaut sur dpmpp_2m. |
| `SOCCER_PROMPT_VARIANTS_REGRESS` | **La variante de prompt influence l'anatomie sur soccer indépendamment du sampler.** v2/v3 → 3_jambes (score 2/10) vs baseline → score 8 sur le même seed et même sampler. Le `anatomy_static_pose` du POC prompt-filter doit être considéré obligatoire pour subjects en action. | 3 variantes mesurées au même euler 8s : baseline=8, v1=8, v2=2 (3_jambes), v3=2 (3_jambes). |

### Implications opérationnelles

1. **Garder `euler 8s normal` comme défaut de prod** — déjà le cas dans `ImageWorker._ERNIE_SAMPLER_DEFAULTS`. Aucune raison de changer.
2. **Si l'utilisateur veut tester un alternatif via `job.config.sampler_name`, n'exposer que `euler` et `dpmpp_2m_sde`** dans la liste UI ; supprimer ou pré-déprécier `dpmpp_2m`.
3. **Ajouter une garde dans la validation de job** : si `sampler_name == "dpmpp_2m"` et `steps < 20`, warn ou refuser avec un message « ce sampler nécessite ≥ 20 steps, considérez `euler 8s` à la place ».
4. **Étendre la liste `defects` du QC humain** pour inclure `tramage_gris` — sinon les écarts samplers sont sous-estimés en agrégation.
5. **Refrigerator reste « color_prior + perspective » à traiter en amont du sampler** : profile pipeline `color_prior_v1` (POC color-to-lineart) ou règles writer renforcées (POC prompt-filter), pas un changement de sampler.

## 6. Verdict

✅ **Aucune raison de changer le sampler de défaut.** `euler 8s normal cfg10` reste le meilleur choix sur 7/8 concepts testés, avec le score moyen le plus haut (6.33), le taux publishable le plus haut (71 %), et zéro mention de tramage. Les deux alternatives DPM-PP++ explorées sous-performent : `dpmpp_2m_sde` est le moins mauvais des deux mais reste à 4.38 ; `dpmpp_2m` est à éliminer (3.75 + tramage systémique).

Le bénéfice principal de ce benchmark v2 n'est pas un changement de défaut mais une **clarification du périmètre de validité de chaque sampler** et la mise au jour de **2 défauts non capturés par la taxonomie actuelle** : tramage en notes (massif sur dpmpp_2m) et régression anatomique selon variante de prompt (independant du sampler).

## Annexes

- Source : `docs/reports/poc-sampler-benchmark-v2/annotations.json` (75 annotations humaines)
- Galerie : `docs/reports/poc-sampler-benchmark-v2/*.png` (75 PNG)
- Worker prod : `src/workers/image_worker.py::_ERNIE_SAMPLER_DEFAULTS`
- Documents connexes (mêmes 8 concepts ou subset) :
  - `docs/reports/2026-05-05_poc-image-quality.md` (8/8 verdict good vision QC, euler-only)
  - `docs/reports/2026-05-05_poc-color-to-lineart.md` (two-step pour color-prior subjects, traite refrigerator/dragon)
  - `docs/reports/2026-05-05_poc-prompt-filter.md` (4 règles upstream, traite refrigerator/dragon/soccer)
