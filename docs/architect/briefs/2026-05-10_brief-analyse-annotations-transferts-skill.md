# Analyse annotations poc-scale-benchmark — opportunités de transfert skill → PromptGenerator

## Contexte

`docs/reports/poc-scale-benchmark/annotations.json` contient 222 entrées annotées grille v2 (3 axes Image/Prompt/Custom + flags + score 1-6). Toutes les images annotées ont été générées par le `PromptGenerator` (`src/services/prompt_generator.py`) **sans** application des règles capitalisées dans le skill `prompt-taxonomy-ecosystem`.

Le skill contient les **améliorations hors-circuit** accumulées par le canal manuel (utilisateur ↔ Claude.ai). L'objectif de cette analyse est de chercher **ce qu'on peut transférer du skill vers le PromptGenerator** pour réduire les défauts observés.

**Posture critique** :

- Le skill est **en avance** sur le PromptGenerator. Les défauts observés sont attendus.
- Tout défaut détecté est une opportunité de transfert (si couvert par skill) ou de capitalisation T19+ (si non couvert).
- **Pas de verdict OK/KO sur le PromptGenerator.** Pas de seuil. L'analyse est de l'inventaire de gap, pas de l'évaluation.

## Périmètre

**Lire (read-only)** :

- `.claude/skills/prompt-taxonomy-ecosystem.skill` (zip à dézipper en `/tmp/skill_extract/` ou équivalent) :
  - `SKILL.md` : vocabulaire défauts canoniques, taux de référence (baseline pré-skill), index T1-T18, règles `_RISKY_MULTI_PATTERNS`, `LEAF_OVERRIDES`, patterns à risque
  - `references/techniques.md` : détail T1-T18 — fix exact par défaut, exemples, contre-exemples
  - `references/taxonomy_full.md` + `taxonomy_summary.md` : pour résoudre les workflow_classes et leaves
- `docs/reports/poc-scale-benchmark/annotations.json` (annotations principales — 222 entrées grille v2)
- Optionnel selon scope élargi : autres annotations dans `docs/reports/poc-*/annotations.json` (8 dossiers POC secondaires, 438 entrées scorées) — utile si l'analyse veut comparer le PromptGenerator entre runs
- `docs/reports/poc-scale-benchmark/index-*.json` (38 fichiers d'index, mapping filename → leaf_id → workflow_class → confidence)
- `docs/reports/poc-scale-benchmark/rerun-2objets.json` (paires v1/v2 du fix `2_objets` — déjà transférée partiellement, voir si reste à transférer)
- `src/services/prompt_generator.py` (état actuel : NEGATIVE_V3, `_ISOLATION`, `LEAF_OVERRIDES`, `_RISKY_MULTI_PATTERNS` — connaître ce qui est déjà transféré)

**Ne pas modifier** : aucun fichier — analyse pure.

## Méthodologie

### Étape 1 — Inventaire des défauts observés

Pour chaque entrée d'annotation :

- Extraire les tags défauts présents (vocabulaire libre, pas seulement les 5 canoniques)
- Croiser avec leaf_id, workflow_class, score, publishable
- Agréger : `défaut → liste des leafs touchés → workflow_classes concernées → taux observé`

### Étape 2 — Croisement avec le skill

Pour chaque défaut observé (en commençant par les plus fréquents) :

- Recherche dans `SKILL.md` (vocabulaire canonique, patterns à risque, LEAF_OVERRIDES, _RISKY_MULTI_PATTERNS)
- Recherche dans `references/techniques.md` T1-T18 (défaut ciblé, fix proposé)
- **Pour chaque défaut, classer en 3 catégories** :
  - 🟢 **Couvert et déjà transféré** : règle skill présente AUSSI dans `prompt_generator.py` → vérifier que la règle est appliquée correctement, sinon transférer le patch
  - 🟡 **Couvert mais non transféré** : règle skill existe, n'est pas (ou partiellement) dans `prompt_generator.py` → opportunité de transfert
  - 🔴 **Non couvert par skill** : ni règle T-X ni mention SKILL.md → opportunité T19+ pour canal manuel

### Étape 3 — Préparation des transferts (catégorie 🟡)

Pour chaque opportunité 🟡, préparer un **prototype de patch** prêt pour brief Claude Code d'exécution :

- Quelle règle skill (citation textuelle T-X ou SKILL.md)
- Quelle modification dans `prompt_generator.py` (NEGATIVE_V3 étendu ? nouveau LEAF_OVERRIDE ? nouveau template ? `_RISKY_MULTI_PATTERNS` étendu ?)
- Quels leaf_ids ou workflow_classes concernés
- Estimation grossière du gain (% de défauts adressés)

### Étape 4 — Cas non couverts (catégorie 🔴)

Pour chaque opportunité 🔴, préparer un **prototype d'entrée T19+** prêt pour le canal manuel :

- Format skill (Hypothèse / Variable testée / Défaut ciblé / Échantillon / Critère de succès / Précédent)
- L'utilisateur le porte au canal manuel (Claude.ai) pour discussion et décision

## Sections obligatoires du rapport

### 1. Inventaire défauts

- Tableau : `défaut | n_observations | leaf_ids | workflow_classes | taux observé`
- Vocabulaire libre (pas filtré sur les 5 canoniques) — capter tout

### 2. Triage 3 catégories

- 🟢 Couvert et déjà transféré (vérifier l'application correcte) : liste défauts + état dans `prompt_generator.py`
- 🟡 Couvert mais non transféré : liste défauts + règle skill applicable + opportunité de transfert
- 🔴 Non couvert : liste défauts + caractéristiques + proto T19+

### 3. Plan de transferts (catégorie 🟡, priorisé)

- Top 5-10 transferts par impact (% de défauts adressés × volume)
- Pour chacun : règle skill (T-X ou SKILL.md), modification `prompt_generator.py` proposée, leafs/classes concernés
- **Prototype de brief Claude Code d'exécution** prêt à coller pour le top 3

### 4. Opportunités T19+ (catégorie 🔴, prêt canal manuel)

- Pour chaque, prototype au format skill (Hypothèse / Variable / Défaut / Échantillon / Critère / Précédent)
- L'utilisateur portera ces prototypes au canal manuel

### 5. Focus sur les 3 critères de sortie du cycle (factuel, sans verdict)

- A : taux `2_objets` v1 vs v2 sur les 13 paires (déjà partiellement transféré — voir si reste à faire)
- B : défauts dominants par méta-pattern (4 classes : Grille imagier, Imagier 3×3, Frise narrative, Multi-sujets via grille)
- C : défauts dominants par classe "OU" (12 classes au libellé contenant "OU")

## Reporting

Rapport obligatoire : `docs/reports/2026-05-10_analyse-annotations-transferts-skill.md`

Sections : Contexte / Résultats (1-5 ci-dessus) / Points d'attention (cas ambigus, données manquantes) / Décision (laisser vide — c'est l'architecte qui priorisera les transferts).

## Hors scope

- Aucune modification de fichier (skill, MEMORY, CLAUDE, prompt_generator, annotations)
- Pas de verdict qualité PromptGenerator
- Pas de seuil ad hoc
- Pas de génération d'images
