# Analyse — Plan de validation POC pipeline existant
Date : 2026-05-05

## Contexte

Le pipeline est fonctionnel (images produites). Avant d'engager les phases P1-P4 (schéma DB, contenu i18n, publication), on valide la qualité de chaque étape existante sur un échantillon réel. L'objectif : identifier les points faibles réels, pas supposés, et affiner les décisions d'architecture P1-P4 en conséquence.

Workflow cible rappel (11 étapes user) :
```
[1] Terme racine taxonomie
→ [2] suggest_children : sous-thèmes (avec name_ar dans le prompt)
→ [3] enrich_term / batch : métadonnées
→ [4] suggest_children récursif : sous-enfants
→ [5] generate_concepts : sujets image (⚠ pas de name_ar dans le schéma)
→ [6a] prompt_planner + prompt_writer + validate_prompt : prompt image EN
→ [6b] NEW : génération contenu éditorial i18n (title/description/keywords × 3 locales)
→ [7] ComfyUI : génération image
→ [8] LLaVA : QC vision (line art propre ?)
→ [9] Correction/itération
→ [10] Validation (humaine ou auto)
→ [11] Publication
```

## Découverte critique (lecture code)

**`generate_concepts` n'a pas de champ `name_ar`** (schéma : id, slug, name_en, name_fr, description_en, description_fr, weight — uniquement).

Conséquence directe pour l'approche "taxonomie-ancrée" validée en session précédente : l'ancre AR ne peut pas venir du concept lui-même. Elle doit venir du **terme taxonomique parent** (`term.name_ar`). Cela impose une condition : la taxonomie doit être **assez granulaire** pour que le terme parent d'un concept "Lion in the Savanna" soit "lion" (name_ar: "أسد") et non "wild animals" (name_ar: "حيوانات برية" — trop générique pour ancrer la génération).

**C'est exactement ce que POC-1 doit valider en premier.**

## Résultats — Plan de 5 POCs

### POC-1 : Granularité taxonomie + qualité labels AR (étapes 2-4)

**Question** : la taxonomie est-elle assez granulaire pour servir d'ancre AR fiable ? Les termes ont-ils des labels AR valides et spécifiques ?

**Protocole** :
- Lire la taxonomie existante sur 2-3 vocabulaires (animaux, véhicules, nature)
- Pour chaque terme feuille : vérifier la présence et la qualité du `name_ar`
- Générer 5 sous-thèmes depuis un terme racine (`suggest_children`) et évaluer : name_ar généré, diversité, doublons avec termes existants

**Métriques** :
- % termes feuilles avec `name_ar` renseigné et non vide
- % termes feuilles où `name_ar` est spécifique (ex. "أسد" vs "حيوانات") et suffisant comme ancre
- Qualité génération suggest_children : doublons, hors-sujet coloriage, AR présent et correct

**Verdict attendu** :
- Si >80% termes feuilles ont un AR valide ET granulaire → approche taxonomie-ancrée viable telle quelle
- Si <50% → il faudra soit enrichir la taxonomie (enrich_term batch), soit adapter l'ancrage au niveau concept (exige d'ajouter name_ar à generate_concepts)

**Livrable** : `2026-05-05_poc-taxonomy-ar-coverage.md` + `.json`

---

### POC-2 : Qualité génération concepts image (étape 5)

**Question** : `generate_concepts` produit-il des sujets variés, spécifiques, publiables et fidèles au thème ?

**Protocole** :
- 3 termes feuilles de catégories différentes (animal, objet, scène)
- Générer N=10 concepts par terme
- Évaluer : fidélité au thème (le concept appartient bien à la catégorie du terme), spécificité (assez précis pour générer une image distinctive), diversité (pas de quasi-doublons), feasibility line art

**Métriques** :
- Taux de fidélité thème (cible >95%)
- Taux de quasi-doublons (<10%)
- Taux de sujets trop génériques ou trop complexes (<15%)

**Point d'attention clé** : le champ `name_en` doit suivre le pattern `<Subject> in <Setting>` (règle MANDATORY dans le prompt). Vérifier que c'est bien respecté en pratique — c'est critique pour la qualité du prompt image en aval.

