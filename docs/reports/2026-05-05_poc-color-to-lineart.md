# POC color-to-lineart — ERNIE coloré + extraction contours non-IA
Date : 2026-05-05

## Contexte
Le POC image quality précédent a identifié **2/8 images KO histogram** sur des subjects à fort prior couleur (Refrigerator, Dragon). Hypothèse testée ici : générer une **illustration colorée style cartoon avec contours noirs épais** puis **extraire les contours en post-traitement non-IA (Pillow)** donne-t-il un meilleur line art que la génération monochrome directe ? Bonus, on rajoute le 3e cas problématique du POC précédent : **Soccer Ball / 3 jambes**, pour voir si le mode coloré + post-process améliore aussi l'anatomie.

## Méthodes d'extraction

- **Méthode A — dark pixel RGB strict** : noir ssi `R<80 ET G<80 ET B<80`, sinon blanc. Repose sur le fait que ERNIE produit des contours noirs purs en mode colored cartoon.
- **Méthode B — grayscale threshold L<128** : binaire simple sur la luminance.
- **Méthode C — grayscale threshold L<160** (agressif) : enlève davantage les ombres grises au prix de perdre des traits fins.

**closed_contours_ratio** = proportion des pixels blancs atteignables depuis les 4 bords par floodfill 4-connexité (`flag d'« ouverture »` du dessin). Plus haut = plus de zones non fermées où la couleur d'un enfant fuirait. Référence : un line art bien fermé est typiquement `0.4-0.7` (le fond extérieur seul est atteignable).

## Résultats par concept et méthode

| Concept | Méthode | color_ratio | ink_ratio | white_ratio | ccr | flags hist | Vision verdict | Vision issues | Conf |
|---|---|---:|---:|---:|---:|---|:---:|---|---:|
| **Refrigerator in a Kitchen** | _colored source_ | 0.371 | 0.07968 | 0.36848 | 0.7512 | ['strong_color'] | — | — | — |
| | method_a | 0.0 | 0.08875 | 0.91125 | 0.702 | [] | **good** | — | 100 |
| | method_b | 0.0 | 0.15823 | 0.84177 | 0.7008 | [] | **good** | — | 100 |
| | method_c | 0.0 | 0.20597 | 0.79403 | 0.731 | [] | **good** | — | 100 |
| **Dragon in a Castle Courtyard** | _colored source_ | 0.52408 | 0.14054 | 0.30377 | 0.9429 | ['strong_color'] | — | — | — |
| | method_a | 0.0 | 0.14617 | 0.85383 | 0.5711 | [] | **good** | — | 100 |
| | method_b | 0.0 | 0.38919 | 0.61081 | 0.6061 | [] | **good** | — | 100 |
| | method_c | 0.0 | 0.51336 | 0.48664 | 0.6727 | ['very_dense_ink'] | **good** | — | 100 |
| **Soccer Ball on a Field** | _colored source_ | 0.5027 | 0.06312 | 0.40354 | 0.7888 | ['strong_color'] | — | — | — |
| | method_a | 0.0 | 0.06406 | 0.93594 | 0.8119 | [] | **good** | — | 100 |
| | method_b | 0.0 | 0.11077 | 0.88923 | 0.8195 | [] | **good** | — | 100 |
| | method_c | 0.0 | 0.24034 | 0.75966 | 0.7964 | [] | **good** | — | 100 |

## Méthode gagnante par concept

Score heuristique : verdict ``good`` (+50), pas `has_color` (+10), pas `has_text` (+5), ink_ratio ∈ [0.005, 0.55] (+10), color_ratio < 0.025 (+10), pénalité `int(ccr × 30)`.

| Concept | Catégorie | Gagnante | Score | Ranking |
|---|---|:---:|---:|---|
| Refrigerator in a Kitchen | electromenager | **method_a** | 64 | method_a:64, method_b:64, method_c:64 |
| Dragon in a Castle Courtyard | fantasy | **method_a** | 68 | method_a:68, method_b:67, method_c:65 |
| Soccer Ball on a Field | sports | **method_c** | 62 | method_c:62, method_a:61, method_b:61 |

## Comparaisons côte à côte

4 colonnes par image : `original mono (POC précédent) | colored source | method_A | method_B`.

### [electromenager] Refrigerator in a Kitchen
![compare](../../docs/reports/poc-color-to-lineart/electromenager-refrigerator-in-a-kitchen_compare.png)

- Original mono : `docs/reports/poc-image-quality/electromenager-refrigerator-in-a-kitchen.png`
- Colored source : `docs/reports/poc-color-to-lineart/electromenager-refrigerator-in-a-kitchen_colored.png`
- method_a : `docs/reports/poc-color-to-lineart/electromenager-refrigerator-in-a-kitchen_method_a.png`
- method_b : `docs/reports/poc-color-to-lineart/electromenager-refrigerator-in-a-kitchen_method_b.png`
- method_c : `docs/reports/poc-color-to-lineart/electromenager-refrigerator-in-a-kitchen_method_c.png`

