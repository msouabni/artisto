# POC — Benchmark LLM v2 (6 modèles + vision)
Date : 2026-05-05

## Contexte
Bench étendu après POC-LLM v1 : tester 6 modèles disponibles sur l'Ollama du projet (10 paires AR + 5 termes feuilles concepts + 6 images vision sur 2 modèles multimodaux). Objectif : confirmer ou changer le choix LLM pour P2 (génération i18n + suggest_children) et identifier un modèle vision pour le QC P3.

## Étape 0 — Inventaire confirmé

`GET /api/tags` → 6/6 modèles attendus présents :

| Modèle | Famille | Paramètres | Taille | Pre-flight ping |
|---|---|---|---|---|
| `qwen2.5:7b` | qwen2 | 7.6 B | 4.36 GB | ✓ 6.2 s |
| `qwen3:8b` | qwen3 | 8.2 B | 4.87 GB | ✓ 6.8 s |
| `qwen3.5:9b` | qwen35 | 9.7 B | 6.14 GB | ✓ 11.4 s (mais bloque sur prompts réels — voir section dédiée) |
| `qwen3.5:4b` | qwen35 | 4.7 B | 3.16 GB | ✓ 7.7 s (idem) |
| `gemma4:26b` | gemma4 | 25.8 B | 16.75 GB | ✓ 14.1 s (1ère fois 45s+ : modèle pas chargé en RAM) |
| `aya-expanse:8b` | command-r | 8.0 B | 4.71 GB | ✓ 6.9 s |

**Fix appliqué** par rapport au v1 : ajout d'un pre-flight ping 30 s avant le bench (un modèle gros peut prendre 30+ s à charger en RAM la 1ʳᵉ fois ; éviter de l'inclure si toujours bloqué). Ici tous OK après une 2ᵉ tentative pour gemma4.

## Étape 1 — Tâche AR ancrée (10 paires, Prompt A POC-4)

Bornes : `title ∈ [25, 55]`, `description ∈ [40, 100]`.

| Modèle | JSON | Anchor | title bornes | desc bornes | Harakat clean | Latin clean | Lat. moy. |
|---|---|---|---|---|---|---|---|
| **qwen3:8b** | 10/10 | **9/10** ✅ | 8/10 | **10/10** ✅ | 8/10 | 8/10 | 12.4 s |
| **gemma4:26b** | 10/10 | 8/10 | **10/10** ✅ | **10/10** ✅ | **10/10** ✅ | **10/10** ✅ | 80.5 s ⚠ |
| qwen2.5:7b | 10/10 | 7/10 | 0/10 | 4/10 | **10/10** | 8/10 | **1.9 s** ⚡ |
| aya-expanse:8b | 10/10 | 7/10 | 2/10 | 3/10 | 9/10 | **10/10** | **2.8 s** ⚡ |

**Findings** :
- **gemma4:26b est le seul à respecter strictement TOUTES les contraintes du contrat AR** (bornes 10/10, harakat 10/10, latin 10/10). Coût : ×40 latence vs qwen2.5:7b.
- qwen3:8b bon compromis qualité/latence (8-10/10 sur tout, latence 12 s acceptable par image).
- qwen2.5:7b + aya-expanse:8b échouent largement les bornes longueur (0-4/10). Inutilisables sans validate-regen.

## Étape 2 — Tâche concepts (suggest_children, 5 termes feuilles)

| Modèle | JSON | name_ar OK | Cross-locale suspect | Doublons existants | Lat. moy. |
|---|---|---|---|---|---|
| **qwen3:8b** | **5/5** ✅ | 25/25 | 1/25 | **1/25** ✅ | 30.3 s |
| **aya-expanse:8b** | **5/5** ✅ | 25/25 | **0/25** ✅ | **0/25** ✅ | 11.0 s ⚡ |
| qwen2.5:7b | 5/5 | 25/25 | 1/25 | 4/25 ⚠ | 7.5 s |
| **gemma4:26b** | **2/5** ❌ | 10/10 | 0/10 | 1/10 | 101.9 s ❌ |

**Findings** :
- **gemma4:26b inutilisable pour concepts** : 3/5 timeout 120 s. Le prompt concepts (~1400 chars + JSON output complexe) excède les 120 s sur ce modèle. Pour le rendre viable il faudrait bumper timeout à 300 s+ et accepter 100+ s de latence par appel.
- **aya-expanse:8b parfait sur cross-locale + dup** (0/25 + 0/25), avec latence excellente. Surprise positive sur concepts.
- qwen3:8b solide partout, latence acceptable.
- qwen2.5:7b : 4 doublons sur 25 enfants — moins fiable pour étendre la taxonomie.

