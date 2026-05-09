# POC — Variance de seed (euler 8s normal cfg1.0)
Date : 2026-05-06

## Contexte

En prod les seeds ne sont pas fixés : il faut connaître la **variance de qualité** par concept pour calibrer les politiques de retry du worker `image_generation`. Ce POC mesure la dispersion sur 23 images annotées humainement (sur les 30 générées par `scripts/poc_seed_variance.py`) à partir de seeds reproductibles (`random.Random(2026)`).

**Paramètres figés** (recommandation prod, cf. `2026-05-06_poc-sampler-benchmark-v3.md`) : sampler `euler`, 8 steps, scheduler `normal`, `cfg=1.0`, 1024×1024, `denoise=1.0`, workflow `ernie-image-turbo-q8-api`. Soccer reçoit le négatif anatomy validé (`extra legs, third leg, duplicate limbs, fused legs, malformed anatomy, wrong number of limbs, six fingers, deformed feet, no motion`) ; les autres concepts utilisent un négatif vide.

Concepts × #seeds testés : **soccer × 10**, **dragon × 10**, **cat × 3/5 annotés**, hammer × 5 (non analysés ici, contrôle stable). Source brute : `docs/reports/poc-seed-variance/poc-seed-variance.json`.

## Résultats par concept

### Soccer — CRITIQUE

| Var | Seed (court) | Score | Défauts | Publishable |
|---|---|---:|---|:---:|
| var01 | s616025 | **9** | — | ✅ |
| var02 | s402793 | 1 | 3_jambes | ❌ |
| var03 | s030207 | 1 | 2_objets | ❌ |
| var04 | s087846 | 1 | 3_jambes | ❌ |
| var05 | s509027 | **10** | — | ✅ |
| var06 | s987308 | 2 | 3_jambes | ❌ |
| var07 | s609845 | **10** | — | ✅ |
| var08 | s963309 | 1 | 3_jambes | ❌ |
| var09 | s252818 | 1 | 3_jambes | ❌ |
| var10 | s817377 | 1 | 3_jambes | ❌ |

**Stats :**
- Score moyen : **3.70** · écart-type σ ≈ **3.93** · médiane 1
- Publishable : **3/10 (30 %)**
- Échecs : **7/10 (70 %)**, dont `3_jambes` **6/10 (60 %)** et `2_objets` 1/10
- Seeds qui passent : `s616025`, `s509027`, `s609845`

→ Bimodal — soit l'image est parfaite (9-10), soit catastrophique (1-2). Pas d'échelle de gris : le prompt négatif anatomy ne **prévient pas** le défaut, il le filtre seulement quand le seed n'est pas dans une zone d'attracteur défavorable.

### Dragon — Stable

| Var | Seed (court) | Score | Défauts | Publishable |
|---|---|---:|---|:---:|
| var01 | s953297 | 5 | — | ✅ |
| var02 | s908032 | 8 | couleurs_résiduelles | ✅ |
| var03 | s240572 | 6 | — | ✅ |
| var04 | s387404 | 9 | couleurs_résiduelles | ✅ |
| var05 | s032352 | 6 | couleurs_résiduelles | ✅ |
| var06 | s983573 | 8 | couleurs_résiduelles | ✅ |
| var07 | s653888 | 7 | couleurs_résiduelles | ✅ |
| var08 | s723331 | 8 | couleurs_résiduelles | ✅ |
| var09 | s014448 | 9 | couleurs_résiduelles | ✅ (note : « details ») |
| var10 | s130464 | 9 | couleurs_résiduelles | ✅ (note : « details ») |

