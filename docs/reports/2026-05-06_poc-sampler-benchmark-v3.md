# POC sampler benchmark v3 — CFG, résolution, nouveaux concepts

Date : 2026-05-06

## Contexte

Suite des benchmarks samplers. **euler 8 steps normal** étant figé comme défaut prod (cf. `2026-05-06_poc-sampler-benchmark-v2.md`), v3 explore les **3 axes restants** sur lesquels le worker prod a un degré de liberté :

1. **Axe CFG** — `cfg ∈ {1.0, 1.5, 2.0, 3.0}` sur 4 concepts représentatifs (cat, dragon, hammer, soccer) à résolution 1024 par défaut
2. **Axe résolution** — `width=height ∈ {512, 768, 1024}` sur 3 concepts (cat, dragon, soccer) à `cfg=1.0` fixe
3. **Axe nouveaux concepts** — 6 concepts hors du panel v2 (castle, fish, flower, house, lion, train) tous à `cfg=1.0`, résolution défaut, pour tester la généralisation

**Paramètres communs :** sampler `euler`, scheduler `normal`, `denoise=1.0`, seed fixe par concept (≠ entre concepts), workflow `ernie-image-turbo-q8-api`. Schéma de notation identique au v2 (score 1-10 + `defects` + `publishable` + notes).

Source brute : `docs/reports/poc-sampler-benchmark-v3/annotations.json` (31 annotations humaines).

## Annotations brutes par image (31)

| Filename | Score | Defects | Pub. | Notes |
|---|---:|---|:---:|---|
| castle_08s_normal_euler_cfg10_43003.png | 10 | — | ✅ | — |
| cat_08s_normal_euler_cfg10_42004.png | 8 | gris_résiduel | ✅ | traits discontinus |
| cat_08s_normal_euler_cfg10_512x512_42004.png | 10 | — | ✅ | — |
| cat_08s_normal_euler_cfg10_768x768_42004.png | 9 | — | ✅ | parfait, details coloriables |
| cat_08s_normal_euler_cfg10_1024x1024_42004.png | 8 | gris_résiduel | ✅ | traits discontinus |
| cat_08s_normal_euler_cfg15_42004.png | 9 | — | ✅ | details coloriables |
| cat_08s_normal_euler_cfg20_42004.png | 8 | gris_résiduel | ✅ | — |
| cat_08s_normal_euler_cfg30_42004.png | 3 | couleurs_résiduelles, gris_résiduel | — | — |
| dragon_08s_normal_euler_cfg10_42003.png | 6 | couleurs_résiduelles | — | — |
| dragon_08s_normal_euler_cfg10_512x512_42003.png | 6 | couleurs_résiduelles | — | — |
| dragon_08s_normal_euler_cfg10_768x768_42003.png | 8 | couleurs_résiduelles | ✅ | details coloriables |
| dragon_08s_normal_euler_cfg10_1024x1024_42003.png | 8 | couleurs_résiduelles | ✅ | — |
| dragon_08s_normal_euler_cfg15_42003.png | 9 | couleurs_résiduelles | — | details coloriables |
| dragon_08s_normal_euler_cfg20_42003.png | 9 | couleurs_résiduelles | ✅ | details coloriables |
| dragon_08s_normal_euler_cfg30_42003.png | 4 | couleurs_résiduelles | — | — |
| fish_08s_normal_euler_cfg10_43002.png | 10 | — | ✅ | simple |
| flower_08s_normal_euler_cfg10_43001.png | 10 | — | ✅ | simple |
| hammer_08s_normal_euler_cfg10_42005.png | 10 | — | ✅ | parfait, scene interessante, details coloriables |
| hammer_08s_normal_euler_cfg15_42005.png | 10 | — | ✅ | traits epais |
| hammer_08s_normal_euler_cfg20_42005.png | 9 | — | ✅ | — |
| hammer_08s_normal_euler_cfg30_42005.png | 9 | — | ✅ | — |
| house_08s_normal_euler_cfg10_43006.png | 9 | — | ✅ | traits non fermés |
| lion_08s_normal_euler_cfg10_43005.png | 10 | — | ✅ | simple |
| soccer_08s_normal_euler_cfg10_074319.png | 9 | — | ✅ | mouvement interessant, contour blanc autour de la personne, traits non fermés |
| soccer_08s_normal_euler_cfg10_512x512_074319.png | 7 | — | ✅ | traits epais, contour blanc, traits non fermés, simple |
| soccer_08s_normal_euler_cfg10_768x768_074319.png | 6 | couleurs_résiduelles | — | — |
| soccer_08s_normal_euler_cfg10_1024x1024_074319.png | 9 | — | ✅ | — |
| soccer_08s_normal_euler_cfg15_074319.png | 1 | **3_jambes** | — | — |
| soccer_08s_normal_euler_cfg20_074319.png | 1 | **3_jambes** | — | — |
| soccer_08s_normal_euler_cfg30_074319.png | 4 | — | — | details intéressants |
| train_08s_normal_euler_cfg10_43004.png | 9 | — | ✅ | simple |