## Étape 3 — Vision QC (gemma4:26b uniquement)

Note : qwen3.5:9b est censé tester aussi mais a été skippé pour le bench vision pour cause d'échec total sur AR/concepts (cf. section dédiée plus bas).

6 images : 2 ground-truth `poor` (1 image vide-texte, 1 avec couleurs/gradients), 4 `good` (line arts propres).

| Image (ground truth) | Verdict gemma4 | Confiance | Issues retournées | Lat. |
|---|---|---|---|---|
| `animaux_chat_collier_…` (poor) | **poor** ✅ | 100 | `["not_line_art", "incomplete"]` | 26.3 s |
| `adventure_in_scooby-doo-island_…` (poor) | **poor** ✅ | 100 | `["has_color", "not_line_art"]` | 14.2 s |
| `animals_bath_cat_…` (good) | **good** ✅ | 100 | `[]` | 10.5 s |
| `animals_party_decor_…` (good) | **good** ✅ | 100 | `[]` | 22.2 s |
| `animaux_chat_biblioth_que_…` (good) | **good** ✅ | 100 | `[]` | 31.3 s |
| `animals_fairy_cat_…` (good) | **good** ✅ | 100 | `[]` | 11.3 s |

**6/6 verdicts corrects, 6/6 issues détectées correctement, latence moyenne 19.3 s.**

gemma4:26b est exploitable pour le QC vision P3. Sur les 2 cas `poor`, il a identifié les bonnes raisons (`incomplete` pour l'image vide ; `has_color` pour l'image avec couleurs) — pas juste un binaire good/poor.

## Étape 4 — Tableau comparatif scoré

Pondération : AR sémantique (anchor) ×3, JSON fiable ×2, latence inversée ×2, AR bornes ×2, cohérence FR/EN ×1. Total max = 10, normalisé sur 100. Hors qwen3.5* (échec, voir section dédiée).

| Rang | Modèle | AR anchor | AR bornes | JSON | FR/EN | Lat. AR | Lat. concepts | Vision | **Score** |
|---|---|---|---|---|---|---|---|---|---|
| 🥇 | **qwen3:8b** | 9/10 | 18/20 | 15/15 | 24/25 | 12.4 s | 30.3 s | n/a | **87.5** |
| 🥈 | aya-expanse:8b | 7/10 | 5/20 | 15/15 | **25/25** | **2.8 s** | **11.0 s** | n/a | 73.7 |
| 🥉 | qwen2.5:7b | 7/10 | 4/20 | 15/15 | 24/25 | **1.9 s** | 7.5 s | n/a | 73.0 |
| 4 | gemma4:26b | 8/10 | **20/20** | 7/15 ⚠ | 10/10 | 80.5 s | 101.9 s ❌ | **6/6** ✅ | 68.0 |

L'ordre v2 confirme et étend l'ordre v1 :
- **qwen3:8b reste champion généraliste** (et le seul score ≥85 sur 4 modèles fonctionnels).
- gemma4:26b est **excellent qualité AR pure mais inutilisable concepts**, son intérêt principal est la **vision**.
- aya-expanse et qwen2.5 quasi à égalité globalement (~73), différenciés par leurs sweet spots (aya = cohérence + concepts, qwen2.5 = vitesse pure).

## qwen3.5 — échec mode thinking, re-test requis

Les 2 modèles `qwen3.5:9b` et `qwen3.5:4b` ont **systématiquement timeouté ou produit du JSON malformé** :

| Modèle | AR (10 paires) | Concepts (5) | Diagnostic |
|---|---|---|---|
| `qwen3.5:9b` | 0/10 (9 timeouts 120 s, 1 JSON KO 85 s) | 0/5 (5 timeouts) | Score "20.0" mécanique mais aucune donnée exploitable |
| `qwen3.5:4b` | partiel (avant kill) — pattern : 67 s, 95 s, timeout 120 s, 97 s, timeout… | non testé | Idem qwen3.5:9b |