**Stats :**
- Score moyen : **7.50** · σ ≈ **1.36** · médiane 8
- Publishable : **10/10 (100 %)**
- Défaut dominant : `couleurs_résiduelles` **8/10 (80 %)** — **bénin** pour un livre de coloriage (l'enfant peint par-dessus le trait noir, les couleurs résiduelles seront recouvertes ou ignorées).

→ Distribution unimodale, basse variance. Concept robuste sans négatif spécifique.

### Cat — Partiel (3/5 annotés)

| Var | Seed (court) | Score | Défauts / Notes | Publishable |
|---|---|---:|---|:---:|
| var01 | s402013 | 7 | — | ✅ |
| var02 | s410345 | 3 | couleurs_résiduelles | ❌ |
| var03 | s140108 | 4 | note : « lumiere » | ❌ |

**Stats sur 3 seeds :**
- Score moyen : **4.67** · σ ≈ **1.70** · médiane 4
- Publishable : **1/3 (33 %)**
- Défauts : couleurs résiduelles + problème d'éclairage (catégorie non formelle dans la taxonomie defects actuelle).

⚠ **2 seeds restent non annotés** : `var04_s960845` et `var05_s799787`. Résultats à considérer comme **indicatifs uniquement** ; ils ne valident ni n'infirment de tendance solide pour cat à ce stade.

## Analyse comparative

| Concept | Seeds annotés | Publishable | Score moyen | σ | Défaut dominant |
|---|---:|---:|---:|---:|---|
| **soccer** | 10 | **3/10 (30 %)** | 3.70 | **3.93** | `3_jambes` 6/10 |
| **dragon** | 10 | **10/10 (100 %)** | 7.50 | 1.36 | `couleurs_résiduelles` 8/10 (bénin) |
| **cat** | 3 | 1/3 (33 %) | 4.67 | 1.70 | couleurs + lumière (partiel) |

→ **Soccer est seul à exhiber un mode de défaillance bloquant** (anatomie). Dragon et cat ont des défauts mais la sévérité n'empêche pas la publication (cas dragon) ou demande plus de données (cas cat).

## Points d'attention

1. **Soccer — le prompt négatif anatomy validé en UI ne protège que ~30 % des seeds.** Les seeds « réussis » des tests précédents (`074319` notamment) étaient des seeds chanceux cherry-pickés. La variance σ ≈ 3.93 sur une échelle 1-10 est extrême — le concept est intrinsèquement instable à euler 8s cfg 1.0 avec un négatif texte seul, malgré tous les fixes empilés (anatomy_static_pose, négatif anatomy, cfg=1.0).

2. **Dragon — `couleurs_résiduelles` sur 80 % des seeds, mais ne bloque pas la publication.** En contexte coloriage, ces couleurs disparaissent dès qu'un enfant peint dessus. Risque : si on intègre le **two-step colored→lineart** (cf. `2026-05-05_poc-color-to-lineart.md`) ou un **prompt filter** strip color (cf. `2026-05-05_poc-prompt-filter.md`) à dragon, ils interféreraient avec ce qu'humainement on tolère ici. À ne **pas** activer automatiquement sur dragon en prod sans benchmark de A/B.

3. **Cat — dataset partiel.** 3/5 seeds insuffisant pour un verdict ; les 2 seeds restants doivent être annotés avant de tirer une conclusion. Présence d'un défaut « lumière » non formalisé dans la taxonomie — à intégrer comme nouveau tag si le pattern se confirme.

## Décision / Action suivante

**Soccer nécessite obligatoirement un mécanisme de retry en production.** Options par ordre de priorité :

1. **Multi-génération avec QC auto** — générer N images (N=3-5), garder la première sans `3_jambes` selon détection heuristique (Pillow contour + nombre de jambes via skeleton/morphologie) ou vision LLM (`qwen3.5:9b` avec prompt anatomy-spécifique). Coût : 1 à 5× la latence Comfy par image, mais politique calibrable selon le concept.
2. **Seed allowlist** — utiliser uniquement les seeds validés `s616025` / `s509027` / `s609845`. **Non recommandé en prod** : manque de variété, et la liste valide pour un prompt précis ne se généralisera pas à un autre prompt soccer.
3. **Renforcement du prompt négatif** — élargir au-delà du négatif actuel (ajouter par ex. `"unnatural pose, anatomical errors, missing limbs"`). À valider en POC dédié avec une nouvelle variance de seeds avant promotion. Bénéfice attendu modéré vu que le négatif actuel est déjà long.
4. **Scheduler karras pour soccer spécifiquement** — la note dans `CLAUDE.md` mentionne « karras 8s = meilleur scheduler pour soccer (POC v1) ». À re-tester en variance de seeds : si karras passe à >70 % publishable sur 10 seeds, c'est le fix le moins coûteux (juste un override de scheduler dans `job.config` pour les concepts taggués `subject_in_action`).

**Priorité absolue avant pipeline prod : implémenter le retry avec QC vision** (`qwen3.5:9b`, en attente de validation sur volume 50+ images cf. décision LLM 2026-05-05). Le retry multi-génération est la seule option robuste à long terme — les autres sont des palliatifs concept-spécifiques qui ne couvriront pas les cas d'usage futurs.

**Pour dragon et cat** : pas d'action prioritaire requise au-delà de la complétion du dataset cat (annoter `var04_s960845` et `var05_s799787`). Dragon est en l'état acceptable pour la prod ; tout traitement upstream couleurs sur ce concept doit être A/B-testé avant d'être déclenché.

## Annexes

- Données brutes : `docs/reports/poc-seed-variance/poc-seed-variance.json` (index live mis à jour pendant la génération avec QC autos)
- Galerie images : `docs/reports/poc-seed-variance/*.png` (30 PNG, naming `<concept>_var<NN>_s<seed_short>_08s_normal_euler_cfg10.png`)
- Annotations humaines : annotations.json (à publier dans le même dossier après complétion cat)
- Script : `scripts/poc_seed_variance.py`
- POCs reliés :
  - `2026-05-06_poc-sampler-benchmark-v2.md` (variantes prompt soccer + tramage dpmpp_2m)
  - `2026-05-06_poc-sampler-benchmark-v3.md` (CFG / résolution / nouveaux concepts)
  - `2026-05-05_poc-prompt-filter.md` (`anatomy_static_pose`)
  - `2026-05-05_poc-color-to-lineart.md` (two-step alternatif pour color_prior)
- Annotation humaine via : http://127.0.0.1:8000/data/benchmark-annotator.html?dir=poc-seed-variance
