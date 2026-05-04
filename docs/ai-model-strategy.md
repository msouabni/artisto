# Stratégie des modèles IA (Ollama)

Document de référence pour les choix de modèles LLM, leur historique dans ce dépôt, la logique de sélection dans le code et les pistes d’optimisation à évaluer. Complémentaire à [tuning-guide.md](tuning-guide.md) (réglages ComfyUI / Z-Image) qui couvre la génération d’images, pas les LLM.

---

## Historique des changements


| Date      | Décision                                                         | Détail                                                                                                                                                                                                                                                                                                                        |
| --------- | ---------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Précédent | `qwen3:8b` dans les prompts taxonomie YAML                       | Modèle puissant mais souvent en mode *thinking* ; latence plus élevée et réponses parfois précédées de blocs de raisonnement. Les endpoints structurés (`enrich-term`, JSON strict) ont montré des **timeouts HTTP 504** lorsque le timeout effectif côté appel était trop court (ex. 60 s) face à un serveur Ollama distant. |
| Actuel    | `**qwen2.5:7b*`* comme défaut pour la taxonomie                  | Modèle plus adapté aux sorties **JSON courtes et déterministes**, meilleur compromis latence / qualité pour noms, descriptions multilingues et enrichissement. Documenté comme défaut dans le README et dans `OLLAMA_MODEL`.                                                                                                  |
| Actuel    | `**defaults.timeout: 180`** dans `prompts/taxonomy_prompts.yaml` | Aligné avec `OLLAMA_TIMEOUT` typique côté `.env` pour que `_resolve_model_temp` + lecture du timeout YAML n’affiche pas de 504 prématurées vers Ollama distant.                                                                                                                                                               |


À mettre à jour manuellement lors de prochains changements significatifs (modèle, timeout, migration vers queue dédiée).

---

## Où le modèle est choisi (ordre de priorité)

Dans `[src/api/routes/ai.py](../src/api/routes/ai.py)`, la fonction `_resolve_model_temp` applique :

1. `**model` dans le body** de la requête (ex. sélection dans `taxonomy_editor.html` / `images_editor.html`) — prioritaire.
2. `**model` du template** : pour la taxonomie, fusion `taxonomy_prompts.yaml` + éventuelle surcharge table `ai_prompt_template` en base.
3. `**OLLAMA_MODEL`** (variable d’environnement), avec repli codé `**qwen2.5:7b**` si la variable est absente.

Le **timeout HTTP** vers Ollama pour les flux taxonomie utilise en pratique `defaults.timeout` du YAML (voir `enrich_term`, etc.), pas uniquement `OLLAMA_TIMEOUT` — d’où l’importance d’aligner les deux.

Les prompts **images** (line art, planner, etc.) vivent dans `[prompts/image_prompts.yaml](../prompts/image_prompts.yaml)` : logique distincte, pas de fusion DB comme pour la taxonomie. Le choix du **writer / validate / improve** pour le pipeline v1 suit le champ optionnel `workflow_template` : défaut **Ernie** (`*_ernie`) ; **Z-Image** uniquement si `workflow_template` = `z_image_turbo_v1` ; voir `resolve_image_prompt_template_keys` dans `src/api/routes/ai.py`.

---

## Orientations à terme

L’objectif est de **converger vers un bon compromis** qualité / latence / coût opérationnel, par itérations mesurées — pas en optimisant trop tôt sans métriques.

### Un modèle « passe-partout » vs plusieurs modèles

- **Un seul modèle** (ex. `qwen2.5:7b`) pour taxonomie + prompts courts : simplifie la config, évite les bascules coûteuses côté serveur Ollama.
- **Modèles spécialisés** (ex. plus gros pour rédaction longue, plus petit pour JSON strict) : peut améliorer la qualité par tâche, mais multiplie les points de réglage et les risques d’incohérence si ce n’est pas documenté (comme ce fichier).

### Impact chargement / déchargement mémoire (Ollama)

- Avoir **plusieurs modèles différents** sur la même machine Ollama peut entraîner des **chargements successifs** (latence au premier appel après changement de modèle, pression VRAM/RAM selon configuration).
- Garder **un modèle chaud** sur une file dédiée ou une politique « un modèle par worker » réduit les allers-retours — à valider sur votre matériel.

### Jobs par batch

- Les endpoints `**enrich-terms-batch`** agrègent plusieurs termes en **un** appel LLM : amortit le coût fixe du prompt et peut réduire le nombre d’allers-retours réseau.
- Limite : prompt plus long, risque de timeout si beaucoup de termes — ajuster la taille des lots et le timeout.