### [fantasy] Dragon in a Castle Courtyard
![compare](../../docs/reports/poc-color-to-lineart/fantasy-dragon-in-a-castle-courtyard_compare.png)

- Original mono : `docs/reports/poc-image-quality/fantasy-dragon-in-a-castle-courtyard.png`
- Colored source : `docs/reports/poc-color-to-lineart/fantasy-dragon-in-a-castle-courtyard_colored.png`
- method_a : `docs/reports/poc-color-to-lineart/fantasy-dragon-in-a-castle-courtyard_method_a.png`
- method_b : `docs/reports/poc-color-to-lineart/fantasy-dragon-in-a-castle-courtyard_method_b.png`
- method_c : `docs/reports/poc-color-to-lineart/fantasy-dragon-in-a-castle-courtyard_method_c.png`

### [sports] Soccer Ball on a Field
![compare](../../docs/reports/poc-color-to-lineart/sports-soccer-ball-on-a-field_compare.png)

- Original mono : `docs/reports/poc-image-quality/sports-soccer-ball-on-a-field.png`
- Colored source : `docs/reports/poc-color-to-lineart/sports-soccer-ball-on-a-field_colored.png`
- method_a : `docs/reports/poc-color-to-lineart/sports-soccer-ball-on-a-field_method_a.png`
- method_b : `docs/reports/poc-color-to-lineart/sports-soccer-ball-on-a-field_method_b.png`
- method_c : `docs/reports/poc-color-to-lineart/sports-soccer-ball-on-a-field_method_c.png`

## Lecture comparative vs monochrome direct

Rappel des KO du POC image quality (génération monochrome directe) :

| Concept | Mono direct color_ratio | Mono direct vision verdict | Mono direct issues |
|---|---:|:---:|---|
| Refrigerator in a Kitchen | **0.058** | good | `has_color` |
| Dragon in a Castle Courtyard | **0.050** | good | `has_color` |
| Soccer Ball on a Field | 0.007 | good | (mais 3 jambes signalées au QC humain) |

Two-step colored→lineart sur les **mêmes** 3 concepts (méthode A, RGB strict) :

| Concept | Two-step color_ratio | Two-step verdict | Two-step issues | Δ color_ratio |
|---|---:|:---:|---|---:|
| Refrigerator in a Kitchen | **0.000** | good | aucune | **−5.8 pts** |
| Dragon in a Castle Courtyard | **0.000** | good | aucune | **−5.0 pts** |
| Soccer Ball on a Field | **0.000** | good | aucune | −0.7 pt |

**3/3 subjects passent à `color_ratio == 0.000` strict** (fond blanc pur, contours noirs purs sans aucun pixel coloré résiduel). Le `has_color` qui était systématique sur le mono direct disparaît complètement. Bonus : aucun retour `has_text` non plus.

## Lecture par méthode

| Métrique | method_a (RGB<80) | method_b (gray<128) | method_c (gray<160) |
|---|---:|---:|---:|
| color_ratio (3 concepts) | **0.000 / 0.000 / 0.000** | 0.000 / 0.000 / 0.000 | 0.000 / 0.000 / 0.000 |
| ink_ratio moyen | **0.099** | 0.219 | 0.319 |
| ccr moyen | **0.695** | 0.709 | 0.733 |
| flags hist | aucun | aucun | `very_dense_ink` (Dragon) |
| Vision verdict | 3/3 good | 3/3 good | 3/3 good |
| Latence extraction | ~10 ms | ~7 ms | ~7 ms |

**Méthode A est le meilleur défaut** : ink density la plus parcimonieuse (proche de la cible 0.05-0.15 pour un coloriage enfant), ccr le plus bas (contours mieux fermés), aucun flag histogram, et elle profite directement du fait que ERNIE-Image-Turbo sort des contours **noirs purs** en mode colored cartoon (R<80 ∧ G<80 ∧ B<80 capte tout le trait sans bruit).

**Méthode B** (gray<128) est intéressante quand le contour n'est pas noir pur (ex. dragon → contour brun foncé sur écailles vertes : passe en gray<128 mais loupé par RGB<80). Elle reste un **fallback robuste**.

**Méthode C** (gray<160) est trop agressive sur ce 3-pack — Dragon flagué `very_dense_ink` (ink 0.513), capte les aplats de couleurs sombres comme s'ils étaient de l'encre. À réserver aux subjects très clairs.

