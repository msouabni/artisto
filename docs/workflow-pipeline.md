# Workflow pipeline — Artiste Coloriage
> Document de référence · Maintenu par Claude Desktop  
> Dernière mise à jour : 2026-05-07

---

## Vue d'ensemble

Pipeline semi-autonome : taxonomie multilingue → concepts image → prompt line art → génération → QC technique automatique → **revue éditoriale humaine systématique** → contenu éditorial i18n → publication. L'admin valide chaque image via `benchmark-annotator.html` (raccourcis clavier, pré-chargement, mode batch côte à côte pour les concepts anatomy-sensitive). Le QC vision LLM auto est abandonné sur le défaut anatomy depuis le POC 2026-05-07.

```
Taxonomie (FR/EN/AR)
  → Sous-thèmes + enrichissement
  → Sujets image (concepts)
  → Prompt EN (planner → writer → validator)  ┐ parallèle
  → Contenu éditorial i18n (titre/desc/kw)    ┘
  → Génération image (ComfyUI, batch_size=3 pour concepts anatomy-sensitive)
  → QC technique automatique (Pillow histogram : color_ratio, ink_ratio, white_ratio)
  → Validation humaine éditoriale (benchmark-annotator) — QC vision auto anatomy abandonné
  → 4 variants (PNG master · WebP · thumb · PDF A4)
  → Publication (R2 + MD frontmatter × 3 locales + git PR)
```

---

## Étapes détaillées

### Phase 1 — Taxonomie

| Étape | Action | Endpoint / outil | Output |
|---|---|---|---|
| ① | Sélection d'un terme racine | Taxonomie existante | term (id, name_fr, name_en, name_ar) |
| ② | Génération sous-thèmes | `POST /api/ai/suggest-children` | Termes enfants avec name_fr/en/ar |
| ③ | Enrichissement métadonnées | `POST /api/ai/enrich-term` ou `enrich-terms-batch` | description_fr/en/ar, keywords |
| ④ | Génération sous-enfants | `POST /api/ai/suggest-children` (récursif) | Termes feuilles avec name_ar |

**Rôle de cette phase dans la suite :** les termes feuilles (④) fournissent l'**ancre AR** pour la génération de contenu éditorial en ⑥b. La qualité du `name_ar` des termes feuilles est donc critique pour tout le pipeline.

---

### Phase 2 — Concepts image

| Étape | Action | Endpoint / outil | Output |
|---|---|---|---|
| ⑤ | Génération sujets image | `POST /api/ai/generate-concepts` | Concepts : id, slug, name_en, name_fr, description_en/fr |

**Pattern imposé dans le prompt :** `name_en` DOIT suivre le format `<Subject> in <Setting>` (ex. "Lion in the Savanna", "Cat in a Library"). C'est l'ancre narrative pour le prompt image en aval.

---

### Phase 3 — Préparation du sujet (deux branches parallèles)

#### ⑥a — Prompt image EN

| Sous-étape | Modèle | Rôle |
|---|---|---|
| Planner | qwen3:8b | Extrait subject + setting + props (4-8 éléments typiques du décor) + composition + mood |
| Writer | qwen3:8b | Rédige le prompt positif EN en 4 paragraphes structurés (scène / props / style line art / cleanup) |
| Validator | qwen3:8b | Score 0-100 sur 5 checks : structure, line_art_constraints, technical_cleanup, keyword_coverage, kids_safe |

Endpoints : `POST /api/ai/create-prompt` (unitaire) · `POST /api/ai/create-prompts-bulk` (batch avec planner_batch).

#### ⑥b — Contenu éditorial i18n *(à construire en P2)*

Génération de title / title_card / description / keywords pour les 3 locales (EN · FR · AR).

**Approche validée (POC-4) : ancrage taxonomie + boucle validate-regen**

```
generate_concepts (name_en) → génération contenu EN
  → traduction FR (guidée par name_fr du concept)
  → génération AR : Prompt A ancré sur term.name_ar
      → validate (bornes + latin + ancre)
      → si échec : regen (max 3 retries)
      → si 2 échecs ancre : fallback Prompt B + review_flag
```

