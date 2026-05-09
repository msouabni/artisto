# POC — Vocalisation arabe par Ollama (qwen2.5:7b)
Date : 2026-05-05

## Contexte
Tester si **Ollama (qwen2.5:7b, T=0)** peut produire du texte arabe **vocalisé** (avec harakat) de façon fiable, pour servir d'input à la chaîne de translittération déterministe (Option A du plan : LLM vocalise → fonction `ar_to_slug` opère sur du vocalisé).

## Résultats

10 titres du corpus envoyés au modèle avec le prompt :
> *"Vocalise ce titre arabe en ajoutant les harakat (tashkil) complets. Réponds uniquement avec le titre vocalisé, rien d'autre."*

| Métrique | Score |
|---|---|
| Réponses obtenues | 10/10 |
| Slugs valides regex (post-translittération) | 10/10 |
| Vocalisation lexicalement correcte | **~5/10** (estimation au mot, pas au titre) |
| Match exact slug attendu corpus | **0/10** |
| Latence min / max | 1.7s / 121.2s |

### 3 problèmes distincts identifiés

#### Problème 1 — Vocalisation lexicalement fausse (le plus grave)
Au moins 5+ mots vocalisés avec **mauvais sens** :
- قط → `قَطٌ` (qaṭ "sec/seulement") au lieu de `قِطٌّ` (qiṭṭ "chat")
- دب → `دَب` (dab) au lieu de `دُبٌّ` (dubb "ours")
- فيل → `فيَّل` (fayyal, shadda inventée) au lieu de `فِيل` (fīl "éléphant")
- كلب → `كلَّب` (klāb) au lieu de `كَلْب` (kalb "chien")
- ملونة → `مُلْوَنَةٌ` (sans shadda) au lieu de `مُلَوَّنَة` (mulawwana, shadda manquante)
- حصان → `حصَّان` (ḥaṣṣān, shadda fausse) au lieu de `حِصَان` (ḥiṣān)

Le modèle ne comprend pas systématiquement le sens du mot et place des voyelles cohérentes morphologiquement mais lexicalement fausses. **Non corrigeable** par adaptation downstream.

#### Problème 2 — Artefacts post-vocalisation côté `ar_to_slug` (corrigeable)
Tanwin terminal, voyelles longues doublées (`ii`/`uu`/`aa`), tāʾ marbūṭa+harakat → générait des slugs comme `aasdun-fii-al-ghaabaai`. Adressable par adaptation des règles.

#### Problème 3 — Latence imprévisible
2 titres sur 10 ont pris > 30 secondes (33s et 121.2s) contre ~1.8s pour le reste (probable cold-start / context shift). **Inacceptable en prod** pour batch — sur 100 images : minutes aléatoires.

## Points d'attention

- L'option A est **non viable avec qwen2.5:7b** : même si on règle les artefacts (problème 2) et qu'on tolère la latence (problème 3), les vocalisations lexicalement fausses (problème 1) produisent du contenu **éditorialement incorrect**.
- Tester avec un modèle plus gros (qwen2.5:14b) ou spécialisé arabe (Jais, AceGPT) serait pertinent **si l'option D ne convient pas**.
- Cold start ~22s sur la 1re requête : à anticiper si on garde Ollama dans le pipeline pour autre chose.

## Décision / Action suivante

❌ **Option A éliminée** (LLM vocalise, fonction translit déterministe).

Voie retenue : **Option B (Mishkal — lib rule-based)**, validée dans le POC `2026-05-05_poc-ar-transliteration.md` à 30/30 sur le même corpus.

POC jetable : `scripts/poc_ar_vocalisation.py` (peut être archivé).