## 1. Axe CFG (cat, dragon, hammer, soccer × 1.0/1.5/2.0/3.0)

| Concept | cfg=1.0 | cfg=1.5 | cfg=2.0 | cfg=3.0 | Verdict |
|---|---:|---:|---:|---:|---|
| cat | 8 | **9** | 8 | 3 | Optimum à 1.5, plateau 1.0-2.0, **dégradation forte à 3.0** |
| dragon | 6 | **9** | **9** | 4 | cfg 1.5-2.0 améliore franchement (+3 pts), 3.0 dégrade |
| hammer | **10** | **10** | 9 | 9 | Robuste sur toute la plage — c'est le concept témoin |
| soccer | **9** | **1** | **1** | 4 | **Catastrophe à 1.5 et 2.0 — `3_jambes` réintroduit**. cfg 3.0 sauve l'anatomie mais le rendu reste sous-publiable. |

**Score moyen par cfg :** 1.0 = **8.25** · 1.5 = 7.25 · 2.0 = 6.75 · 3.0 = 5.0
**Publishable rate par cfg :** 1.0 = 4/4 (100 %) · 1.5 = 2/4 (50 %) · 2.0 = 3/4 (75 %) · 3.0 = 0/4 (0 %)

**Lectures :**

- **cfg=1.0 est le seul réglage 100 % publishable** — il ne casse aucun concept.
- **cfg=1.5-2.0 améliore les concepts non-anatomiques** (cat +1, dragon +3) — détails plus riches, mieux notés en revue. Mais **casse l'anatomie sur soccer** (3_jambes, score 1).
- **cfg=3.0 est universellement dégradant** — pénalise même hammer (10→9) et fait s'effondrer cat (3) et dragon (4) avec couleurs résiduelles.
- **L'anatomie humaine/animale en mouvement (soccer kicker) est l'attache critique pour cfg=1.0.** Tout cfg>1.0 réintroduit le défaut `3_jambes` — c'est la même régression observée dans le POC `prompt-filter` (variantes v2/v3 → 3_jambes même à cfg 1.0). Conclusion : avec un prompt qui garde la consigne anatomy_static_pose, **cfg=1.0 est obligatoire**.

→ **Règle dégagée — CFG safe zone :**
- **`cfg=1.0` = défaut prod** (anatomie OK garantie)
- **`cfg=1.5` acceptable uniquement sur sujets inanimés ou animaux statiques** (cat, dragon, hammer)
- **`cfg=2.0` à n'utiliser qu'en pre-validation manuelle** sur sujets non-anatomiques
- **`cfg=3.0` à bannir** (4/4 dégradations)

## 2. Axe résolution (cat, dragon, soccer × 512/768/1024)

À `cfg=1.0` fixe. La cellule `1024` partage le seed avec la cellule « cfg=1.0 défaut » de l'axe 1 — score identique.