**Résultats POC-4 :** hallucinations majeures éliminées (أسد pour éléphant, دبكة pour dauphin → disparus). 1 seule erreur lexicale réelle sur 10 (حوت=baleine au lieu de دلفين=dauphin — trou lexical AR du modèle). Harakat : 10/10 propres.

**Blockers résolus par la boucle validate-regen :** bornes longueur (0/10 en génération directe), latin résiduel sur termes empruntés (Mandalas, Christmas).

**Bornes — distinction HARD caps Zod (plateforme) vs SOFT caps éditoriaux (pipeline)**

Confirmé par Alwan Books (réponse 2026-05-05, ADR §1.13) : **les hard caps Zod côté plateforme sont uniformes pour toutes les locales**. Le pipeline Python applique en plus des sweet spots éditoriaux internes plus stricts. Notre validate-regen loop rejette sur les SOFT caps, jamais sur les HARD caps.

| Champ | HARD cap Zod plateforme (toutes locales) | SOFT cap éditorial pipeline EN/FR | SOFT cap éditorial pipeline AR |
|---|---|---|---|
| `title` | [5, 100] | [40, 60] | [25, 55] |
| `title_card` | [5, 40] | (cible courte ≤ 30) | ≤ 25 |
| `description` | [20, 200] | [80, 130] | [40, 100] |

> ⚠ **Le validate-regen loop rejette sur les SOFT caps, pas les HARD caps.** Le build Astro côté Alwan Books ne cassera jamais sur nos longueurs AR — les SOFT caps sont notre propre gate qualité interne, distincte de la contrainte plateforme.

---

### Phase 4 — Génération image

| Étape | Action | Outil | Output |
|---|---|---|---|
| ⑦ | Génération line art | ComfyUI (workflow JSON + `.overrides.json`) | PNG master (fond blanc, contours noirs) |
| ⑧ | QC technique automatique | Pillow histogram (`build_technical_image_qc_v1`) : `color_ratio`, `white_ratio`, `ink_ratio`, contraste | Flags : `strong_color`, `noticeable_color`, `low_contrast`, `near_empty`, `overdrawn` |
| ⑨ | **Validation humaine éditoriale obligatoire** | `benchmark-annotator.html` (interface de revue) | Score 1-10 · `defects[]` · `publishable: true/null` · annotations structurées |
| ⑩ | Correction prompt | `POST /api/ai/improve-prompt` → retour en ⑦ | Prompt amélioré ou rejet |

**QC vision auto anatomy — abandonné (POC 2026-05-07).** Les modèles vision testés (`qwen3.5:9b` × 5 prompts, `gemma4:26b`) donnent **recall = 0/18** sur la détection du défaut `3_jambes` en line art, indépendamment de la formulation du prompt. La voie LLM vision est close pour la validation anatomy ; toute validation `publishable` passe désormais par l'humain. Le **QC technique Pillow** reste utile pour les défauts métriques (couleurs, encre, contraste) mais ne remplace pas le jugement éditorial.

**Stratégie retry — batch_size=3 + sélection humaine** (POC 2026-05-07) :

| Concept tier | batch_size | Justification |
|---|---:|---|
| Anatomy-sensitive (soccer, astronaut, dancer, danseur, sportifs en action) | **3** | Variance seeds élevée (POC seed-variance soccer = 30 % publishable seed-par-seed). Avec batch=3 + sélection humaine de la meilleure : taux attendu **~70 %** (POC batch-size : 7/10 seeds avec ≥1 image humainement publishable). |
| Concepts simples (hammer, flower, fish, train…) | 1 | Variance faible, défaut dominant `couleurs_résiduelles` bénin. Pas de gain à payer 3× le compute. |
| Color-prior subjects (refrigerator, dragon, fruit, drapeau…) | 1 + traitement upstream | POC color-to-lineart ou prompt filter `strip_color_nouns` (cf. CLAUDE.md). |

Le worker `image_generation` doit lire un tag `concept_tier` (à curer dans la taxonomie) pour décider le `batch_size`. Les 3 images du batch sont remontées simultanément à l'annotateur (mode côte à côte ; cf. Phase 5).

---

### Phase 5 — Revue éditoriale (validation humaine)

