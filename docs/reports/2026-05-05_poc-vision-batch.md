# POC vision batch — gemma4:26b sur 6 images, 4 stratégies d'appel
Date : 2026-05-05

## Contexte
gemma4:26b QC vision a été validé en POC-LLM-v2 avec **6/6 verdicts corrects** sur les mêmes 6 images, en appels unitaires à ~19.3 s/image. Question : peut-on **réduire la latence par image** en groupant plusieurs images dans un seul appel API ?

Test de 4 configurations sur les mêmes 6 images (4 good, 2 poor) avec ground truth déjà établie :
1. Unitaires (baseline) — 6 calls × 1 image
2. Batch 3 — 2 calls × 3 images
3. Batch 5 — 1 call × 5 images + 1 call × 1 image
4. Batch 6 — 1 call × 6 images

Modèle : `gemma4:26b` (T=0). API : `POST /api/generate` avec liste `images` base64 + prompt demandant un JSON array de verdicts indexés.

## Résultats

### Tableau comparatif

| Config | n_calls | verdicts corrects | total | s/image | JSON OK | issues overlap moy. |
|---|---|---|---|---|---|---|
| **unit (1×6)** | 6 | **6/6** ✅ | 116.4 s | 19.4 s | 6/6 | **1.00** |
| batch 3 | 2 | 5/6 | 96.6 s | 16.1 s | 2/2 | 0.83 |
| batch 5 | 2 | 3/6 | 108.5 s | 18.1 s | 2/2 | 0.33 |
| **batch 6** | 1 | **2/6** ❌ | 87.8 s | 14.6 s | 1/1 | **0.17** |

### Observation décisive : le modèle ne distingue pas les images en batch

En **batch 5 et batch 6**, le détail des verdicts retournés montre un comportement **catastrophique** :

| Image | Ground truth | Verdict batch 5 | Verdict batch 6 |
|---|---|---|---|
| animaux_chat_collier (vide-texte) | poor | poor ✓ | poor ✓ |
| adventure_scooby (couleurs) | poor | poor ✓ | poor ✓ |
| animals_bath_cat | good | **poor ✗** | **poor ✗** |
| animals_party_decor | good | **poor ✗** | **poor ✗** |
| animaux_chat_biblioth_que | good | **poor ✗** | **poor ✗** |
| animals_fairy_cat | good | (call 2 unit) ✓ | **poor ✗** |

**Toutes les images "good" sont marquées "poor / not_line_art" en batch ≥ 5.** Le modèle juge la **série** comme "pas du line art" plutôt que chaque image individuellement, malgré le prompt explicite "image_index 1, 2, 3…".

En **batch 3**, dégradation déjà commencée : 1 verdict erroné sur 6.

En **unit (1×1)**, comportement parfait : 6/6 corrects, issues précisément identifiées (`incomplete + not_line_art` pour la vide-texte, `has_color` pour celle aux couleurs, `[]` pour les good).

### Hypothèse — pourquoi le batch échoue

Quand Ollama envoie `images: [b64_1, b64_2, …, b64_N]` à gemma4:26b dans un seul `/api/generate`, le modèle voit une **scène composite** (toutes les images dans son contexte visuel global) et ne sait pas attribuer un verdict par image, malgré le `image_index` demandé. Comportement par défaut : retourner un verdict global (pessimiste : "poor not_line_art" sur la majorité des frames).

→ La capacité multi-image d'Ollama n'est pas un broadcasting "1 prompt × N inférences indépendantes", c'est un appel mono-inférence avec N images dans un contexte mêlé. **Inadapté au QC par-image**.

### Latence : gain marginal qui ne compense pas la perte qualité

Sur le total wall-clock :
- unit : 116 s pour 6 images
- batch 6 : 88 s → gain ~24 % de latence

Mais à 2/6 verdicts corrects (33 % précision), c'est strictement inutilisable. Le coût du pipeline pour rejeter les faux-positifs (re-vérification humaine ou retry unitaire) annule largement le gain.

## Points d'attention

- **Ne jamais batcher gemma4:26b vision pour du QC par-image** sur Ollama. Le modèle ne supporte pas le pattern "N images, N verdicts".
- **Les 2 cas "poor" sont robustement détectés** dans les 4 configs (anchor de qualité du modèle). Le problème vient des **faux positifs sur les "good"** en batch.
- **issues overlap chute à 0.17 en batch 6** : non seulement le verdict global est faux mais les issues retournées sont génériques ("not_line_art" sur tout).
- **Latence unitaire 19 s reste élevée** pour de la prod massive. Si on doit traiter 100 images/jour, ça fait ~30 min séquentiel — gérable. Si 1000+/jour, il faut paralléliser.
- **Pas testé** : batch via plusieurs `/api/chat` séquentiels avec 1 image chacun mais en réutilisant la session keep-alive du modèle. Pourrait amortir le cold-load. Sortie de scope POC actuel.

## Décision / Action suivante

❌ **Le batching d'images dans un seul appel API est rejeté pour la prod.**

✅ **Recommandation pour P3 (worker QC vision)** :

| Aspect | Décision |
|---|---|
| Taille de batch API | **1 image par call** (unitaire) |
| Latence prod attendue | ~19 s/image |
| Si débit insuffisant | **Paralléliser plusieurs workers QC** (multi-thread ou multi-process) appelant chacun gemma4:26b en unitaire. Le serveur Ollama gère les requêtes concurrentes en parallèle (à valider, mais probable). |
| max_concurrent du worker QC | À calibrer en POC P3 : combien de calls gemma4:26b en parallèle l'Ollama remote tient avant dégradation. Cible initiale : 2-3 workers. |
| Cible débit | ~9-15 images/min avec 3 workers parallèles (~6-9 s/image effectif si Ollama serve correctement) |

Si dans la pratique l'Ollama remote sature à 1 inférence vision concurrente : envisager **un upgrade infra dédiée GPU pour le worker QC** (gemma4:26b est gros — 16.75 GB en RAM, possiblement le bottleneck).

📋 **Question résolue** : taille de batch optimale ? **1 image par call** (= unit). Tout batch ≥ 3 dégrade la précision verdicts.

📋 **Question ouverte (hors scope)** : tester si plusieurs `/api/generate` parallèles vers gemma4:26b sur l'Ollama remote tiennent la cadence sans dégradation. À adresser au moment d'implémenter le worker QC P3.

## Annexes

- Données brutes : `2026-05-05_poc-vision-batch.json`
- Script : `scripts/poc_vision_batch.py`
- Référence baseline unit : `2026-05-05_poc-llm-benchmark-v2.md` (vision section)
