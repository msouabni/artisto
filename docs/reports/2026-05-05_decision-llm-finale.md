# Décision LLM finale — clôture chapitre benchmark
Date : 2026-05-05

## Contexte
Clôture de la séquence d'arbitrage du choix LLM pour le pipeline artiste-coloriage. Cette analyse documente :
- la séquence des POC effectués sur la journée
- les décisions actées
- le routing final par tâche
- ce qui reste à valider en P3

## Séquence des POC (chronologique)

| # | POC | Question centrale | Verdict |
|---|---|---|---|
| 1 | `2026-05-05_poc-llm-benchmark.md` (v1) | Comparer les 2 modèles dispos (qwen2.5:7b vs qwen3:8b) | qwen3:8b champion à **87.5/100** |
| 2 | `2026-05-05_poc-llm-benchmark-v2.md` | Étendre à 6 modèles (Qwen 2.5/3/3.5, gemma4, aya-expanse) + ajouter tâche vision | qwen3:8b confirmé champion. **gemma4:26b validé vision 6/6**. **qwen3.5:9b et qwen3.5:4b échouent (0/15)** — diagnostic mode thinking non désactivé |
| 3 | `2026-05-05_poc-qwen35-retest.md` | Fixer qwen3.5* via paramètre natif Ollama `"think": false` | **Fix validé** : qwen3.5:9b passe 0→79.4, **qwen3.5:4b passe à 98.2/100 (nouveau champion)** sur 10 paires |
| 4 | `2026-05-05_poc-qwen35-volume.md` | Stabilité de qwen3.5:4b sur 50 paires + bug parser concepts | 38 paires effectives (taxonomie limite) : **stable** mais desc bornes 24/38 et harakat 28/38 → **regen loop + strip harakat requis**. Bug parser corrigé (fallback array + strip ``` orphelins) |
| 5 | `2026-05-05_poc-vision-batch.md` | Réduire latence vision via batching plusieurs images/call | **Batching contre-productif** : verdicts corrects 6→2 quand on passe unit→batch 6. À garder en unitaire et paralléliser |
| 6 | `2026-05-05_poc-qwen35-vision.md` | qwen3.5:9b est-il multimodal et peut-il remplacer gemma4 ? | **Multimodal validé**. 5/6 sur les 6 images, **8.4× plus rapide** (2.3 s vs 19 s/image), 2 workers possibles sur 16 GB VRAM. **Faux négatif sur 1 cas couleurs** → fallback gemma4 + Pillow pre-check |
| 7 | `2026-05-05_poc-qualitative-mickey.md` | Test qualitatif réel sur thème "Mickey Mouse" : 20 concepts + 5 i18n complets | Toutes les générations OK (15/15 JSON valides), latence stable EN/FR ~1.6 s, AR ~2.3 s. Pattern de dépassement borne EN desc confirmé (regen loop appliqué en prod) |

## Décisions actées

### 1. Modèle texte primaire : qwen3.5:4b

Champion absolu sur 4 axes :
- **Qualité** : score composite **98.2/100** (vs 87.5 pour qwen3:8b)
- **Latence** : ~2.2 s/call AR (vs 12.4 s qwen3:8b → **5× plus rapide**)
- **Empreinte** : 3.16 GB (vs 4.87 GB qwen3:8b → **−35 % RAM**)
- **Cohérence cross-locale** : 0 doublon + 0 suspect cross-locale FR/EN

Caveats actés :
- **Description AR dépasse souvent la borne haute 100** (37 % de retry attendu sur le validate-regen loop)
- **Harakat occasionnels** (~26 % des outputs) → strip post-process systématique recommandé (instantané, sans regen)

### 2. Fix critique : `apply_no_think_system` corrigé

Le tag `/no_think` est **spécifique à qwen3 strict** et n'opère **pas** sur qwen3.5. Sans ce fix, qwen3.5* timeoutent systématiquement (modèles bloqués à raisonner en `<think>…</think>` jusqu'au timeout).

Fix implémenté dans `src/services/ollama_json.py` (et miroir async dans `src/api/routes/ai.py`) :
- Détection `"qwen3:" in name AND "qwen3." not in name` → `/no_think` system tag
- Détection `"qwen3." in name` → paramètre natif Ollama `"think": false` dans le payload
- Documenté dans le code (docstrings) et CLAUDE.md (section Routing LLM)

### 3. Bug parser corrigé — `parse_json_response`

`src/services/ollama_json.py::parse_json_response` étendu pour gérer :
- balises markdown ` ``` ` orphelines (modèles qui ferment sans ouvrir, ou inversement)
- fallback **`[...]` array AVANT `{...}` object** (sinon une réponse type "liste avec trailing junk" n'extrait que le 1er élément)

Effet de bord positif : tous les workers LLM API du projet (suggest_children, enrich_term, generate_concepts, etc.) bénéficient automatiquement.

### 4. QC vision : 2-tiers (qwen3.5:9b primaire + gemma4:26b arbitre)

| Aspect | Décision |
|---|---|
| Primaire | qwen3.5:9b — 8.4× plus rapide, 2 workers possibles sur 16 GB VRAM |
| Faiblesse couverte | Pillow histogram pre-check (>seuil pixels non-monochromes → force `poor` même si LLM dit `good`) |
| Arbitre | gemma4:26b sur cas où qwen3.5 dit "good" mais histogram suggère couleurs |
| Batching | **Toujours unitaire** (1 image / call). Le batching dégrade fortement la précision verdicts |

### 5. Bornes Zod plateforme vs SOFT caps pipeline

Confirmé par Alwan Books le 2026-05-05 (cf. `2026-05-05_analyse-bornes-validation.md`) : les hard caps Zod sont **uniformes toutes locales** (`title [5,100]`, `title_card [5,40]`, `description [20,200]`). Nos SOFT caps internes sont strictement inclus dans les HARD → tout contenu validé en interne est publiable côté plateforme sans risque de build cassé.

## Routing final par tâche

| Tâche | Modèle | Rôle |
|---|---|---|
| Texte EN/FR/AR (i18n, concepts, enrichissement) | **qwen3.5:4b** | Primaire |
| Texte fallback qualité | qwen3:8b | Si qwen3.5:4b dérive ou plante |
| Concepts fallback cohérence | aya-expanse:8b | 0 dup / 0 cross-locale suspect |
| Texte fallback vitesse batch | qwen2.5:7b | Pure latence (regen obligatoire) |
| QC vision (P3) | **qwen3.5:9b** | Primaire — volume 50+ requis avant prod |
| QC vision arbitre | gemma4:26b | Faux-négatif couleurs |

Configuration projet alignée :
- `.env` : `OLLAMA_MODEL=qwen3.5:4b`
- `prompts/taxonomy_prompts.yaml` : `defaults.model: qwen3.5:4b`
- `prompts/image_prompts.yaml` : `defaults.model: qwen3.5:4b`
- `CLAUDE.md` : section *Routing LLM (acté 2026-05-05)* avec tableau complet et mécaniques (`/no_think` vs `think: false`, strip harakat, validate-regen)

## Ce qui reste à valider en P3 (hors scope LLM)

| Test | Question | Bloquant |
|---|---|---|
| **Volume vision 50+ images** | qwen3.5:9b reste-t-il à ~83 % sur un mix représentatif (4 catégories de défauts × 12 images chacune) ? | Avant codage worker QC P3 |
| **Concurrence Ollama** | 2 calls qwen3.5:9b vision en parallèle → l'instance distante tient ou queue ? Quel max_concurrent prudent ? | Avant codage worker QC P3 |
| **Latence cumulée prod** | Sur batch réel de 50 images : pipeline complet (3 locales × validate-regen × QC vision × Pillow check) tient le SLA ? | Validation prod P2+P3 |
| **Drift qwen3.5:4b en prod** | Distribution réelle des longueurs description AR (médiane / quantiles) sur 200+ outputs réels — recalibrer borne haute si nécessaire | Continu après mise en prod |
| **Pillow histogram pre-check** | Implémenter le check couleur déterministe (5-10 ms) en parallèle du LLM vision, fixer le seuil "% pixels non-monochromes" qui flagge un faux-négatif gemma | Conception worker QC P3 |

## Annexes

Rapports POC dans l'ordre chronologique de la session :
- `2026-05-05_poc-llm-benchmark.md` (.json)
- `2026-05-05_poc-llm-benchmark-v2.md` (.json)
- `2026-05-05_poc-qwen35-retest.md` (.json)
- `2026-05-05_poc-qwen35-volume.md` (.json)
- `2026-05-05_poc-vision-batch.md` (.json)
- `2026-05-05_poc-qwen35-vision.md` (.json)
- `2026-05-05_poc-qualitative-mickey.md` (.json)

Code touché côté `src/` :
- `src/services/ollama_json.py` — `apply_no_think_system`, `_supports_native_think_disable`, `parse_json_response`, `call_ollama_sync`
- `src/api/routes/ai.py` — `_apply_no_think_system`, `_native_think_disable`, payload think param

Config :
- `.env` (OLLAMA_MODEL)
- `prompts/taxonomy_prompts.yaml` (defaults.model)
- `prompts/image_prompts.yaml` (defaults.model)
- `CLAUDE.md` (routing LLM + clarification HARD/SOFT bornes)
- `docs/workflow-pipeline.md` (Phase 3 ⑥b + §7 bornes)