Le QC vision auto anatomy étant abandonné (cf. Phase 4), **toutes les images passent par une revue humaine éditoriale obligatoire** avant publication. Le seul QC automatique conservé en upstream est le QC technique Pillow (couleurs, encre, contraste) qui peut **flagger** une image mais jamais l'auto-approuver.

#### Interface de production : `benchmark-annotator.html`

`benchmark-annotator.html` (initialement développé pour les POCs samplers) devient l'**interface de validation éditoriale en production**. Exigences :

- **Raccourcis clavier obligatoires** :
  - `1` à `9` : score qualité (1 = inutilisable, 9 = excellent)
  - `Espace` : avancer à l'image suivante
  - `J` : toggle defect `3_jambes`
  - `O` : toggle defect `2_objets`
  - `G` : toggle defect `gris_résiduel`
  - `C` : toggle defect `couleurs_résiduelles`
  - `T` : toggle defect `traits_discontinus`
  - `P` : toggle `publishable`
- **Mode batch côte à côte** : pour les concepts `anatomy-sensitive` (cf. Phase 4 batch_size=3), afficher les 3 images **simultanément côte à côte**, avec sélection rapide (clic ou touche `1/2/3`) de la meilleure. Mode batch hors anatomy-sensitive : 1 image plein écran.
- **Pré-chargement de l'image suivante** dans le DOM pour latence visuelle nulle quand l'annotateur appuie sur `Espace`.
- **Intégration pipeline jobs** : les images à valider sont **pushées par le worker** (côté DB ou via WebSocket) plutôt que importées manuellement par dossier. Une queue `awaiting_validation` côté `image.status` alimente l'interface ; pas de drag-and-drop manuel en prod.
- **Persistance** : chaque annotation écrite dans la table `image_annotations` (cf. section R&D ci-dessous) au moment du `Espace`, pas en bulk en fin de session.

#### Cheminement de validation

| État image | Action annotateur | Transition |
|---|---|---|
| `awaiting_validation` (batch=1) | Score + defects + `publishable` | → `approved` ou `rejected` |
| `awaiting_validation` (batch=3, anatomy-sensitive) | Sélection de la meilleure des 3 + score + defects | → `approved` (best) + `rejected` (autres) |
| `rejected` | (optionnel) Annotation des defects pour la base R&D | → archivé |
| `approved` | (auto) | → Phase 6 publication |

**Pas de mécanisme exception-driven** : on ne revoit pas seulement les exceptions, on revoit **chaque** image. Le coût annotateur est budgété en payload : ~3-5 secondes/image au pacing optimisé (raccourcis clavier + pré-chargement) → ~12-20 minutes pour 200 images/jour.

---

### Phase 6 — Post-traitement & publication

| Étape | Action | Output |
|---|---|---|
| Variants | Conversion PNG master → WebP, WebP thumb, PDF A4 | 4 fichiers par image |
| Upload R2 | Upload atomique 4-ou-0 (rollback si partiel) | r2_slug stable (jamais modifié) |
| MD frontmatter | Génération fichier par locale (FR · EN · AR), slug différent par locale | 3 fichiers markdown |
| Git PR | Branche dédiée + PR auto-merge → rimalab-v2 | Post publié sur alwanbooks.com |

---

## Points d'attention identifiés

### 1. Gap AR dans `generate_concepts` ⚠
`generate_concepts` ne génère pas de `name_ar` pour les concepts image. L'ancre AR en ⑥b doit donc remonter au terme feuille (④) via `term.name_ar`. **Condition critique :** la taxonomie doit être assez granulaire — le terme feuille doit correspondre au sujet spécifique (ex. terme "lion" avec `name_ar: "أسد"`, pas seulement "wild animals" avec `name_ar: "حيوانات برية"`).

**Scénario de fallback si granularité insuffisante :** ajouter `name_ar` au schéma de sortie de `generate_concepts` (modifier le prompt + enrichir chaque concept via `enrich_term`). Coût : +1 appel LLM par concept.

### 2. `suggest_children` : incohérences cross-locale (finding POC-1)
`suggest_children` peut produire un `name_ar` formellement correct alors que `name_fr` ou `name_en` est faux (ex. "Égouts" pour un tracteur, nom féminin pour un mâle). La génération multilingue parallèle n'est pas fiable. **Confirme la stratégie EN-first + traduction guidée** pour tout le pipeline i18n, y compris pour l'extension de la taxonomie. La revue humaine via `awaiting_validation` est indispensable avant tout `apply`.

