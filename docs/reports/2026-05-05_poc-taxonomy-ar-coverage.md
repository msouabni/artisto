# POC — Audit couverture AR taxonomie + qualité suggest_children
Date : 2026-05-05

## Contexte
POC-1 du sprint Phase 2 (génération i18n). Vérifier (A) la couverture AR de la taxonomie existante en base et (B) la qualité du endpoint `POST /api/ai/suggest-children` pour générer de nouveaux termes enfants — pré-requis pour valider l'usage de la taxonomie comme **source d'ancrage AR** dans la chaîne de génération de contenu (POC-4).

## Résultats

### Partie A — Audit taxonomie

**Couverture globale : excellente (100 %)**

| Métrique | Valeur |
|---|---|
| Total termes en base | **88** |
| Termes avec `name_ar` non vide | **88 / 88 (100 %)** |
| Termes feuilles | 74 |
| Feuilles avec `name_ar` | **74 / 74 (100 %)** |

**Distribution par vocabulaire**

| vocabulary_id | total | avec_ar | leaves | leaves_ar |
|---|---|---|---|---|
| `themes` | 88 | 88 (100 %) | 74 | 74 (100 %) |

Une seule taxonomie active (`themes`). Pas de gap AR à combler.

**Top 10 feuilles candidates ancres AR** (sélection : name_ar court, 1-3 mots, parent identifié, FR + EN présents) :

| id | name_fr | name_ar |
|---|---|---|
| `aid` | Aïd | عيد |
| `animaux_domestiques_cows` | Vaches | البقرة |
| `animaux_domestiques_dogs_chihuahuas` | Chiens de Chihuahua | تشيكواخوا |
| `animaux_domestiques_dogs_pitbulls` | Bulldog Américain | بولي |
| `animaux_domestiques_dogs_pomeranians` | Pomeraniens | بوميرانيان |
| `animaux_domestiques_dogs_poodles` | Pudelp | بوديل |
| `animaux_domestiques_dogs_pugs` | Pug | بوج |
| `animaux_domestiques_dogs_retrievers` | Récupérateurs | المتلقون |
| `animaux_domestiques_dogs_schnauzers` | Schnauzer | شناوسر |
| `animaux_domestiques_dogs_terriers` | Térier | تيرير |

### Partie B — Test `suggest_children`

**2 termes feuilles sondés** : `aid` (Aïd) et `animaux_domestiques_cows` (Vaches). Endpoint async — polling sur `GET /api/jobs/{id}` jusqu'à `awaiting_validation`. Les 2 jobs ont retourné un artefact `taxonomy_import_ops` complet en moins de 60 secondes.

**Qualité AR des 10 suggestions générées : 10/10 ✅**

| Critère | Score |
|---|---|
| `name_ar` présent | 10/10 |
| `name_ar` non vide | 10/10 |
| `name_ar` longueur 1-4 mots | 10/10 |
| Doublon avec existant (id, name_fr, name_en) | 0/10 |

#### Détail — parent `aid`

| id | name_fr | name_ar | mots AR |
|---|---|---|---|
| `aid_hajj` | Activités de l'Aïd | أنشطة العيد الحج | 3 |
| `aid_islamic_sym` | Symboles islamiques | رموز إسلامية | 2 |
| `aid_family_traditions` | Traditions familiales | العادات العائلية | 2 |
| `aid_food_drinks` | Aliments & boissons | الأطعمة والمشروبات | 2 |
| `aid_clothing` | Vêtements | الملابس | 1 |

#### Détail — parent `animaux_domestiques_cows`

| id | name_fr | name_ar | mots AR |
|---|---|---|---|
| `animaux_domestiques_cows_bull` | Taureaux | البقر ذكور | 2 |
| `animaux_domestiques_cows_heifer` | Taureau | البقرات | 1 |
| `animaux_domestiques_cows_tractor` | Égouts | الجرارات الزراعية | 2 |
| `animaux_domestiques_cows_pasture` | Pâturages | الحقول | 1 |
| `animaux_domestiques_cows_feed` | Alimentation | التغذية | 1 |

## Points d'attention