**Livrable** : `2026-05-05_poc-concept-generation.md` + `.json`

---

### POC-3 : Qualité chaîne prompt image EN (étape 6a)

**Question** : le pipeline planner → writer → validator (qwen3:8b × 3 étapes) produit-il des prompts valides et efficaces pour le line art ?

**Protocole** :
- 10 concepts issus du POC-2 (ou manuels si POC-2 non encore exécuté)
- Exécuter la chaîne `create-prompt` complète (ou simuler en appelant les étapes séquentiellement)
- Évaluer : taux de validation au premier essai, latence p50/p95, types d'échecs du validator

**Métriques** :
- Taux de validation premier essai (cible >80%)
- Latence p50 / p95 (budgeter la prod)
- Score validator moyen et distribution par check (structure / line_art_constraints / technical_cleanup / keyword_coverage / kids_safe)
- Patterns de recommandations récurrentes (= faiblesses systématiques du writer)

**Note modèle** : le planner/writer/validator utilise qwen3:8b (pas qwen2.5:7b) — à confirmer sur l'instance Ollama distante (disponibilité + latence réelle).

**Livrable** : `2026-05-05_poc-prompt-chain.md` + `.json`

---

### POC-4 : Génération contenu éditorial AR ancré taxonomie (étape 6b)

**Question** : en fournissant le `term.name_ar` validé comme ancre explicite dans le prompt, peut-on éliminer les erreurs sémantiques sur le sujet (actuellement 30-40% en génération directe) ?

**Contexte** : Les POCs précédents ont éliminé la génération directe FR→AR et EN→AR (hallucinations sémantiques : "دبكة" pour dauphin, "أسد" pour éléphant). L'approche taxonomie-ancrée est le pivot validé en session. **Ce POC est le plus critique du plan : son résultat conditionne toute l'architecture P2 (génération i18n).**

**Protocole** :
- Prérequis : POC-1 validé (termes avec name_ar fiables disponibles)
- 10 sujets image = 10 paires (concept_name_en, term_name_ar) issues de la taxonomie réelle
- Prompt template à tester :
  ```
  Le sujet est "{concept_name_en}".
  Le thème principal en arabe est : {term_name_ar} ({term_name_en}).
  Génère : titre AR (40-60 chars), title_card AR (≤30 chars), description AR (80-130 chars), 5 keywords AR.
  Règles : arabe standard (fusha), pas de harakat, pas de caractères latins.
  ```
- Évaluer : présence du mot AR du sujet dans l'output, conformité bornes Zod, harakat, latin

**Métriques** :
- Taux d'erreur sémantique (cible <5%, vs 30-40% sans ancrage)
- Conformité bornes : title ∈ [40,60], title_card ≤30, description ∈ [80,130]
- Taux harakat (cible 0/10)
- Taux caractères latins (cible 0/10)