**Hypothèse** : la fonction `apply_no_think_system` dans `src/services/ollama_json.py` désactive le mode thinking via `/no_think` en system prompt. La détection est `"qwen3" in model.lower()` qui matche bien `qwen3.5`, mais **le tag `/no_think` est probablement spécifique à Qwen3** et ne fonctionne pas sur Qwen3.5 (changement d'API côté modèle ?). Résultat : les modèles qwen3.5 raisonnent en `<think>…</think>` pendant 120 s+ avant de répondre, ce qui fait timeout.

**Action requise** : re-test ciblé avec :
- soit le paramètre `"think": false` natif Ollama dans le payload (équivalent moderne du `/no_think`),
- soit `"keep_alive": "0"` pour forcer le mode rapide,
- soit la nouvelle convention Qwen3.5 documentée upstream (à vérifier).

Pas inclus dans le classement final pour ne pas fausser la comparaison.

## Recommandation routing par tâche

| Tâche pipeline | Modèle recommandé | Latence est. | Justification |
|---|---|---|---|
| `generate_concepts` (depuis thème) | **qwen3:8b** | ~30 s | Bon compromis qualité (cross-locale 24/25), tolère latence (1× par lot de concepts). |
| `prompt_planner` (FR + EN) | **qwen3:8b** | ~12 s | Idem, bornes contrôlées. |
| `prompt_writer` (line-art prompt) | **qwen3:8b** | ~12 s | Idem. |
| `prompt_validator` (line-art quality) | **qwen3:8b** | ~12 s | Cohérent avec le reste de la chaîne. |
| `content` EN + FR (i18n) | **qwen3:8b** | ~12 s/locale | Anchor 9/10, bornes 8-10/10, harakat n/a sur EN/FR. |
| `content` AR (i18n ancré) | **qwen3:8b** primaire | ~12 s | Anchor 9/10. Si bornes ratées : retry 1× sur **gemma4:26b** (bornes 10/10) — coût latence ~80 s acceptable car rare. |
| `suggest_children` / `enrich_term` | **qwen3:8b** | ~30 s | 1/25 dup, 1/25 cross-locale suspect. **aya-expanse:8b** en fallback (0/25 sur les 2). |
| `QC vision` (P3) | **gemma4:26b** | ~19 s/image | 6/6 verdicts corrects, issues détectées avec précision. **Seul candidat vision viable** sur ce server. |
| Batch ultra-volumineux (cas isolé) | qwen2.5:7b ou aya-expanse:8b | ~2-3 s/AR | 7× plus rapide que qwen3:8b mais bornes faibles → ne JAMAIS sans validate-regen. |

**Pas de routing mixte critique nécessaire en P2** — qwen3:8b couvre AR + concepts. gemma4:26b uniquement pour vision (P3). aya-expanse:8b à garder en fallback de fallback si qwen3:8b sature en charge réelle.

## Décision / Action suivante

✅ **Choix LLM P2 confirmé : qwen3:8b** (cf. POC-LLM v1, validé v2).

✅ **Choix LLM vision P3 : gemma4:26b** — à activer dans le worker QC vision quand il sera implémenté.

✅ **aya-expanse:8b ajouté comme fallback secondaire** sur la tâche concepts (cohérence cross-locale parfaite à latence basse).

À mettre à jour côté config (déjà recommandé en POC-LLM v1) :
- `OLLAMA_MODEL=qwen3:8b` dans `.env`
- `defaults.model: qwen3:8b` dans `prompts/taxonomy_prompts.yaml` et `prompts/image_prompts.yaml`
- Documenter dans `CLAUDE.md` :
  - `qwen3:8b` → modèle texte par défaut
  - `gemma4:26b` → modèle vision (P3)
  - `aya-expanse:8b` → fallback concepts
  - `qwen2.5:7b` → fallback latence batch (validate-regen requis)

À traiter ailleurs :
- **Re-test qwen3.5*** avec correctif `think: false` natif Ollama — prompt suivant fourni par Claude Desktop.
- **Étendre `apply_no_think_system`** pour gérer Qwen3.5 (fix dans `src/services/ollama_json.py` quand le bon mécanisme sera identifié).

## Annexes

Données brutes : `2026-05-05_poc-llm-benchmark-v2.json`
Script principal : `scripts/poc_llm_benchmark_v2.py`
Log d'exécution : `logs/poc_llm_benchmark_v2.log`

**Caveats du run** :
- qwen3.5* exclu du classement (mode thinking non désactivé) — re-test ciblé requis.
- gemma4:26b concepts : 3/5 timeouts 120 s. Sa latence concepts réelle (sans cap) est inconnue mais ≥120 s, probablement ~150-200 s. Si gemma4 devait remplir la tâche concepts, prévoir timeout 300 s minimum.
- Latences mesurées sur appel froid pour le 1ᵉʳ pair de chaque modèle, plus chaud ensuite. Pour les chiffres "lat. moy." j'ai gardé la moyenne brute incluant le cold-start.