### Côté Partie A
- **Couverture 100 %** : la taxonomie existante est nominalement utilisable comme source d'ancrage AR. Aucun gap critique côté `name_ar`.
- **Volume modeste** : 88 termes au total. Pour un site de coloriage qui produira potentiellement des centaines/milliers d'images, la taxonomie est probablement encore sous-développée. Beaucoup de feuilles concernent une seule famille (chiens), peu de diversité dans d'autres catégories.
- **Qualité lexicale AR de la base existante** : non audité par cet POC (qui ne juge que la présence/longueur). Quelques entrées paraissent suspectes en lecture rapide (ex. `Pudelp` côté FR pour caniche, `بوديل` côté AR — translittération phonétique douteuse), mais c'est une question d'évaluation humaine, pas mécanique.

### Côté Partie B
- **Qualité formelle AR : 10/10** sur les 4 critères mécaniques (présence, non-vide, 1-4 mots, pas de doublon).
- **2 incohérences FR/EN graves** détectées dans les suggestions, indépendantes du AR mais à signaler :
  - `animaux_domestiques_cows_heifer` (heifer = "génisse" en EN) → `name_fr = "Taureau"` (Taureau = mâle, pas génisse). Le AR `البقرات` = "vaches" (pluriel féminin), proche mais imprécis.
  - `animaux_domestiques_cows_tractor` → `name_fr = "Égouts"` (??? complètement faux, devrait être "Tracteur"). Le AR `الجرارات الزراعية` = "tracteurs agricoles" est correct.
  - → Le LLM a des erreurs **de cohérence cross-locale** dans le suggest_children. Le AR seul peut être OK alors que FR ou EN est faux. Cela conforte la thèse "EN-first puis traduction guidée" plutôt que "génération multi-locale parallèle".
- **`بولي`** pour Bulldog (entry 4 du top A) ressemble à une translittération phonétique improbable (Bully?) — qualité lexicale AR du seed à auditer manuellement avant d'utiliser comme ancre.
- **Format du `result` job** : c'est une string JSON wrappée (`taxonomy_import_ops` artifact), avec les nouveaux termes dans `proposal.operations[].value`. À documenter dans `job_review_artifact.py` si on étend pour un autre type.

### Côté pipeline
- Le endpoint async + polling fonctionne (job_id retourné en 202, completion en awaiting_validation < 60s pour count=5). Le worker `taxonomy_suggest_children` est actif et opérationnel.
- 2 jobs en `awaiting_validation` ont été créés pendant ce POC (aid, animaux_domestiques_cows) — non appliqués, à rejeter manuellement si non voulus en base.

## Décision / Action suivante

✅ **La taxonomie est prête pour servir d'ancrage AR au POC-4** côté couverture (100 %).

⚠ **Conditionnel à l'audit qualité humain** des entrées AR existantes (translittérations phonétiques à valider) avant de les utiliser comme exemples few-shot dans le prompt EN→AR. Suggest_children produit un AR formellement correct mais avec des erreurs FR/EN parasites — si on l'utilise pour étendre la taxonomie, il faut une étape de **revue humaine systématique** avant `apply` (ce que le contrat de revue prévoit déjà via `awaiting_validation`).

**Action proposée pour POC-4** :
1. Utiliser les `name_ar` du **top 10 feuilles** comme exemples few-shot dans le prompt EN→AR (animal lexicon réel).
2. Auditer manuellement la qualité de ces 10 entrées AR avant d'en faire des exemples (30 min de revue humaine).
3. Pour la stratégie d'extension de taxonomie : confirmer que `suggest_children` reste async + revue humaine, pas auto-apply.

**Question ouverte** : faut-il enrichir la taxonomie avant POC-4 (élargir au-delà de chiens + Aïd) ou suffit-il d'utiliser les feuilles existantes comme ancres pour la génération de contenu ? À arbitrer côté Claude Desktop / hamma.

## Annexes

Données brutes : `2026-05-05_poc-taxonomy-ar-coverage.json`
Script : `scripts/poc_taxonomy_ar_coverage.py`
2 jobs `awaiting_validation` créés : `job_ai_1777970742496806600_6935`, `job_ai_1777970783948490500_3374` (à rejeter manuellement si non voulus).
