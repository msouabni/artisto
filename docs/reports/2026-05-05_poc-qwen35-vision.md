# POC qwen3.5:9b vision — capability probe + QC benchmark vs gemma4:26b
Date : 2026-05-05

## Contexte
gemma4:26b validé pour le QC vision en POC vision-batch (6/6 verdicts corrects, 19.3 s/image en unitaire, 16.75 GB RAM). Question : `qwen3.5:9b` (6.14 GB, multimodal natif annoncé) peut-il remplacer gemma4 — avec l'avantage potentiel de tourner en **2 instances parallèles sur 16 GB VRAM** (12.28 GB de modèles cumulés) ?

Bench en 2 phases :
1. **Phase 1 — capability probe** : qwen3.5:9b accepte-t-il et exploite-t-il l'image envoyée via `images: [b64]` dans `/api/generate` ?
2. **Phase 2 — benchmark QC** : si phase 1 OK, mêmes 6 images que gemma4 (4 good / 2 poor), prompt QC identique, comparaison face à face.

## Résultats

### Phase 1 — capability probe ✅

Image probe : `animaux_chat_collier_job_gen_1773358396932.png` (page vide avec juste du texte écrit du prompt). Question : *"Describe what you see in this image in 1 short sentence. If you cannot see any image, reply with: NO_IMAGE_SEEN."*

Réponse qwen3.5:9b en 9.5 s :
> *"A blank coloring book page with text describing a cute cat illustration."*

→ Description **précise** mentionnant "blank", "coloring book", "text" — exactement ce que contient l'image. **qwen3.5:9b est bien multimodal sur cette instance Ollama.**

### Phase 2 — Benchmark QC sur 6 images

| Image | Ground truth | Verdict gemma4:26b | Verdict qwen3.5:9b | Match ? |
|---|---|---|---|---|
| `animaux_chat_collier_…` (vide-texte) | poor | poor ✓ | poor ✓ | = |
| `adventure_scooby_island_…` (couleurs/gradients) | poor | poor ✓ | **good ✗** | ≠ |
| `animals_bath_cat_…` | good | good ✓ | good ✓ | = |
| `animals_party_decor_…` | good | good ✓ | good ✓ | = |
| `animaux_chat_biblioth_que_…` | good | good ✓ | good ✓ | = |
| `animals_fairy_cat_…` | good | good ✓ | good ✓ | = |

**Score qwen3.5:9b : 5/6 verdicts corrects** vs 6/6 gemma4. 1 faux négatif : l'image scooby avec couleurs (jaune soleil + gradients gris) est marquée "good" par qwen3.5:9b, alors que gemma4 la flaggait `has_color + not_line_art` correctement.

### Métriques globales

| Axe | gemma4:26b | qwen3.5:9b | Δ |
|---|---|---|---|
| Verdicts corrects | **6/6** ✅ | 5/6 (83 %) | -17 pp |
| Issues overlap moyen | 1.00 | 0.83 | -0.17 |
| Latence moyenne /image | 19.31 s | **2.29 s** ✅ | **−88 %** (8.4× plus rapide) |
| Latence min / max | 10.5 / 31.3 s | 1.5 / 2.6 s | très stable qwen3.5 |
| RAM modèle | 16.75 GB | 6.14 GB | −63 % |
| Multimodalité | native (validée v2) | native (validée probe) | = |

## Analyse — trade-off qualité / latence / parallélisme

### Qualité
qwen3.5:9b rate la détection des **couleurs accidentelles** dans l'image scooby. Sur 1 cas isolé, c'est statistiquement non concluant — il faudrait benchmarker volume (50+ images avec un % connu de "poor avec couleurs") pour confirmer la précision réelle. **Hypothèse de travail : qwen3.5:9b est moins sensible aux couleurs subtiles** (gradients gris, soleil jaune partiel) que gemma4. Sur la détection "vide / texte / line art absent", les 2 modèles s'accordent.

### Latence
**2.29 s/image vs 19.31 s** : gain massif. Permet de traiter ~26 images/min en single-threaded vs ~3/min sur gemma4. Pour un pipeline qui produit ~50-100 images/jour, qwen3.5:9b passe le QC en quasi-temps réel ; gemma4 reste sur du batch nuit ou multi-worker.

### Faisabilité parallélisation 2 workers sur 16 GB VRAM
- **qwen3.5:9b** : 6.14 GB × 2 = **12.28 GB** → tient largement dans 16 GB VRAM. **2 workers parallèles viables**. Débit : ~52 images/min.
- **gemma4:26b** : 16.75 GB → 1 seul worker possible, pas de parallélisation.