### 3. Pattern `<Subject> in <Setting>` non garanti en pratique
Le prompt `generate_concepts` impose ce pattern mais le validator ne le vérifie pas. Un concept mal formé (ex. "Cute Lion" sans setting) dégrade le planner en ⑥a (props mal ciblés) et le prompt image final.

**Recommandation :** ajouter une validation regex post-génération sur `name_en` pour détecter les titres sans setting, et les rejeter ou les corriger avant d'entrer dans ⑥a.

### 4. Choix LLM acté : qwen3:8b pour toutes les tâches texte (POC-LLM)
Benchmark comparatif effectué sur les deux modèles disponibles. **qwen3:8b retenu comme modèle par défaut.**

| Tâche | Modèle | Raison |
|---|---|---|
| Génération contenu AR (⑥b) | **qwen3:8b** | Bornes longueur 9/10 vs 0/10 — one-shot publishable |
| suggest_children / enrich_term | **qwen3:8b** | Cohérence cross-locale 25/25, 0 doublon |
| Chaîne prompt image EN (⑥a) | **qwen3:8b** | Déjà en place, confirmé |
| Tâches batch urgentes | qwen2.5:7b (fallback) | 7× plus rapide, acceptable avec validate-regen |

Config à jour : `OLLAMA_MODEL=qwen3:8b` dans `.env`, `defaults.model: qwen3:8b` dans les deux fichiers YAML de prompts.

**Caveat latence prod :** 12s × 3 locales × jusqu'à 3 retries = ~72s/image worst case. Acceptable avec workers parallèles — à valider sur batch de 50 images avant mise en prod.

### 5. QC vision auto anatomy — voie close (POC 2026-05-07)
Initialement, l'étape ⑧ devait s'appuyer sur un modèle de vision (LLaVA puis qwen3.5:9b multimodal). Les benchmarks de 2026-05-07 ont fermé cette voie pour le défaut anatomy le plus impactant (`3_jambes` sur soccer-style concepts) :

| Modèle vision | Prompts testés | Recall sur 18 images `3_jambes` | F1 max |
|---|---:|---:|---:|
| `qwen3.5:9b` | 5 (baseline, anatomy-aware, soccer-spécifique, binary, chain-of-thought) | 0/18 sur 4 prompts ; 1/18 sur 1 prompt | 0.095 |
| `gemma4:26b` | 1 (baseline, abandonné après confirmation pattern) | 0/18 | 0.000 |

**Conclusion :** les LLM vision testés ne voient pas ce défaut en line art, indépendamment de la formulation. Le QC anatomy passe désormais **exclusivement par la validation humaine** (cf. Phase 5). Le QC technique Pillow reste utile pour les défauts métriques (couleurs, contraste, encre) — il est conservé comme filtre upstream non-bloquant à l'étape ⑧.

**Pistes futures (hors scope court terme) :** détecteur heuristique squelettisation (OpenCV/Pillow) entraîné spécifiquement sur les figures anatomy soccer ; ou modèle vision spécialisé fine-tuné sur un corpus line art annoté. Aucune ne remplace la validation humaine à court terme — elles seraient un complément.

### 6. Bug regex harakat — à propager
La regex de détection des harakat `[ؐ-ًؚ-ٟ]` est sensible à la corruption RTL au copier-coller (le range peut inclure toutes les lettres arabes au lieu des seuls signes diacritiques). Utiliser des codepoints explicites : `[ؐ-ًؚ-ٟ]`. À vérifier dans `poc_ar_anchored_content.py` et à intégrer dès le départ dans le module AR de `src/`.

### 7. Bornes — HARD Zod plateforme vs SOFT éditoriales pipeline (clarifié 2026-05-05)
Confirmé par Alwan Books (réponse plateforme 2026-05-05, ADR §1.13) : les hard caps Zod côté plateforme sont **uniformes pour toutes les locales** (EN/FR/AR). Nos sweet spots éditoriaux internes sont distincts et plus stricts — densité lexicale AR ~50 % inférieure à EN/FR motive des cibles AR plus courtes.

