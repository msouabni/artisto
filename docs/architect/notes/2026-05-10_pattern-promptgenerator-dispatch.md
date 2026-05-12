# Pattern technique — `PromptGenerator`

Date : 2026-05-10
Type : note d'architecture (référence pour matrice de pilotage)
Source code : `src/services/prompt_generator.py`

## Synthèse

`PromptGenerator` n'est **pas un système IA**. C'est un **dispatcher déterministe sur un knowledge graph curé manuellement**. Aucun appel LLM à l'exécution, aucun RAG, aucun embedding, aucun apprentissage. Le résultat est reproductible bit à bit.

## Pattern central

**Strategy (GoF) + Registry + Data-driven design** (Felleisen)

| Couche | Pattern | Implémentation |
|---|---|---|
| Sélection de stratégie | **Dispatch table / Registry** | `TEMPLATE_DISPATCHER: dict[str, Callable]` — ~85 entrées, clé = `workflow_class` |
| Stratégie de production | **Decision table** | `taxonomy_production_cartography.json` — règles déclaratives par sous-catégorie |
| Génération du contenu | **Template Method (variant fonctionnel)** | 15 fonctions `template_*(leaf, strategy)` retournant une string |
| Connaissance du domaine | **Knowledge graph curated** | `coloring_taxonomy_full.json` (1376 leaves) + cartographie + SEO |
| Architecture globale | **Data-driven design** | Le type de la donnée d'entrée dicte la structure du code (cascade `leaf_id → root → sub → strategy → template_fn`) |

## Cascade d'exécution

```
build_prompt(leaf_id)
   │
   ▼
┌─ Lookup 1 : leaf_index[leaf_id] ──────────┐
│  → (root, sub, leaf)                      │
└──────────────────────────────────────────┘
   │
   ▼
┌─ Lookup 2 : strategy_index[sub.id] ───────┐
│  → production_strategy {class, resolution,│
│     technique, pipeline, confidence,      │
│     pitfalls, negative_extra?}            │
└──────────────────────────────────────────┘
   │
   ▼
┌─ Lookup 3 : TEMPLATE_DISPATCHER[class] ───┐
│  → template_fn (15 candidats)             │
└──────────────────────────────────────────┘
   │
   ▼
┌─ Court-circuit : LEAF_OVERRIDES[leaf_id]? ┐
│  → si présent : positive = override       │
│  → sinon : positive = template_fn(...)    │
└──────────────────────────────────────────┘
   │
   ▼
┌─ Composition : negative ─────────────────┐
│  → NEGATIVE_V3                            │
│  + strategy.negative_extra (si présent)   │
│  + renforcement multi-sujet               │
│    (si leaf_id ∈ _RISKY_MULTI_PATTERNS)   │
└──────────────────────────────────────────┘
   │
   ▼
return {positive, negative, resolution, workflow_class,
        technique, pipeline, confidence, pitfalls, seo, …}
```

Tout est en `O(1)` après l'indexation au boot. Pas de scan, pas d'inférence.

## Pourquoi ça marche ici (contraintes satisfaites)

1. **Corpus fini et fermé** — 1376 leaves, 145 sub-cats, 18 roots. Tient en mémoire.
2. **Domaine maîtrisé en amont** — l'expertise est précompilée dans `taxonomy_production_cartography.json` plutôt qu'inférée à l'exécution.
3. **Discriminateur stable** — `workflow_class` est une nomenclature humaine fermée (~85 valeurs), pas un texte libre.
4. **Sortie standardisée** — string + dict, pas de structure dynamique à découvrir.
5. **Évolution lente** — la taxonomie change sur cycles longs, le dispatcher peut être maintenu manuellement.

## Soupapes d'exception

Le pattern ferme la porte aux cas particuliers — il faut les laisser entrer par des soupapes nommées :

| Soupape | Rôle |
|---|---|
| `LEAF_OVERRIDES: dict[leaf_id, str]` | Court-circuit du template pour des feuilles à nom ambigu (`sheep_with_lamb`, `eid_al_adha_sheep`). 2 entrées aujourd'hui. |
| `_RISKY_MULTI_PATTERNS: tuple[str, ...]` | Patterns substring (`_with_friend`, `_and_`, …) → renforcement automatique du négatif. Évite d'avoir à over-rider tous les leaves correspondants. |
| `strategy.negative_extra` | Permet à la cartographie de pousser des termes négatifs sans toucher au code. |
| Fallback `template_solo_object` | `TEMPLATE_DISPATCHER.get(class) or template_solo_object` — pas de crash sur classe inconnue. |

## Inspiration / cousins

| Domaine | Implémentation cousine |
|---|---|
| Compilateurs (LLVM, GCC, Babel) | Visitor pattern + IR lowering |
| Web frameworks | Routing tables (Django URLconf, FastAPI router, Express) |
| Build systems | Bazel rules, Make pattern rules |
| Static site generators | Hugo / Jekyll : data + templates + dispatcher de layouts |
| ETL pipelines | `type → handler` map |
| Game dev | Entity Component Systems |
| Rules engines | Drools, IBM ODM (mais souvent dynamiques) |
| Agents LLM | Function calling : nom d'outil → handler |

C'est un pattern **canonique** et bien éprouvé. Ce qui est spécifique au projet : la **curation 100 % manuelle** du knowledge graph (cartographie + dispatcher). Acceptable au volume actuel ; à externaliser au-delà (plugins, DSL, codegen).

## Anti-pattern évité

**La "chaîne d'IA"** (LLM appelle un autre LLM qui appelle un RAG qui appelle un embedding). C'est tentant pour un POC, mais ça brise la reproductibilité, multiplie le coût à l'exécution, et déplace la dette technique des structures de données vers des hyperparamètres opaques.

Ici l'expertise a été **précompilée une fois** (dans `taxonomy_production_cartography.json`) au lieu d'être reconstruite à chaque appel.

## Évolutions futures envisageables (sans renier le pattern)

| Si | Évolution |
|---|---|
| 10 000+ leaves ou taxo dynamique éditée par plusieurs personnes | Externaliser la cartographie en DB + admin UI ; valider au boot |
| Workflow_classes à 200+ | Décorateurs `@register("class_name")` au lieu d'un dict en dur |
| Besoin de variantes par marché / langue | Surcouche de localisation **après** le dispatcher (post-processing du positif) |
| Sortie structurée multi-modèles | Adapter le dispatcher à `(class, model) → template_fn` |

À chaque évolution, le pattern de fond reste le même : **dispatcher déterministe sur knowledge graph + soupapes d'exception**.

## Coût opérationnel actuel

- **Boot** : ~3 lectures JSON + indexation O(N). Sub-seconde sur les volumes actuels.
- **`build_prompt`** : trois lookups O(1) + concaténations de strings. Microseconde.
- **Mémoire** : ~quelques MB (3 JSON + indexes).
- **Pas d'I/O réseau, pas de GPU, pas d'API externe**.

## Limites assumées

- **Pas de tests unitaires dédiés** — la couverture est implicite via les POC scale benchmarks (annotation humaine en aval).
- **2 sources de vérité** (taxonomie + cartographie) — un `sub_id` doit matcher dans les deux ; pas de contrainte structurelle, c'est un invariant qu'on maintient à la main.
- **`TEMPLATE_DISPATCHER` codé en dur** — ajouter une `workflow_class` = modifier le code Python (pas de hot-reload).
- **`LEAF_OVERRIDES` inline** — pas adapté au-delà de ~50 entrées.

Ces limites sont volontaires et cohérentes avec le statut "POC mature" — pas un système à industrialiser sans cycle dédié.