→ Le parallélisme 2 workers compense largement la légère perte de précision. Débit théorique 2-workers qwen3.5:9b ≈ ~52 img/min vs ~3 img/min gemma4 single = **17× plus rapide en pratique**.

## Points d'attention

- **6 images = trop petit** pour conclure définitivement. Le 5/6 vs 6/6 n'a pas de signification statistique. Sur 50+ images réelles avec mix de pathologies (couleurs partielles, flou, artefacts ComfyUI), le ratio pourrait basculer dans un sens ou l'autre.
- **Faux négatif sur couleurs** : si la prod a un % significatif d'images avec couleurs accidentelles (sortie ComfyUI mal calibrée, prompt fuyant), qwen3.5:9b va laisser passer ces erreurs en "good". Mitigation possible : check Pillow histogram parallèle (rapide, déterministe) qui flagge si > 1 % pixels non-monochromes → force `poor` même si LLM dit `good`.
- **Issues détaillées** : qwen3.5:9b retourne `issues=[]` quand il dit "good" mais ne décrit pas pourquoi il pense que c'est "good". gemma4 retournait `confidence=100` + issues précises sur les "poor". Pas un manque fonctionnel ; juste moins informatif si on veut explainability.
- **Latence de phase 1 (9.5 s)** vs phase 2 (1.5-2.6 s) : la 1ère requête vision charge sans doute le modèle en RAM/VRAM côté serveur Ollama. À anticiper en pipeline P3 (warm-up vs cold start).
- **Concurrence sur Ollama remote** : non testée. Avec 2 workers parallèles, est-ce que l'instance distante traite les 2 requêtes en parallèle ou en sérial avec queue ? À mesurer.

## Décision / Action suivante

✅ **qwen3.5:9b remplace gemma4:26b — partiellement**, conditionnel à :

| Aspect | Décision |
|---|---|
| QC vision **primary** P3 | **qwen3.5:9b** (8.4× plus rapide, 5/6 corrects sur ce mini-bench) |
| Backup / arbitre | gemma4:26b si confiance faible OU si Pillow histogram détecte couleurs et qwen3.5 dit "good" |
| Parallélisme | **2 workers qwen3.5:9b en parallèle** sur 16 GB VRAM (à valider concurrence Ollama remote) |
| Couverture faiblesse couleur | Ajouter check Pillow histogram en parallèle (5-10 ms/image, déterministe) → si pixel non-monochrome > seuil, force `poor` |
| Validation finale | **POC volume QC vision sur 50+ images** avant promotion prod : mesurer la précision réelle de qwen3.5:9b face à un mix représentatif de pathologies |

### Routing recommandé pour P3 (à valider après volume bench)

| Tâche | Modèle | Latence est. | Justification |
|---|---|---|---|
| QC vision primary | **qwen3.5:9b** | ~2.3 s/image | 8.4× plus rapide, 5/6 sur ce bench |
| QC vision arbitre (cas marginaux) | gemma4:26b | ~19 s/image | Plus précis sur couleurs subtiles, fallback |
| Pre-check couleurs | Pillow histogram | <10 ms/image | Déterministe, gratuit, force `poor` si couleur > seuil |

### Question résolue
**qwen3.5:9b remplace gemma4:26b ?** → **OUI partiel**. Comme primary avec fallback gemma4 sur les cas où qwen3.5 dit "good" mais Pillow histogram suggère couleurs. **NON** comme remplacement total sans garde-fou — la régression sur "couleurs accidentelles" est trop spécifique pour conclure sur 6 images.

### Question ouverte
- **Volume bench QC vision** : 50+ images variées (mix good/poor avec catégories de défaut) sur qwen3.5:9b pour mesurer précision réelle. À faire avant codage du worker QC P3.
- **Concurrence Ollama** : tester 2 calls qwen3.5:9b en parallèle pour vérifier que l'instance distante gère sans dégradation (timeouts, ralentissements).

## Annexes

- Données brutes : `2026-05-05_poc-qwen35-vision.json`
- Script : `scripts/poc_qwen35_vision.py`
- Référence gemma4 baseline : `2026-05-05_poc-llm-benchmark-v2.md` (vision section, 6/6)
- Référence batch unitaire : `2026-05-05_poc-vision-batch.md` (config unit 1×6)