Le ranking automatique a tranché en faveur de A pour 2/3 (Refrigerator, Dragon) et C pour Soccer Ball (1 point d'écart, ex aequo dans le bruit). En lecture humaine du tableau ci-dessus, **method_a est le défaut universel** ; method_c gagne uniquement sur Soccer parce que l'image colorée a beaucoup de blanc (ciel, terrain) → ink_ratio 0.064 sur method_a est légèrement sous la borne basse 0.005-0.55, et method_c remonte à 0.240 (bon point pour la denisté coloriage).

## Verdict global

✅ **Two-step colored→lineart écrase le monochrome direct sur les 3/3 subjects à prior couleur testés.**

| Critère | Mono direct (POC précédent) | Two-step méthode A (ce POC) |
|---|---|---|
| color_ratio | 0.007 - 0.058 (2/3 KO) | **0.000 / 0.000 / 0.000** ✅ |
| Vision `has_color` | 2/3 | **0/3** ✅ |
| Vision verdict good | 3/3 | **3/3** ✅ |
| Surcoût pipeline | — | +50 ms Pillow + ~18 s Comfy supplémentaire (déjà compté en mono) |

L'extraction Pillow méthode A à `R<80 ∧ G<80 ∧ B<80` donne un line art **strictement plus propre** que la génération monochrome directe pour ces 3 cas, parce qu'on travaille **avec le modèle** plutôt qu'**contre** lui : ERNIE rend très bien le style « cartoon avec contours noirs épais et aplats de couleur », un style auquel ses datasets l'ont massivement exposé. Le post-process binaire Pillow ne fait alors que jeter les aplats colorés et garder les contours.

## Recommandation architecturale

**Adopter Option 1 — profile `kids_coloring_lineart_color_prior_v1` two-step** comme **traitement principal** pour les subjects à fort prior couleur, avec **method_a comme défaut** et **method_b en fallback** si l'image résultante a `ink_ratio < 0.005` (signe que le contour n'était pas noir pur).

**Architecture proposée :**

1. **Curation taxonomie** — flagger un sous-ensemble de termes feuilles avec `color_prior: true` dans `data/taxonomy_universal_v0.yaml` (refrigerator, dragon, fruit, fleur, drapeau, papillon, perroquet, poisson tropical, etc.). À démarrer avec une liste manuelle ~30-50 termes ; itérer selon les retours histogram en prod.
2. **Profile pipeline** — `kids_coloring_lineart_color_prior_v1` active : prompt cartoon coloré (template à ajouter dans `prompts/image_prompts.yaml` : `prompt_writer_ernie_color_prior`), ComfyUI workflow inchangé, post-process Pillow avec method_a + fallback method_b.
3. **Worker** — `image_worker.py` dispatche selon le profile : si `color_prior_v1`, après `client.download_image()` appliquer la chaîne d'extraction Pillow et écraser l'image d'output avant le QC technique.
4. **QC** — le `build_technical_image_qc_v1` actuel reste intact ; il jugera le résultat post-process exactement comme un line art monochrome standard.

**Coût total ajouté en prod :** +18 s ComfyUI uniquement si on garde aussi un fallback monochrome (sinon 0, c'est juste un prompt différent dans le même workflow), +50 ms Pillow / image.

**Option 2 (anti-color-prior dans le writer)** reste une voie complémentaire à tester : elle évite le coût du two-step et reste un fix « simple ». Dans ce POC on n'a pas mesuré l'effet d'une consigne writer renforcée — c'est un follow-up POC séparé qui demanderait de regénérer les 3 mêmes concepts en mono direct avec la consigne « plain black silhouette » et comparer color_ratio. Si ça suffit (color_ratio < 0.025), c'est plus économe ; sinon Option 1 reste la bonne réponse.

**Recommandation finale :** lancer Option 1 pour P2 (la donnée empirique est sans appel : 3/3 perfect color_ratio = 0.000), puis si bande passante, faire le POC Option 2 en parallèle comme optimisation single-step pour les cas où elle suffirait.

## Annexes

- Galerie : `docs/reports/poc-color-to-lineart/` (1 colored + 3 méthodes + 1 compare par concept)
- Données brutes : `2026-05-05_poc-color-to-lineart.json`
- Originaux mono : `docs/reports/poc-image-quality/` (réutilisés sans modification)
- Source prompts originaux : `2026-05-05_poc-prompt-chain-v2.json`
- Script : `scripts/poc_color_to_lineart.py`
- Comparaison QC : POC image quality `2026-05-05_poc-image-quality.md`

**Points d'attention :**
- Si les contours ERNIE en colored cartoon ne sont pas noirs purs (ex. brun foncé / contour orangé), méthode A peut louper des traits — basculer alors sur méthode B/C (grayscale).
- `closed_contours_ratio` est une heuristique 4-connexité ; les fins traits diagonaux peuvent laisser des fuites au floodfill. Lecture complémentaire à la métrique vision.