| Champ | HARD cap Zod plateforme (toutes locales) | SOFT cap pipeline EN/FR | SOFT cap pipeline AR |
|---|---|---|---|
| `title` | [5, 100] | [40, 60] | [25, 55] |
| `title_card` | [5, 40] | (cible ≤ 30) | ≤ 25 |
| `description` | [20, 200] | [80, 130] | [40, 100] |

**Implication validation :**
- Le validate-regen loop Python (notre gate qualité) rejette sur les SOFT caps.
- Le build Astro plateforme casserait sur les HARD caps (jamais touché en pratique : nos SOFT caps sont strictement plus stricts).
- Cela veut dire qu'un contenu accepté par notre pipeline est **toujours** publiable côté plateforme — la marge est confortable.

Voir aussi le rapport `docs/reports/2026-05-05_analyse-bornes-validation.md` pour l'historique de la clarification.

### 10. Boucle correction ⑨ boucle sur ⑦, pas sur ⑥a
L'amélioration de prompt (`improve_prompt`) génère des variantes du prompt image sans repasser par le planner. Si l'échec QC est dû à un concept mal formé (sujet trop complexe, setting indessinable), la boucle ⑦→⑨→⑦ ne corrige pas la cause racine. Dans ce cas, il faut remonter à ⑤ (générer un nouveau concept).

### 8. r2_slug vs post_slug — stabilité post-publication
Le `r2_slug` est partagé entre les 3 locales et ne doit jamais être modifié après le premier upload. Le `post_slug` est par locale et peut différer. Toute logique qui confond les deux risque de casser les URLs publiées.

---

## Plan de validation POC

| POC | Étape(s) validée(s) | Question centrale | Bloquant pour |
|---|---|---|---|
| **POC-1** | ①②③④ | Les termes feuilles ont-ils des `name_ar` valides et assez granulaires ? | POC-4 |
| **POC-2** | ⑤ | `generate_concepts` produit-il des concepts fidèles au thème, pattern Subject+Setting respecté ? | POC-3, POC-4 |
| **POC-3** | ⑥a | La chaîne planner→writer→validator valide >80% au premier essai ? Latence budgétable ? | Architecture P2 |
| **POC-4** | ⑥b | L'ancrage `term.name_ar` ramène les erreurs sémantiques AR sous 5% ? | Architecture P2 |
| **POC-5** | ⑧ | ~~LLaVA détecte correctement les images dégradées~~ — **POC fermé 2026-05-07** : LLM vision (qwen3.5:9b, gemma4:26b) recall=0 sur `3_jambes`. Validation anatomy via humain obligatoire. | Architecture P3 (humain) |

**Séquence :**
```
POC-1 ──→ POC-4 (si taxonomie AR OK)
  └──→ POC-2 ──→ POC-3 (parallèle avec POC-2)
POC-5 (indépendant, nécessite un corpus d'images)
```

**Condition de sortie :** tout POC avec >20% d'erreur sur sa métrique principale déclenche un arbitrage avant de continuer.

---

## Base de connaissance R&D — annotations structurées

Chaque annotation humaine produite par `benchmark-annotator.html` (Phase 5) est un **datum R&D** persisté de manière structurée. Les annotations alimentent une table PostgreSQL `image_annotations` (à créer en P3) qui sert à :

