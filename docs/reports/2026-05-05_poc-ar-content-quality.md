# POC — Qualité du contenu arabe généré par Ollama
Date : 2026-05-05

## Contexte
Tester si **qwen2.5:7b** génère de l'arabe **naturel et idiomatique** pour le contenu éditorial d'un site de coloriage enfants (4-10 ans), avant de bâtir la Phase 2 du plan dessus. Évaluation portée sur 10 concepts FR variés ; pour chacun, l'LLM doit produire un JSON `{title, title_card, description, keywords[]}` directement en arabe.

## Résultats

### Métriques quantitatives

| Métrique | Score |
|---|---|
| JSON parsable | 10/10 ✅ |
| Schema (4 clés présentes) | 10/10 ✅ |
| `title` ∈ [40, 60] chars (borne Zod) | **0/10** (tous trop courts : 13–38 chars) |
| `title_card` ≤ 30 chars | 10/10 ✅ |
| `description` ∈ [80, 130] chars (borne Zod) | **1/10** (entry 7 = 83 chars) |
| `keywords` array de 3 items | 10/10 |
| Latence 1er appel (cold) | 21.6s |
| Latence appels suivants | 3.8s – 7.3s |

**Conclusion bornes Zod : 0/10 outputs respectent toutes les bornes du contrat Alwan §4.**

### Anomalies mécaniques observées

- **Vocalisation imprévue** dans 3/10 (entries 6, 7, 8) — harakat insérées sans qu'on les demande, pendant que les 7 autres sont en arabe non vocalisé. Inconsistant.
- **Caractères latins dans champ AR** : entry 5 a `"أسماك الocean"` — "ocean" en latin dans un mot arabe.

### Erreurs sémantiques graves (évaluation humaine confirmée)

| # | Concept FR | Sortie AR | Traduction littérale du AR |
|---|---|---|---|
| 4 | éléphant avec ses petits | `الإنسان الأفريقي مع صغاره` | **"l'humain africain avec ses petits"** ❌ |
| 6 | renard dans la forêt | `الحَرْسُ الأَحْمَرُ في الغابة` | **"le garde rouge dans la forêt"** ❌ |

Le modèle remplace l'animal du concept FR par un nom complètement étranger. Pas une nuance de traduction — une **dérive sémantique majeure**.

## Points d'attention

- **Bornes Zod systématiquement violées** : sans guidance plus stricte, 0 contenu publiable. Il faudra soit (a) prompts beaucoup plus contraignants avec exemples few-shot dans la borne, soit (b) boucle de validation+regen, soit (c) abandonner la génération AR directe.
- **2 erreurs sémantiques sur 10** : taux d'erreur de 20 % au niveau du sujet du contenu. Inacceptable en prod sans QC humain ou pipeline de validation.
- **Vocalisation aléatoire** : règle à imposer explicitement dans le prompt (ne **jamais** vocaliser, ou vocaliser systématiquement — choisir une politique).
- **Mixage AR/EN** : règle à imposer dans le prompt (zéro caractère latin dans les champs AR).
- **Cold start** ~22s sur la 1re requête : à anticiper pour le batch.

## Décision / Action suivante

❌ **Génération AR directe (FR concept → AR contenu) éliminée.**

✅ **Option EN-first validée** :
1. Générer en EN d'abord (qwen2.5:7b est probablement plus fiable sur EN).
2. Traduire EN → AR avec un prompt **guidé** qui :
   - Impose les bornes de longueur AR avec exemples
   - Interdit explicitement la vocalisation
   - Interdit les caractères latins
   - Fournit le concept FR + EN comme double ancrage pour éviter les dérives sémantiques

À tester dans un prochain POC avant d'engager Phase 2 LLM i18n.

POC jetable : `scripts/poc_ar_content_quality.py`.
