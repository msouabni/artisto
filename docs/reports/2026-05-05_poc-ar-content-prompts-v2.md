# POC — Comparaison de prompts AR (A vs B avec few-shot)
Date : 2026-05-05

## Contexte
Itération sur le POC `ar-content-quality` du même jour. Test de deux prompts pour générer du contenu éditorial AR (titre + title_card + description + keywords) depuis un concept EN, sur les 10 mêmes concepts du jeu de test (traduits FR→EN). Modèle : qwen2.5:7b, T=0.

- **Prompt A** : structure stricte (consignes + bornes + JSON template, **sans exemple**).
- **Prompt B** : structure + **un exemple few-shot complet** (le concept "lion in the savanna" sert d'illustration).

## Résultats

### Synthèse quantitative

| Métrique | Prompt A | Prompt B |
|---|---|---|
| JSON parsable | 10/10 ✅ | 10/10 ✅ |
| `title` ∈ [40, 60] | **0/10** ❌ | **8/10** ✅ |
| `title_card` ≤ 30 | 10/10 ✅ | 10/10 ✅ |
| `description` ∈ [80, 130] | **0/10** ❌ | **0/10** ❌ (tous trop courts, médiane ~67) |
| Harakat indésirables | 1/10 | 0/10 ✅ |
| Caractères latins dans AR | **6/10** ❌ | 1/10 ✅ |
| Latence moyenne | 7.4s | 5.1s |

**Verdict métriques** : B nettement meilleur sur `title` (longueur), `latin` (interdit), latence. Description trop courte des deux côtés. `title_card` toujours OK.

### Erreurs sémantiques observées (animal/sujet remplacé)

#### Prompt A
| # | Concept EN | AR généré (title) | Traduction littérale |
|---|---|---|---|
| 7 | white rabbit | `صغيرة مع خفيف الألوان الفأر الأبيض` | "petite avec léger les couleurs **le rat** blanc" — *rat* au lieu de *lapin* |
| 9 | turtle on a rock | `طفلة تلوّن فقيرتها الصغيرة على حجر` | description AR mentionne `قرد` = **singe** au lieu de tortue |
| 10 | jumping dolphin | `دolphin يقفز في الماء` | mot **"dolphin" en latin** au lieu de دلفين |

#### Prompt B
| # | Concept EN | AR généré (title) | Traduction littérale |
|---|---|---|---|
| 4 | elephant with its babies | `استمتع برسم أسد بابا مع صغاره في الغابة الخضراء` | "amusez-vous à dessiner un **lion papa** avec ses petits..." — **lion** au lieu d'**éléphant** |
| 6 | fox in the forest | `استمتع برسم فهد يمشي في الغابة الخضراء...` | "...un **guépard** marche dans la forêt..." — **guépard** au lieu de **renard** |
| 9 | turtle on a rock | `استمتع برسم تنين يقف على حجر في الطبيعة الجميلة` | "...un **dragon** se tient sur un rocher..." — **dragon** au lieu de **tortue** |
| 10 | jumping dolphin | `استمتع برسم دبكة تلعب في الماء الجميل مع الأمواج` | "...une **debka** [danse traditionnelle arabe] joue dans l'eau..." — **debka** (pas un animal) au lieu de **dauphin** |

**Taux d'erreur sémantique au sujet** : A = 3/10 (~30 %), B = 4/10 (~40 %).

### Analyse — pourquoi B ne réduit pas les erreurs sémantiques

L'exemple few-shot apprend au modèle la **structure** (le pattern `استمتع برسم X في Y`, le `رائع للتلوين` final, les keywords avec `تلوين X`) mais **n'apprend rien sur le vocabulaire AR de l'animal X**. Quand le modèle hallucine sur le mot AR de l'animal cible, le few-shot ne corrige pas — il propage l'hallucination dans la structure copiée.

C'est cohérent avec le finding du POC vocalisation : **qwen2.5:7b a des trous lexicaux en arabe** indépendamment du prompting.

### Description trop courte — pattern commun

Les 10 descriptions de B suivent le pattern `{sujet} {action} {décor} {trait}، رائع للتلوين`. Construction qui plafonne naturellement à ~60-75 chars. La borne basse Zod (80) demande une phrase plus riche (sujet composé, ou 2 actions). À ajuster dans le prompt avec un sweet-spot explicite ou un 2nd exemple de description plus longue.

## Points d'attention

- **Few-shot apprend la structure, pas le vocabulaire.** L'exemple aurait pu inclure 3-4 concepts différents pour que l'animal change ; même là, ça ne fixerait pas une hallucination sur un animal **non vu** dans les exemples. Conclusion : le vocabulaire AR fiable doit venir d'**ailleurs** que du LLM seul.
- **Le mot `أسد بابا` (lion papa)** dans la sortie B pour "elephant with its babies" est particulièrement révélateur : le modèle a copié l'animal de l'exemple few-shot (lion) parce qu'il avait du mal avec "elephant" au pluriel/familial.
- **`دبكة` (debka)** pour dolphin = quasi-pun phonétique avec "doll" / "dolph". Le modèle prend le son anglais et trouve un mot AR proche, sans rapport sémantique. Risque type "LLM faux ami" persistant.
- **Bornes description** : viser un sweet-spot rallongé (e.g. "70-100" pour cibler la moyenne, ou ajouter un exemple long).
- **Caractères latins** : B presque clean (1/10 seulement, "natuurة" hybride). Le `No Latin` dans la consigne suffit avec exemple.

## Décision / Action suivante

❌ **Génération AR depuis concept EN seul (avec ou sans few-shot) ÉLIMINÉE pour la prod**. Taux d'erreur sémantique de 30-40 % inacceptable, indépendant du prompting.

✅ **Pivot : EN-first complet, puis traduction guidée AR avec triple ancrage** :
1. Génère le contenu en **EN** depuis le concept (qwen2.5:7b est probablement plus fiable côté lexical EN — à vérifier dans un POC dédié).
2. Traduit EN → AR avec un prompt qui fournit explicitement :
   - Le concept EN
   - Le concept FR (si disponible)
   - Le contenu EN à traduire (title, title_card, description, keywords)
   - Les bornes Zod AR adaptées (densité 50 % inférieure pour AR : ~30-50 chars title, ~50-90 desc — à recalibrer)
   - Interdiction explicite : pas de harakat, pas de latin
3. Validation post-LLM : regex bornes + check absence latin/harakat + check "le mot du concept EN apparaît bien dans la traduction AR" (sanity check sémantique léger).

À tester dans un prochain POC : `poc_ar_content_en_first.py`.

**Garder Prompt B comme fallback** pour la structure (good for `title` length + `latin` cleanliness) si la voie EN-first échoue. Mais pas en prod sans validation sémantique humaine.

## Annexes

Données brutes : `2026-05-05_poc-ar-content-prompts-v2.json`
Script : `scripts/poc_ar_content_prompts_v2.py`