1. **Calculer le taux de succès par concept × paramètres** (sampler, steps, cfg, scheduler, seed) — tableau croisé dynamique pour identifier les combinaisons gagnantes/perdantes empiriquement.
2. **Identifier les seeds favorables par concept** — repérer les seeds qui produisent systématiquement des `publishable=true` et alimenter une éventuelle allowlist concept-spécifique.
3. **Calibrer les seuils de retry automatique** — déterminer combien de variantes batch sont nécessaires par concept tier pour atteindre N % publishable. Aujourd'hui empirique (batch=3 = 70 %), à raffiner par concept.
4. **Mesurer la dérive qualité dans le temps** — détecter quand un changement (mise à jour du modèle Ollama, version ComfyUI, retrain d'ERNIE) dégrade un concept jusqu'ici stable.

### Schéma table `image_annotations`

| Colonne | Type | Description |
|---|---|---|
| `id` | uuid PK | identifiant |
| `image_id` | text FK → image.id | image annotée |
| `image_path` | text | chemin fichier (utile pour audit hors DB) |
| `concept` | text | concept de la taxonomie (ex. `soccer`, `dragon`, `hammer`) |
| `concept_tier` | text | `simple_inanime` / `simple_anime` / `complexe_anime` / `anatomy_sensitive` / `color_prior` / `scene_interieure` |
| `sampler` | text | `euler` / `dpmpp_2m_sde` / … |
| `steps` | int | 8 / 12 / 20 / … |
| `cfg` | numeric(3,1) | 1.0 / 1.5 / 2.0 / 3.0 |
| `scheduler` | text | `normal` / `karras` |
| `seed` | bigint | seed exact passé au KSampler |
| `width`, `height` | int | dimensions de génération |
| `score` | int (1-9) | score qualité éditorial |
| `defects` | text[] | `3_jambes`, `2_objets`, `gris_résiduel`, `couleurs_résiduelles`, `traits_discontinus`, `perspective_KO`, … |
| `publishable` | boolean | true / null (null = rejected ou pas encore décidé) |
| `notes` | text | texte libre annotateur |
| `annotator_id` | text | identifiant humain (pour mesurer la cohérence inter-annotateurs) |
| `annotated_at` | timestamptz | horodatage |
| `batch_position` | int nullable | 1/2/3 si annotation issue d'un batch_size=3, NULL sinon |
| `batch_selected` | boolean nullable | true si cette image est la "best" du batch |

### Reporting attendu

- **Dashboard concept** : `% publishable` × `(sampler, steps, cfg)` sur N derniers jours, par concept.
- **Suivi seeds** : top-K seeds publishable par concept (à valider statistiquement avant d'en faire une allowlist : un seed gagnant sur 3 essais ≠ gagnant universel).
- **Alerte dérive** : si `publishable_rate(concept_tier=anatomy_sensitive)` chute de >10 pts sur 7 jours glissants, notifier l'équipe.
- **Export R&D** : extraction CSV par concept × paramètres pour étudier l'effet d'un nouveau négatif ou d'un nouveau prompt writer en A/B (ex. POC `prompt-filter`).

Tant que la table n'est pas créée, les annotations vivent dans `docs/reports/<poc-dir>/annotations.json` (format actuel : `{filename: {score, defects, publishable, notes, updated_at}}`). La migration vers Postgres consiste à parser ces JSONs comme historique initial et à brancher `benchmark-annotator.html` sur l'API `image_annotations`.

---

## Décisions architecturales actées

| Sujet | Décision |
|---|---|
| Génération AR | Taxonomie-ancrée (term.name_ar) — génération directe FR→AR et EN→AR éliminée |
| Translittération AR | Mishkal + ar_to_slug custom DIN 31635 — 30/30 sur corpus |
| Validation contenu | Règles Python (port Zod) + review_flags JSON (pas de score flou) |
| QC vision anatomy | **Validation humaine requise** (LLM vision recall=0 sur soccer 3_jambes, POC 2026-05-07) |
| QC technique image | Pillow histogram non-bloquant (color/ink/white/contrast) — flagger seulement |
| Stratégie retry concepts anatomy-sensitive | `batch_size=3` côté ComfyUI + sélection humaine via `benchmark-annotator` mode côte à côte |
| UX admin | **Validation humaine systématique** via `benchmark-annotator.html` (raccourcis clavier + pré-chargement) |
| Annotations R&D | Persister chaque annotation en table `image_annotations` pour calibration empirique des paramètres |
| Génération i18n | EN-first → FR → AR |
| Upload R2 | Atomique 4-ou-0, rollback via job dédié |
| Git publication | Branche dédiée + PR auto-merge (pas push direct main) |

---

## Références

- `CLAUDE.md` — conventions techniques, architecture, pièges
- `docs/brief-claude-desktop.md` — plan production, phases, décisions
- `docs/poc-plan.md` — plan de validation POC, statuts, prompts Claude Code, verdicts
- `docs/xchange/PIPELINE-CONTRACT.md` — contrat Alwan Books v2.4 (source de vérité format)
- `docs/reports/` — tous les rapports POC et analyses datés
