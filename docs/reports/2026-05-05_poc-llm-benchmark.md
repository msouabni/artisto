# POC — Benchmark comparatif modèles Ollama
Date : 2026-05-05

## Contexte
Avant de figer le choix LLM pour la Phase 2 (génération i18n + suggest_children + validation IA contenu), comparer les modèles texte disponibles sur l'Ollama du projet sur les deux tâches critiques : génération AR ancrée et suggestion de termes enfants. Recommandation pour figer (ou pas) `OLLAMA_MODEL` du projet.

## Étape 0 — Inventaire modèles disponibles

`GET http://100.65.24.35:11434/api/tags` :

| Modèle | Famille | Paramètres | Taille |
|---|---|---|---|
| `qwen2.5:7b` | qwen2 | 7.6 B | 4.36 GB |
| `qwen3:8b` | qwen3 | 8.2 B | 4.87 GB |

Aucun LLaVA listé. Les 2 modèles disponibles sont tous deux Qwen, génération suivante (3 vs 2.5).

## Étape 1 — Tâche AR ancrée (Prompt A POC-4, 10 paires)

Bornes ajustées par rapport à POC-4 (recalibrage densité AR) : title `[25, 55]`, description `[40, 100]`.

| Métrique | qwen2.5:7b | qwen3:8b |
|---|---|---|
| JSON parsable | 10/10 | 10/10 |
| Anchor présent (term_ar / synonyme dans title+desc) | **7/10** | **8/10** |
| `title` dans bornes [25, 55] | **0/10** | **9/10** ✅ |
| `description` dans bornes [40, 100] | 4/10 | **10/10** ✅ |
| Harakat absents | **10/10** ✅ | 9/10 |
| Latin absents | **8/10** | 7/10 |
| Latence moyenne AR | **1.7 s** ✅ | 11.9 s |

**Gap qualité critique** : qwen3:8b respecte les bornes de longueur (9-10/10) là où qwen2.5:7b les viole quasi systématiquement (0-4/10). C'est probablement le différenciateur le plus important pour P2 : prompt-only "one shot" suffit avec qwen3, alors que qwen2.5 nécessitera obligatoirement une boucle validate-regen.

**Régression observée** : qwen3 introduit parfois des harakat (1/10) et plus de latin (3/10 vs 2/10). Pas dramatique mais à valider en post-LLM.

## Étape 2 — Tâche concepts (suggest_children, 5 termes feuilles)

Termes choisis (catégories variées) : `animaux_marins`, `noel`, `mandalas_fleurs`, `voitures`, `science`. Appel direct Ollama (pas via API queue) avec le template YAML `prompts/taxonomy_prompts.yaml`.

| Métrique | qwen2.5:7b | qwen3:8b |
|---|---|---|
| JSON parsable | 5/5 | 5/5 |
| Total enfants générés | 25 | 25 |
| `name_ar` présent et 1-4 mots | 25/25 | 25/25 |
| Cross-locale suspect (heuristique) | 1/25 | **0/25** ✅ |
| Doublons avec termes existants | **3/25** ⚠ | **0/25** ✅ |
| Latence moyenne concepts | **7.4 s** ✅ | 26.4 s |

**qwen3:8b parfait sur cohérence et déduplication**. Pas d'erreur du type "Égouts pour tracteur" qu'on avait observée sur qwen2.5 dans POC-1. Le coût : ~3.5× plus lent.

## Étape 3 — Synthèse + score composite

Pondération : AR sémantique (anchor) ×3, JSON fiable ×2, latence ×2 (inversée), AR bornes ×1, cohérence FR/EN ×1. Total max = 9, normalisé sur 100.

| Modèle | Taille | AR sémantique | AR bornes | JSON fiable | Cohérence FR/EN | Latence AR | Latence concepts | **Score** |
|---|---|---|---|---|---|---|---|---|
| `qwen2.5:7b` | 7.6 B | 7/10 | 4/20 | 15/15 | 24/25 | 1.7 s ✅ | 7.4 s ✅ | **79.0** |
| `qwen3:8b` | 8.2 B | 8/10 | **19/20** | 15/15 | **25/25** | 11.9 s | 26.4 s | **85.7** ✅ |

