# Règles empiriques — Génération image ERNIE

Source : benchmarks humains 2026-05-06 (130+ images) + poc-scale-benchmark 2026-05-09 (196 images).

## Défauts prod (ne pas changer sans nouveau benchmark)

| Param | Valeur |
|-------|--------|
| sampler_name | euler |
| steps | 8 |
| cfg | 1.0 |
| scheduler | normal |
| denoise | 1.0 |
| width × height | 1024×1024 |

## Samplers

| Sampler | Verdict | Raison |
|---------|---------|--------|
| **euler** | ✅ Prod | +2 pts vs dpmpp_2m_sde, +2.6 pts vs dpmpp_2m |
| dpmpp_2m | ❌ Banni | Tramage quasi-systématique, score moyen 3.75/10 |
| dpmpp_2m_sde | ⚠️ Fallback expérimental | Score moyen 4.38/10 |
| karras (scheduler) | ❌ Banni sujets complexes | Catastrophique sur humains en action (échec total, validé variance seeds 2026-05-07) |

## CFG

- **1.0 : obligatoire si anatomie humaine ou animale** — cfg 1.5+ réintroduit 3_jambes
- 1.5 : acceptable sur inanimes simples (outils, objets)
- 3.0 : dégradation universelle, jamais utiliser

## Steps euler

- **8 = optimum** — 12 steps = creux qualité (5.75 vs 7.50 à 8)
- 20 steps : utilisable pour scènes complexes mais gris résiduel

## Résolution par type de sujet

| Type | Résolution | Justification |
|------|-----------|---------------|
| Personnages / scènes complexes | 1024×1024 | Défaut universel |
| Humains en action (Solo humain en action, pose active) | 848×1264 (portrait) | Anatomie verticale |
| Véhicules / paysages | 1376×768 (landscape) | Composition horizontale |
| Objets / animaux simples | 768×768 | Moins de traits discontinus |
| Sujets trop riches pour 512 | Éviter 512 | Trop simple, perte de détails |

## Spectre de complexité des concepts

| Tier | Exemples | Score moyen | Défauts typiques |
|------|----------|------------|-----------------|
| ✅ Simple inanime | hammer, flower, fish, guitar, train | 9-10/10 | aucun |
| ✅ Simple animé | cat, lion, bicycle | 7-9/10 | gris_résiduel mineur |
| ⚠️ Complexe animé | astronaut, soccer, dragon | 6-9/10 | anatomy si cfg>1.0, couleurs_résiduelles |
| ❌ Scène intérieure | refrigerator | 1-3/10 | color_prior + perspective_KO |

## Couleurs résiduelles

**Aucun paramètre sampler/steps/cfg ne corrige les couleurs résiduelles.** Fix uniquement upstream :
1. `strip_color_nouns` dans le prompt filter
2. Négatif additif couleur spécifique au concept
3. Two-step colored→lineart pour color_prior élevé

Seuil mesure : `color_ratio < 0.002` = image N&B correcte. Mesuré par `src/services/image_qc_technical.py`.

## Anatomie (3_jambes, membres surnuméraires)

- Garder cfg=1.0 — cfg>1.0 réintroduit le défaut
- Négatif anatomy ciblé : `"extra legs, third leg, duplicate limbs, fused legs, malformed anatomy, wrong number of limbs, six fingers, deformed feet, no motion"`
- Ne pas raccourcir le prompt writer (prompts courts → 3_jambes même à euler 8s cfg 1.0)
- batch_size=3 pour humains en action : garde la meilleure image des 3 sorties

## batch_size

- **1** : défaut pour tous les sujets
- **3** : recommandé pour Solo humain en action, Solo humain pose active (risque anatomie)
  - Génère 3 images avec seeds consécutifs, sauvegarde les 3 + copie de b1 en canonical
  - Taux "au moins 1 bonne" : ~70% (validé poc)