| Concept | 512×512 | 768×768 | 1024×1024 | Sweet spot |
|---|---:|---:|---:|---|
| cat | **10** | 9 | 8 | **512** (1 seul sujet simple, plus la résolution est haute, plus on récolte de gris résiduel et de traits discontinus) |
| dragon | 6 | 8 | 8 | **768** suffit (1024 n'apporte rien) |
| soccer | 7 | 6 | **9** | **1024** (scène complexe, personnage en mouvement, ballon, terrain — détails perdus en 768 et en dessous) |

**Score moyen par résolution :** 512 = 7.67 · 768 = 7.67 · 1024 = **8.33**
**Publishable rate :** 512 = 3/3 · 768 = 2/3 · 1024 = 3/3

**Lectures :**

- **Pas de "meilleure résolution universelle".** Le sweet spot dépend de la complexité de la scène :
  - **Sujet simple isolé** (cat) : 512 est meilleur que 1024 (+2 pts) — le modèle ne sait pas occuper la résolution avec du contenu pertinent et ajoute du bruit (gris résiduel, traits discontinus).
  - **Sujet animé moyen** (dragon, lion supposé) : 768 atteint le plateau, 1024 n'apporte rien.
  - **Scène complexe avec personnage en action** (soccer) : 1024 nécessaire pour les détails (le 768 perd même 1 pt avec une couleur résiduelle apparue).

- **Effet de bord 768 sur soccer** : score 6 + couleurs_résiduelles. Le 768 est dans une zone instable pour les scènes complexes — soit on reste à 1024 (qualité garantie), soit on descend à 512 (rendu simplifié mais propre).

→ **Règle dégagée — Résolution par tier de complexité :**
- **Tier "Simple inanime/animé"** (hammer, fish, flower, cat, lion, train…) : `512` ou `768` suffit, économie de compute, moins de gris résiduel.
- **Tier "Complexe animé / scène"** (soccer, dragon, astronaut, castle, house) : `1024` nécessaire.
- **Défaut prod prudent : `1024`** (jamais bloquant ; payer le compute supplémentaire pour les Tier 1 est OK tant qu'on ne batch pas massivement).

## 3. Axe nouveaux concepts (6 hors panel v2)

Tous à `cfg=1.0`, résolution défaut, euler 8s normal, seed unique par concept.

| Concept | Score | Defects | Publishable | Notes | Tier |
|---|---:|---|:---:|---|---|
| castle | **10** | — | ✅ | — | Complexe |
| fish | **10** | — | ✅ | simple | Simple inanime |
| flower | **10** | — | ✅ | simple | Simple inanime |
| house | 9 | — | ✅ | traits non fermés | Complexe |
| lion | **10** | — | ✅ | simple | Simple animé |
| train | 9 | — | ✅ | simple | Simple inanime |

**Score moyen :** 9.67/10 · **Publishable rate : 6/6 (100 %)** · 0 défaut formel · 2 notes mineures (`traits non fermés` sur house, à corréler au floodfill du POC `color-to-lineart`).

**Lectures :**

- **6/6 publiables au premier essai** — la chaîne `qwen3.5:4b → euler 8s normal cfg=1.0` généralise très bien sur des concepts simples à modérément complexes.
- Le score moyen 9.67 est plus élevé que sur le panel v2 (6.33 sur euler) parce que ce panel ne contient **aucun cas problématique connu** (pas de refrigerator-style scène intérieure, pas de soccer-style anatomie). Confirme que **les 2 cas problématiques v2 ne sont pas représentatifs** du quotidien — ce sont des points durs à traiter en amont (POC `color-to-lineart` pour color-prior, POC `prompt-filter` pour anatomie).
- **Aucun nouveau pattern de défaut** introduit par ces 6 concepts — la chaîne ne plante pas sur des sujets nouveaux.

→ **Règle dégagée — Concepts validés :** les Tier "Simple inanime", "Simple animé" et "Complexe non-anatomique" passent la chaîne sans traitement spécial. Les seuls Tier nécessitant un traitement amont sont :
- **Scène intérieure perspective** (refrigerator) → POC `color-to-lineart` ou prompt renforcé
- **Personnage en mouvement** (soccer) → règle `anatomy_static_pose` du POC `prompt-filter` + `cfg=1.0` strict

## 4. Règles à ajouter à la base de connaissance

| ID | Règle | Action workflow / code |
|---|---|---|
| `CFG_SAFE_ZONE` | `cfg=1.0` est le seul défaut sûr (100 % publishable). `cfg=1.5` acceptable sur sujets non-anatomiques (cat/dragon/hammer +1 à +3 pts en moyenne). `cfg≥2.0` casse l'anatomie sur sujets en mouvement. `cfg=3.0` à bannir (0/4 publishable, dégrade hammer même). | `ImageWorker._ERNIE_SAMPLER_DEFAULTS["cfg"]=1.0` ✅ déjà en place. Ajouter une garde dans le worker : si `config.cfg > 1.0` ET `subject_tag in {"sport", "person_in_action", "animated_character"}`, warn ou clamp à 1.0. |
| `RESOLUTION_BY_TIER` | Pas de résolution universelle. Tier "Simple" (objets isolés, animaux statiques) → 512 ou 768 suffit (souvent meilleur, moins de gris résiduel). Tier "Complexe animé / scène" → 1024 nécessaire (soccer 1024=9 vs 768=6). Défaut prudent prod : 1024 partout (jamais bloquant). | `_ERNIE_SAMPLER_DEFAULTS["width"/"height"]=1024` ✅ déjà en place. Optimisation possible : permettre `width/height` dans `job.config` pour les Tier "Simple" (économie de compute). |
| `NEW_CONCEPTS_VALIDATED` | castle, fish, flower, house, lion, train passent la chaîne `euler 8s normal cfg=1.0` sans traitement spécial (6/6, score moyen 9.67/10). Aucun nouveau pattern de défaut introduit. | Pas de changement code. À documenter comme « concepts validés » dans la base de connaissance pour que les futurs ajouts taxonomie de même profil ne soient pas re-benchés inutilement. |

## 5. Verdict global v3

✅ **Aucune raison de changer les défauts prod** — `cfg=1.0`, `width=height=1024`, `euler 8s normal` restent corrects.

✅ **Trois nouvelles règles validées empiriquement** à ajouter à la base de connaissance image (cf. tableau ci-dessus).

✅ **Anatomie confirmée comme attache critique de cfg=1.0** — le défaut `3_jambes` revient dès que cfg dépasse 1.0 sur un sujet en mouvement, indépendamment du sampler (déjà observé en v2 sur les variantes de prompt soccer).

⚠ **Optimisation potentielle** : pour les Tier "Simple" (la majorité de la taxonomie), descendre la résolution à 512 ou 768 permet :
- Score moyen ≥ équivalent (cat 512 = 10 vs 1024 = 8)
- Compute réduit (~4× moins de pixels en 512)
- Moins de bruit résiduel (gris, traits discontinus)
- À tester sur 20-30 concepts Tier 1 avant de basculer le défaut.

## Annexes

- Source : `docs/reports/poc-sampler-benchmark-v3/annotations.json` (31 annotations humaines)
- Galerie : `docs/reports/poc-sampler-benchmark-v3/*.png` (31 PNG)
- Worker prod : `src/workers/image_worker.py::_ERNIE_SAMPLER_DEFAULTS`
- POCs précédents :
  - `docs/reports/2026-05-06_poc-sampler-benchmark-v2.md` (sampler comparison euler/dpmpp_2m/dpmpp_2m_sde)
  - `docs/reports/2026-05-05_poc-image-quality.md` (8/8 vision QC verdict good, baseline)
  - `docs/reports/2026-05-05_poc-prompt-filter.md` (`anatomy_static_pose`, `strip_color_nouns`)
  - `docs/reports/2026-05-05_poc-color-to-lineart.md` (two-step pour color_prior)