**Classement : qwen3:8b > qwen2.5:7b** de 6.7 points. L'écart est modéré, dominé par les bornes de longueur AR (qwen3 fait du one-shot publishable, qwen2.5 nécessite regen).

## Recommandation

### Routing optimal par tâche

| Tâche | Modèle recommandé | Raison |
|---|---|---|
| Génération contenu i18n AR (P2) | **qwen3:8b** | Bornes respectées, harakat clean ~90 %, anchor 8/10. Tolère la latence (1× par image). |
| `suggest_children` taxonomie | **qwen3:8b** | Cohérence cross-locale parfaite, 0 doublon. Critique pour qualité de la base. |
| `enrich_term` (lot ponctuel) | qwen3:8b | Même profil que suggest_children. |
| QC vision (LLaVA) | n/a — modèle dédié à provisionner | Aucun LLaVA disponible aujourd'hui sur le serveur. |
| Tâches batch très volumineuses | qwen2.5:7b en fallback | 7× plus rapide ; acceptable si validation post-LLM systématique. |

### Configuration projet à mettre à jour

- **`OLLAMA_MODEL` par défaut → `qwen3:8b`** (`.env` + `defaults.model` dans `prompts/taxonomy_prompts.yaml` + `prompts/image_prompts.yaml`).
- Toujours possibilité de **surcharger via le body API** (`model: "qwen2.5:7b"` dans la requête) pour les jobs où la latence prime — déjà supporté dans le code projet.
- Activer **boucle validate-regen** systématique en P2, budget 2-3 retries, parce que qwen3:8b ne respecte pas non plus 100 % les harakat/latin.

### Caveats à surveiller

- **Latence cumulée P2** : si une image nécessite ~12 s/locale × 3 locales × 2 retries possibles = ~72 s/image worst case. À mesurer sur batch réel avant production.
- **Aucun LLaVA disponible** : pour le QC vision (P3), il faut soit `ollama pull llava:latest`, soit choisir un autre VLM compatible. À adresser avant Phase 3.
- **Mode thinking de qwen3** : le projet gère déjà `/no_think` en system prompt (`apply_no_think_system` dans `services/ollama_json.py`). Validé empiriquement ici (pas de balises `<think>` parasites observées). À ne pas désactiver.
- **Cache Ollama** : les latences mesurées pour qwen2.5:7b sur AR sont anormalement basses (~1.5 s) probablement à cause d'un cache de réponses identiques (T=0 + même prompt). Sur prompts inédits, prévoir 4-7 s comme dans POC-4.

## Décision / Action suivante

✅ **Choix LLM pour P2 : qwen3:8b**.

À mettre à jour :
1. `OLLAMA_MODEL=qwen3:8b` dans `.env`
2. `defaults.model: qwen3:8b` dans `prompts/taxonomy_prompts.yaml` et `prompts/image_prompts.yaml`
3. Documenter dans CLAUDE.md (section "Key environment variables") que `qwen3:8b` est le défaut et `qwen2.5:7b` un fallback latence

À provisionner avant **Phase 3** :
- Pull `llava` (ou modèle VLM équivalent) sur l'Ollama remote pour le QC vision

À valider sur **batch réel** avant production :
- Latence cumulée par image (i18n × 3 locales × retries) sur un lot de 50 images
- Stabilité harakat/latin de qwen3:8b sur volume

## Annexes

Données brutes : `2026-05-05_poc-llm-benchmark.json`
Script : `scripts/poc_llm_benchmark.py`

Bug fix relevé pendant le POC : la regex `[ؐ-ًؚ-ٟ]` (codepoints harakat) a vu son ordre de caractères réécrit par le RTL au copier-coller depuis le brief, et incluait alors **toutes les lettres arabes** (range U+0610-U+064B au lieu des 2 ranges étroites U+0610-U+061A et U+064B-U+065F). Corrigé via codepoints explicites dans le source — à propager si la même regex est réutilisée ailleurs (notamment dans `poc_ar_anchored_content.py` qui marche par chance avec le bon ordre, et dans le futur module AR slug en `src/`).