### Queue locale / workers

- Le projet a déjà une **queue de jobs** (`text_enrichment`, workers dans `src/workers/`, voir [README](../README.md)) : l’idée d’une **queue locale dédiée au texte** peut lisser la charge vers Ollama au lieu de saturer l’API synchrone depuis le navigateur.
- Piste future : mesurer la latence ressenti vs charge parallèle avant d’ajouter de la complexité.

---

## Démarche de test recommandée

1. **Métriques simples** : temps de réponse médian / p95 sur `POST /api/ai/enrich-term`, taux de **504**, taux d’échec **JSON** (`422` / parsing).
2. **Qualité métier** : échantillon de termes enrichis relus (cohérence SEO, respect des langues, pas de fuite du format).
3. **Comparaison A/B** : deux modèles sur le même jeu de termes et mêmes champs demandés ; noter temps + qualité subjective.
4. **Décision** : changer de modèle ou de timeout uniquement quand une métrique ou un retour utilisateur le justifie.

---

## Fichiers de configuration utiles


| Fichier                                                             | Rôle                                                                                         |
| ------------------------------------------------------------------- | -------------------------------------------------------------------------------------------- |
| `[.env](../.env)`                                                   | `OLLAMA_BASE_URL`, `OLLAMA_MODEL`, `OLLAMA_TIMEOUT`                                          |
| `[prompts/taxonomy_prompts.yaml](../prompts/taxonomy_prompts.yaml)` | Modèles et timeouts par type de prompt taxonomie                                             |
| `[prompts/image_prompts.yaml](../prompts/image_prompts.yaml)`       | Modèles pour pipelines images (planner commun ; défaut writer/validate Ernie, opt-in Z-Image via `workflow_template`) |
| `[src/api/routes/ai.py](../src/api/routes/ai.py)`                   | Résolution modèle/température, appels Ollama, parsing JSON des sorties LLM (voir ci-dessous) |


---

## Réponses JSON des LLM : correction nécessaire

Les modèles **ne garantissent pas** une sortie JSON strictement valide, même lorsque le prompt impose « JSON uniquement ». C’est attendu côté produit : le pipeline **normalise** la chaîne avant `json.loads`, puis certains endpoints **réinterprètent** le résultat partiel si besoin.

### Ce que fait le code (`src/api/routes/ai.py`)

1. `**_strip_think_tags`** — Supprime les blocs de raisonnement (ex. Qwen3) placés **avant** le JSON.
2. `**_repair_json_llm_typos`** — Corrections heuristiques sur le **texte brut** (ex. clé mal fermée : `, ""weight":` → `, "weight":`). La liste de motifs doit rester **courte et documentée** ; élargir uniquement face à des échecs mesurés en production ou en tests.
3. `**_parse_json_response`** — `json.loads` sur la chaîne corrigée ; en échec, extraction depuis un bloc markdown ````json` ou recherche du premier tableau / objet **potentiellement** valide par scans de crochets / accolades (heuristique, avec limites si imbrications ou guillemets internes).
4. **Endpoints type `generate-concepts`** — Si le parseur ne retourne qu’un **objet** unique (dict) avec un `id` alors qu’un **tableau** était attendu, une **conversion en liste d’un élément** évite des `suggestions: []` alors que `raw_response` est rempli (cas typique : tableau JSON **cassé** au milieu, seul le premier objet étant extrait par l’heuristique).

Sans ces étapes, une **seule** erreur de syntaxe (une clé avec un guillemet en trop) peut invalider **tout** le tableau : l’API peut alors renvoyer HTTP 200 avec `suggestions` vide et `raw_response` long, ce qui ressemble à un bug d’affichage alors que la cause est **parsing côté serveur**.

### Bonnes pratiques

- Continuer à mesurer les **422** « non parsable en JSON » et les taux de sorties vides malgré `raw_response` non vide.
- Préférer **compléter `_repair_json_llm_typos`** pour les fautes **récurrentes** plutôt que d’alourdir indéfiniment l’extracteur par crochets.
- Ne pas compter sur `format: "json"` côté Ollama pour les modèles *thinking* : le code **n’utilise pas** ce flag au profit d’un parsage tolérant (voir commentaires dans `_call_ollama`).

---

## Voir aussi

- [README — Variables d'environnement](../README.md#variables-denvironnement)
- [Tuning guide ComfyUI](tuning-guide.md)