**Variante à tester si POC-4a échoue (taux d'erreur >10%)** : fournir le terme AR dans le titre explicitement (ex. `"{concept_name_en}" = "{term_name_ar} في مشهد"`) pour forcer le sujet dans le premier token généré.

**Livrable** : `2026-05-05_poc-ar-anchored-content.md` + `.json`

---

### POC-5 : QC vision LLaVA (étape 8)

**Question** : LLaVA détecte-t-il correctement les images de mauvaise qualité (bruit, couleur, artefacts, non-line-art) ?

**Protocole** :
- Corpus de 10 images : 5 bonnes (line art propre, fond blanc, contours nets) + 5 mauvaises (bruit, couleurs résiduelles, artefacts, flou)
- Passer chaque image par le QC LLaVA existant
- Évaluer : précision, rappel, F1, latence

**Métriques** :
- Précision / Rappel / F1
- **Faux négatifs** (mauvaise image acceptée — risque maximal : publiée)
- **Faux positifs** (bonne image rejetée — coût : travail humain superflu)
- Latence par image

**Note corpus** : si peu d'images "mauvaises" disponibles, en générer intentionnellement (prompt dégradé, ou paramètres ComfyUI perturbés). Prévoir ≥3 types de défauts distincts pour tester la robustesse.

**Livrable** : `2026-05-05_poc-qc-lava.md` + `.json`

---

## Points d'attention

1. **Dépendance en cascade** : POC-4 dépend de POC-1 (sans AR fiables en taxonomie, pas d'ancrage possible). POC-3 peut tourner en parallèle de POC-1/2. POC-5 est indépendant (nécessite juste des images).

2. **Granularité taxonomie = décision architecturale** : si POC-1 révèle que les termes feuilles ne sont pas assez spécifiques (ex. "wild animals" mais pas "lion"), il faut décider : (a) approfondir la taxonomie avant la prod, ou (b) ajouter `name_ar` au schéma de `generate_concepts` et enrichir les concepts post-génération avec `enrich_term`. Option (b) est plus souple mais ajoute un appel LLM par concept.

3. **generate_concepts : gap AR non documenté** — le schéma de sortie de `generate_concepts` n'a pas de `name_ar`. Si l'approche taxonomie-ancrée POC-4 ne suffit pas (taux d'erreur résiduel >10%), le remède naturel est d'ajouter `name_ar` au schéma `generate_concepts` (modifier le prompt) et de l'utiliser comme ancre directe. À tenir en réserve.

4. **qwen3:8b vs qwen2.5:7b** : la chaîne prompt image (POC-3) utilise qwen3:8b — modèle différent des POCs AR (qwen2.5:7b). Vérifier la disponibilité de qwen3:8b sur l'instance Ollama distante avant de lancer POC-3, et mesurer sa latence réelle.

5. **Condition de sortie** : tout POC avec un taux d'erreur >20% sur sa métrique principale déclenche un arbitrage avant de passer au suivant. On ne valide pas une étape fragile et on construit dessus.

## Décision / Action suivante

**Séquence recommandée :**
```
POC-1 → POC-2 → POC-3 (parallèle avec POC-2)
             ↓ (si POC-1 valide les AR)
         POC-4
             ↓ (si images disponibles)
         POC-5
```

**Priorité absolue : POC-1** — son résultat conditionne l'architecture entière de la génération AR (P2). Si la taxonomie n'a pas les AR feuilles nécessaires, il faut enrichir avant tout.

**Prompt Claude Code pour POC-1 :** voir section ci-dessous.

---

## Prompt Claude Code — POC-1

```
Lis CLAUDE.md et docs/brief-claude-desktop.md avant de commencer.

Objectif : POC-1 — Audit couverture AR de la taxonomie + qualité suggest_children.

**Partie A — Audit taxonomie existante**

Écris un script `scripts/poc_taxonomy_ar_coverage.py` qui :
1. Se connecte à la base de données (DATABASE_URL depuis .env)
2. Lit tous les termes (`SELECT id, parent_id, vocabulary_id, name_i18n FROM term`)
3. Pour chaque terme, extrait `name_ar` depuis le JSON `name_i18n`
4. Calcule :
   - % termes avec name_ar non nul et non vide
   - % termes "feuilles" (sans enfants) avec name_ar valide
   - Distribution par vocabulaire (combien de termes par vocab, combien ont name_ar)
5. Identifie les 10 termes feuilles les plus "utiles" comme ancres AR (name_ar court, spécifique, non vide)
6. Exporte les résultats dans `docs/reports/2026-05-05_poc-taxonomy-ar-coverage.json` (ensure_ascii=False)

**Partie B — Test suggest_children**

Depuis 2 termes feuilles choisis parmi les meilleurs du Partie A :
1. Appelle `POST /api/ai/suggest-children` (API doit tourner) avec count=5
2. Pour chaque enfant généré, vérifie : name_ar présent ? non vide ? longueur 1-4 mots ?
3. Vérifie l'absence de doublons avec les termes existants (même name_fr ou name_en)

**Rapport**

Écris `docs/reports/2026-05-05_poc-taxonomy-ar-coverage.md` avec :
- Contexte (1-2 lignes)
- Résultats Partie A (tableau par vocabulaire + chiffres globaux)
- Résultats Partie B (tableau des enfants générés + qualité AR)
- Points d'attention (termes manquants, gaps AR critiques)
- Décision / Action suivante : la taxonomie est-elle prête pour l'ancrage AR en POC-4 ?

Convention reporting : le rapport .md et le .json existent avant la fin de la réponse.
```
