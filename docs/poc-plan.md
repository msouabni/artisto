# Plan POC & Tests — Validation pipeline
> Document de suivi · Maintenu par Claude Desktop  
> Dernière mise à jour : 2026-05-05

---

## Objectif

Valider chaque étape du pipeline existant avant d'engager les phases P1-P4 (schéma DB, génération i18n, publication). Chaque POC répond à une question précise, produit un verdict, et conditionne ou non la suite.

**Règle de sortie :** tout POC avec >20% d'erreur sur sa métrique principale déclenche un arbitrage avant de continuer.

---

## Tableau de bord

| POC | Étape pipeline | Statut | Verdict | Rapport |
|---|---|---|---|---|
| POC-1 | ①②③④ Taxonomie AR | ✅ Terminé | Couverture 100% — conditionnel audit qualité AR | `2026-05-05_poc-taxonomy-ar-coverage.md` |
| POC-2 | ⑤ Concepts image | ⏳ Après POC-1 | — | — |
| POC-3 | ⑥a Prompt EN | ⏳ Après POC-2 | — | — |
| POC-4 | ⑥b Contenu AR ancré | ✅ Terminé | Approche validée — boucle validate-regen requise | `2026-05-05_poc-ar-anchored-content.md` |
| POC-LLM | Choix modèle | ✅ Terminé | qwen3:8b retenu — bornes AR 9/10 vs 0/10 | `2026-05-05_poc-llm-benchmark.md` |
| POC-5 | ⑧ QC LLaVA | ⏳ Bloqué | ⚠ Aucun LLaVA sur instance Ollama | — |

**Légende statuts :** ⏳ En attente · 🔄 En cours · ✅ Validé · ❌ Éliminé · ⚠ Partiel (arbitrage requis)

---

## POC-1 — Couverture AR taxonomie + qualité `suggest_children`

**Statut :** 🔄 En cours  
**Question :** les termes feuilles ont-ils des `name_ar` valides et assez granulaires pour servir d'ancre en ⑥b ?  
**Bloquant pour :** POC-4 (sans AR fiables en taxonomie, pas d'ancrage possible)

### Métriques cibles

| Métrique | Cible | Bloquant si |
|---|---|---|
| % termes feuilles avec `name_ar` valide | >80% | <50% → enrichissement batch avant POC-4 |
| % `name_ar` assez spécifiques (≤4 mots, nom du sujet direct) | >70% | <50% → fallback : ajouter `name_ar` à `generate_concepts` |
| `suggest_children` : name_ar présent et non vide | >90% | <70% → corriger le prompt |
| `suggest_children` : doublons avec termes existants | <10% | — |

### Scénarios de décision

- **Taxonomie AR OK (>80% feuilles valides + spécifiques)** → POC-4 lancé tel quel
- **Taxonomie AR partielle (50-80%)** → lancer `enrich-terms-batch` sur les termes sans AR avant POC-4
- **Taxonomie AR insuffisante (<50%)** → ajouter `name_ar` au schéma de `generate_concepts` (modifier le prompt + enrichir post-génération)

### Résultats

| Vocabulaire | Nb termes | Avec name_ar | Feuilles | Feuilles AR valides |
|---|---|---|---|---|
| `themes` | 88 | 88 (100%) | 74 | 74 (100%) ✅ |

**Métriques suggest_children (10 suggestions sur 2 termes parents) :**

| Critère | Score |
|---|---|
| name_ar présent et non vide | 10/10 ✅ |
| name_ar longueur 1-4 mots | 10/10 ✅ |
| Doublons avec existants | 0/10 ✅ |
| Cohérence cross-locale FR/EN | **8/10** ⚠ (2 incohérences FR/EN détectées) |

**Incohérences cross-locale détectées :**
- `animaux_domestiques_cows_heifer` → name_fr = "Taureau" (faux, heifer = génisse ♀), name_ar = "البقرات" (vaches pluriel, approximatif)
- `animaux_domestiques_cows_tractor` → name_fr = "Égouts" (complètement faux), name_ar = "الجرارات الزراعية" (tracteurs agricoles — correct !)

→ Le AR peut être correct alors que FR ou EN est faux. **Confirme la stratégie EN-first + traduction guidée** (pas génération parallèle multilingue).

**Points d'attention qualité AR seed :**
- Volume modeste : 88 termes, un seul vocabulaire (`themes`), dominé par races de chiens + Aïd
- Quelques entrées AR suspectes : "بوديل" (poodle), "بولي" (bulldog) — translittérations phonétiques à valider humainement avant usage comme ancres few-shot
- 2 jobs `awaiting_validation` créés pendant le POC (non appliqués) → **à rejeter manuellement** : `job_ai_1777970742496806600_6935`, `job_ai_1777970783948490500_3374`

**Verdict :** ✅ Taxonomie prête pour POC-4 côté couverture (100%). Conditionnel à un **audit manuel rapide (~30 min)** des 10 entrées AR candidates avant de les utiliser comme ancres.  
**Question ouverte :** enrichir la taxonomie avant POC-4 (diversifier au-delà de chiens + Aïd) ou travailler avec l'existant ?  
**Rapport complet :** `docs/reports/2026-05-05_poc-taxonomy-ar-coverage.md`

---

## POC-2 — Qualité génération concepts image (`generate_concepts`)

**Statut :** ⏳ En attente de POC-1  
**Question :** les concepts générés sont-ils fidèles au thème, spécifiques, et respectent-ils le pattern `<Subject> in <Setting>` ?  
**Bloquant pour :** POC-3 (input de la chaîne prompt), POC-4 (input du contenu éditorial)

### Métriques cibles

| Métrique | Cible |
|---|---|
| Fidélité thème (concept ∈ catégorie du terme) | >95% |
| Pattern Subject+Setting respecté dans `name_en` | >85% |
| Quasi-doublons dans une même génération | <10% |
| Sujets trop génériques ou trop complexes pour line art | <15% |

### Prompt Claude Code
*(à copier-coller quand POC-1 est terminé)*

```
Lis CLAUDE.md et docs/brief-claude-desktop.md avant de commencer.

Objectif : POC-2 — Qualité génération concepts image.

Écris un script `scripts/poc_concept_generation.py` qui :
1. Choisit 3 termes feuilles de catégories différentes (animal, objet, scène) parmi les résultats du POC-1
2. Pour chacun, appelle `POST /api/ai/generate-concepts` avec count=10
3. Évalue chaque concept :
   - Fidélité thème : le concept correspond-il bien à la catégorie du terme parent ?
   - Pattern Subject+Setting : `name_en` contient-il un sujet ET un décor explicite ?
     (regex indicative : présence de " in ", " on ", " at ", " under ", " near ", " with ")
   - Quasi-doublons : similarité textuelle >80% entre deux concepts du même lot
   - Feasibility line art : le sujet est-il trop abstrait ou trop complexe ? (heuristique : longueur >8 mots = suspect)
4. Exporte `docs/reports/2026-05-05_poc-concept-generation.json` (ensure_ascii=False)

Rapport `docs/reports/2026-05-05_poc-concept-generation.md` :
- Tableau des résultats par terme (10 concepts × 3 termes)
- Métriques globales
- Exemples de concepts bien formés vs mal formés
- Décision / Action suivante : faut-il ajouter une validation post-génération sur name_en ?

Convention reporting : .md + .json avant fin de réponse.
```

### Résultats

| Métrique | Baseline (sans ancrage) | Prompt A (ancré) | Prompt B (ancre forcée) |
|---|---|---|---|
| Erreurs sémantiques majeures | 30-40% ❌ | **1/10** ✅ (حوت≠دلفين) | 0/10 ✅ |
| Anchor présente dans title | ~60% | 7/10 | 10/10 |
| title dans bornes AR [30-50c] | 0% | 0/10 ❌ | 0/10 ❌ |
| description dans bornes [55-90c] | 0% | 0/10 ❌ | 0/10 ❌ |
| Harakat absents | 7/10 | **10/10** ✅ | **10/10** ✅ |
| Latin absents | 9/10 | 8/10 | 6/10 ⚠ |
| Latence moyenne | 5.1s | 6.0s | 4.2s |

**Analyse clé :** les 3 "anchor missing" du Prompt A ne sont que 1 vraie erreur lexicale (حوت=baleine ≠ دلفين=dauphin). Les 2 autres cas : le modèle choisit un terme **plus spécifique** que l'ancre catégorielle (بقرة=vache vs حيوانات المزرعة=animaux de la ferme) — comportement correct, pas une erreur.

**Blockers restants :** bornes longueur violées 0/10 (titre 10-25c produit vs cible 30-50c) + latin résiduel sur termes empruntés (Christmas/Mandalas).

**Verdict :** ✅ Approche validée — hallucinations majeures éliminées, harakat propres. Architecture P2 : **Prompt A + boucle validate-regen (3 retries max)** + bornes AR recalibrées + Prompt B comme fallback si 2 échecs consécutifs.

**Décisions actées :**
- Bornes AR à élargir : title [25-55c], description [40-100c] (densité lexicale AR ~50% inférieure à EN/FR)
- Latin résiduel sur termes empruntés → post-processing ou regen (pas un problème de modèle)
- Cas dauphin (حوت≠دلفين) → trou lexical AR : futur dictionnaire de termes spécifiques (lien avec Mishkal/ar_to_slug)
- Budget regen : 3 retries × ~6s = ~18s overhead acceptable pour production batch

**Rapport complet :** `docs/reports/2026-05-05_poc-ar-anchored-content.md`

---

## POC-3 — Chaîne prompt image EN (planner → writer → validator)

**Statut :** ⏳ En attente de POC-2  
**Question :** la chaîne qwen3:8b × 3 étapes valide-t-elle >80% des prompts au premier essai ? La latence est-elle budgétable en prod ?  
**Bloquant pour :** architecture P2 (dimensionnement du batch, timeouts)

### Prérequis à vérifier avant lancement
- [ ] qwen3:8b disponible sur l'instance Ollama distante
- [ ] Latence de base qwen3:8b mesurée (vs qwen2.5:7b)

### Métriques cibles

| Métrique | Cible |
|---|---|
| Taux validation premier essai (score validator ≥ 80) | >80% |
| Latence p50 (3 étapes cumulées) | <60s |
| Latence p95 | <120s |
| Check `line_art_constraints` : taux pass | >90% |
| Check `kids_safe` : taux pass | 100% |

### Prompt Claude Code
*(à copier-coller quand POC-2 est terminé)*

```
Lis CLAUDE.md et docs/brief-claude-desktop.md avant de commencer.

Objectif : POC-3 — Qualité chaîne prompt image EN.

Prérequis : vérifier que qwen3:8b est disponible sur Ollama (GET /api/tags ou équivalent).
Si non disponible, signaler dans le rapport et utiliser qwen2.5:7b comme fallback.

Écris un script `scripts/poc_prompt_chain.py` qui :
1. Prend 10 concepts valides issus du POC-2 (ou 10 concepts manuels si POC-2 non disponible)
2. Pour chacun, exécute la chaîne complète via `POST /api/ai/create-prompt`
   (ou appelle planner / writer / validator séquentiellement si create-prompt n'est pas disponible)
3. Mesure pour chaque concept :
   - Latence totale (planner + writer + validator)
   - Score validator (0-100)
   - Résultat par check (structure / line_art_constraints / technical_cleanup / keyword_coverage / kids_safe)
   - Recommendations du validator (patterns récurrents)
4. Calcule p50 / p95 latence, taux de validation (score ≥ 80), distribution par check
5. Exporte `docs/reports/2026-05-05_poc-prompt-chain.json` (ensure_ascii=False)

Rapport `docs/reports/2026-05-05_poc-prompt-chain.md` :
- Modèle utilisé (qwen3:8b ou fallback) + disponibilité confirmée
- Métriques globales (taux validation, latences)
- Distribution scores validator (histogramme textuel)
- Patterns de recommendations récurrentes (faiblesses du writer)
- Décision / Action suivante : la chaîne est-elle prête pour la prod ? Timeouts à ajuster ?

Convention reporting : .md + .json avant fin de réponse.
```

### Résultats
*(à compléter après exécution)*

**Verdict :** —

---

## POC-4 — Génération contenu éditorial AR ancré taxonomie

**Statut :** ⏳ En attente de POC-1  
**Question :** fournir `term.name_ar` comme ancre explicite ramène-t-il les erreurs sémantiques AR sous 5% ?  
**Bloquant pour :** toute l'architecture P2 (génération i18n)

### Contexte
Les approches directes ont été éliminées :
- FR→AR : 0/10 bornes Zod, erreurs sémantiques majeures (éliminé en session 1)
- EN→AR prompt A : 3/10 erreurs sémantiques, 6/10 caractères latins (éliminé)
- EN→AR prompt B : 4/10 erreurs sémantiques, hallucination phonétique ("دبكة" pour dauphin) (éliminé)

L'approche taxonomie-ancrée est le pivot : le `term.name_ar` du terme feuille parent est injecté comme ancre explicite dans le prompt.

### Métriques cibles

| Métrique | Cible | Rappel baseline (sans ancrage) |
|---|---|---|
| Erreurs sémantiques (animal/sujet substitué) | <5% | 30-40% |
| `title` ∈ bornes AR cibles [30-50 chars] | >80% | 0% (trop long) |
| `title_card` ≤ 25 chars | >90% | 100% (OK baseline) |
| `description` ∈ [55-90 chars] | >70% | 0% (trop court) |
| Harakat indésirables | 0% | 10% |
| Caractères latins | <5% | 10-60% |

### Prompt Claude Code
*(à copier-coller quand POC-1 est terminé)*

```
Lis CLAUDE.md, docs/brief-claude-desktop.md et docs/reports/2026-05-05_poc-taxonomy-ar-coverage.md avant de commencer.

Objectif : POC-4 — Génération contenu éditorial AR ancré sur term.name_ar.

Contexte : les approches de génération directe AR ont été éliminées (30-40% erreurs sémantiques).
L'approche taxonomie-ancrée injecte le label AR validé du terme feuille parent comme ancre explicite.

Écris un script `scripts/poc_ar_anchored_content.py` qui :

1. Sélectionne 10 paires (concept_name_en, term_name_ar, term_name_en) depuis la taxonomie réelle
   - Choisir des termes feuilles avec name_ar valide (résultats POC-1)
   - Varier les catégories (animaux, objets, scènes, véhicules…)
   - Pour chaque terme, prendre un concept du style "X in Y" représentatif

2. Pour chaque paire, appelle qwen2.5:7b (Ollama) avec ce prompt template :
   ---
   Le sujet de l'image est : "{concept_name_en}".
   Le thème principal en arabe est : {term_name_ar} ({term_name_en}).
   Génère le contenu éditorial en arabe standard (fusha/MSA) pour cette page de coloriage.
   Règles strictes :
   - Pas de harakat (signes diacritiques)
   - Pas de caractères latins
   - Arabe standard uniquement, pas de dialecte
   Retourne UNIQUEMENT un JSON valide avec ces champs :
   {{"title": "...", "title_card": "...", "description": "...", "keywords": ["...", "..."]}}
   Contraintes de longueur :
   - title : 30 à 50 caractères
   - title_card : 25 caractères maximum
   - description : 55 à 90 caractères
   - keywords : 5 mots-clés
   ---

3. Pour chaque output, vérifie :
   - JSON parsable
   - Présence du mot AR du thème (term_name_ar ou dérivé) dans title ou description
   - Longueurs dans les bornes
   - Absence de harakat (regex : [ؐ-ًؚ-ٟ])
   - Absence de caractères latins (regex : [a-zA-Z])

4. Exporte `docs/reports/2026-05-05_poc-ar-anchored-content.json` (ensure_ascii=False)

Rapport `docs/reports/2026-05-05_poc-ar-anchored-content.md` :
- Tableau résultats (10 lignes : concept / term_ar / erreur sémantique ? / bornes / harakat / latin)
- Métriques globales vs baseline (tableau comparatif)
- Analyse des cas d'erreur résiduels
- Si taux erreur >10% : proposer variante B (forcer term_name_ar en début de titre)
- Décision / Action suivante : approche validée pour P2 ?

Convention reporting : .md + .json avant fin de réponse.
```

### Variante B (si POC-4 taux erreur >10%)
Forcer `term_name_ar` en début du champ `title` pour ancrer dès le premier token :
> *"Le titre doit commencer par : {term_name_ar}"*

### Résultats
*(à compléter après exécution)*

**Verdict :** —

---

## POC-5 — QC vision LLaVA

**Statut :** ⏳ Indépendant (nécessite un corpus d'images)  
**Question :** LLaVA détecte-t-il correctement les images dégradées ? Quel est le taux de faux négatifs (mauvaise image publiée) ?  
**Bloquant pour :** architecture P3 (dimensionnement du QC, seuils de rejet)

### Prérequis
- [ ] Corpus de 10 images : 5 bonnes (line art propre) + 5 mauvaises (≥3 types de défauts distincts)
- Si peu d'images mauvaises disponibles : générer intentionnellement (prompt dégradé ou paramètres ComfyUI cassés)

### Métriques cibles

| Métrique | Cible | Priorité |
|---|---|---|
| Rappel (mauvaises images détectées) | >90% | Critique (faux négatif = mauvaise image publiée) |
| Précision (bonnes images acceptées) | >80% | Important (faux positif = travail humain superflu) |
| Latence par image | <30s | Budgétable en prod |

### Prompt Claude Code
*(à copier-coller quand le corpus d'images est disponible)*

```
Lis CLAUDE.md et docs/brief-claude-desktop.md avant de commencer.

Objectif : POC-5 — Évaluation du QC vision LLaVA.

Prérequis : disposer d'un corpus de 10 images (5 bonnes / 5 mauvaises).
Si le corpus n'existe pas encore, générer 5 images mauvaises intentionnellement
(ex. : modifier les paramètres ComfyUI pour produire des images bruitées, avec couleurs, ou floues).

Écris un script `scripts/poc_qc_lava.py` qui :
1. Charge les 10 images du corpus (chemin à adapter)
2. Pour chaque image, appelle le QC LLaVA existant (même code que le worker en prod)
3. Compare le verdict LLaVA avec le label ground truth (bonne / mauvaise)
4. Calcule : précision, rappel, F1, latence p50/p95
5. Identifie les faux positifs et faux négatifs avec leur motif
6. Exporte `docs/reports/2026-05-05_poc-qc-lava.json`

Rapport `docs/reports/2026-05-05_poc-qc-lava.md` :
- Description du corpus (5+5, types de défauts)
- Matrice de confusion
- Métriques (précision / rappel / F1 / latence)
- Analyse des erreurs (quels types de défauts LLaVA rate-t-il ?)
- Décision / Action suivante : seuils à ajuster ? QC suffisant pour la prod ?

Convention reporting : .md + .json avant fin de réponse.
```

### Résultats
*(à compléter après exécution)*

**Verdict :** —

---

## POCs antérieurs (sessions précédentes)

| POC | Date | Verdict | Rapport |
|---|---|---|---|
| AR translittération (Mishkal) | 2026-05-05 | ✅ 30/30 — Mishkal + ar_to_slug DIN 31635 | `2026-05-05_poc-ar-transliteration.md` |
| AR vocalisation Ollama | 2026-05-05 | ❌ Éliminé — erreurs lexicales, latence 1.8-121s | `2026-05-05_poc-ar-vocalisation-ollama.md` |
| Génération contenu AR directe (FR→AR) | 2026-05-05 | ❌ Éliminé — 0/10 bornes Zod, erreurs sémantiques majeures | `2026-05-05_poc-ar-content-quality.md` |
| Génération contenu AR (EN→AR, prompt A vs B) | 2026-05-05 | ❌ Éliminé — 30-40% erreurs sémantiques, "دبكة" pour dauphin | `2026-05-05_poc-ar-content-prompts-v2.md` |

---

## Décisions prises suite aux POCs

| Décision | Source | Statut |
|---|---|---|
| Génération AR directe (FR→AR, EN→AR) éliminée | POC AR content quality + prompts v2 | ✅ Acté |
| Translittération AR : Mishkal + ar_to_slug custom | POC AR translittération | ✅ Acté — scripts prêts dans `scripts/` |
| Approche i18n : EN-first → FR → AR ancré term_ar | Analyse session + POCs AR | ✅ Acté — à valider par POC-4 |
| Bornes AR à recalibrer (≠ bornes EN/FR) | POC AR content prompts v2 | ✅ Acté — cibles dans POC-4 |
| Validation : review_flags JSON (pas score flou) | Analyse architecture | ✅ Acté |
| Intégration Mishkal dans src/ | POC translittération | ⏳ En attente green light |
| Validation GPL-3.0 Mishkal (usage interne) | POC translittération | ⏳ À confirmer |
| Architecture P2 AR : Prompt A + validate-regen (3 retries) + Prompt B fallback | POC-4 | ✅ Acté |
| Bornes Zod AR recalibrées : title [25-55c], description [40-100c] | POC-4 | ✅ Acté (à confirmer contrat Alwan) |
| Dictionnaire AR termes spécifiques (animaux rares) | POC-4 (trou حوت≠دلفين) | ⏳ Workstream futur |
| Expansion taxonomie : 88 → 500+ termes feuilles | Stratégie production massive | ⏳ Sprint à planifier |
| **OLLAMA_MODEL → qwen3:8b** dans .env + taxonomy_prompts.yaml + image_prompts.yaml | POC-LLM | ⏳ À appliquer |
| CLAUDE.md : documenter qwen3:8b défaut, qwen2.5:7b fallback latence | POC-LLM | ⏳ À appliquer |
| Provisionner LLaVA (ou qwen3.5:9b multimodal) sur Ollama avant Phase 3 | POC-LLM | ⚠ Bloquant P3 |
| Propager fix regex harakat (codepoints explicites) dans poc_ar_anchored_content.py et futur module AR src/ | POC-LLM (bug) | ⏳ À corriger |
| Valider latence cumulée sur batch 50 images (i18n × 3 locales × retries) avant prod | POC-LLM | ⏳ Avant mise en prod |
