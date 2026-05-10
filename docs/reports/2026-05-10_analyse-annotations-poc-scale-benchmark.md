# Analyse — Annotations POC scale-benchmark (verdicts auto A/B/C)

Date : 2026-05-10
Scope : `docs/reports/poc-scale-benchmark/annotations.json` (515 entrées) + 38 fichiers `index-*.json` + `rerun-2objets.json` (13 paires v1/v2). Skill `prompt-taxonomy-ecosystem` (SKILL.md + references/techniques.md) lu pour vocabulaire et taux de référence.

## Contexte

Trois critères de sortie du cycle architecte arbitrés mécaniquement par règles dérivées du skill :
- A : extinction `2_objets` sur le rerun v1→v2 (13 paires)
- B : tenue de la composition sur 4 méta-patterns (Grille imagier annoté, Imagier différencié 3×3, Frise narrative 1×N, Multi-sujets via grille)
- C : cohérence des workflow_classes "OU"

## Résultats

### 1. Vocabulaire défauts annotations vs skill (anti-hallucination)

Le mapping canonique skill (v1) → tag annotation v2 vient de `scripts/migrate_benchmark_annotations.py:33`. Tags v2 effectivement présents dans `annotations.json` (515 entrées) :

| Tag v2 (image_tags) | n | Mappé vers (v1 canonique skill) | Statut |
|---|---|---|---|
| `image_pas_coherente` | 66 | **AUCUN** | **GAP — vocab v2 hors mapping** |
| `image_incomprehensible` | 64 | **AUCUN** | **GAP — vocab v2 hors mapping** |
| `image_duplication` | 28 | `2_objets` | OK |
| `image_anatomie_pb` | 23 | `3_jambes` | OK |
| `image_compo_bonne` | 15 | (positif, hors défauts) | n/a |
| `image_simpliste` | 14 | **AUCUN** | **GAP — vocab v2 hors mapping** |
| `image_prompt_non_respecte` | 9 | `prompt_incohérent` | OK |
| `image_creative` | 7 | (positif, hors défauts) | n/a |
| `image_coherente` | 6 | (positif, hors défauts) | n/a |
| `image_flou` | 5 | `traits_flous` | OK |
| `image_physique_pb` | 4 | `perspective_KO` | OK |
| `image_gris_residuel` | 1 | `gris_résiduel` | OK |

**Tags v1 du skill jamais observés dans v2** : `couleurs_résiduelles` (→ `image_traces_couleur` : 0 occurrence), `traits_doubles`/`traits_discontinus` (→ `image_traits_pb` : 0 occurrence).

**Écart majeur** : les deux tags les plus utilisés (`image_pas_coherente` + `image_incomprehensible` cumulent **130 occurrences sur 515**, soit ~25% de la table) **n'existent pas dans le mapping `migrate_benchmark_annotations.py`** ni dans la table de défauts canoniques du skill (SKILL.md §"Défauts annotés"). Les annotateurs humains ont introduit un vocabulaire post-migration que ni le skill ni le script de mapping ne reconnaissent.

**Conséquence opérationnelle** : tout verdict mécanique fondé sur les 4 défauts canoniques (`2_objets`, `3_jambes`, `prompt_incohérent`, `traits_flous`) ignore la majorité du signal qualitatif accumulé par l'annotateur humain. C'est précisément ce qui survient au verdict B ci-dessous.

`prompt_tags` (n=19 total) et `custom_tags` (texte libre, n=39 total) confirment des concepts non couverts (`prompt_complexe`, `prompt_ambigu`, `bizarre`, `comptage`, `incomplet`, `tramage en gris`, etc.).

### 2. Verdict A — extinction `2_objets` sur 13 paires v1/v2

Tag canonique recherché : `image_duplication` (= `2_objets` v1).

| leaf_id | dup_v1 | dup_v2 | score_v1 | score_v2 | publishable_v1 | publishable_v2 |
|---|---|---|---|---|---|---|
| bactrian_camel | oui | **OUI (résiduel)** | 1 | 5 | False | False |
| chimpanzee | oui | non | 1 | 6 | None | True |
| eid_al_adha_sheep | oui | non | 1 | 6 | None | True |
| golden_retriever | oui | **OUI (résiduel)** | 1 | 1 | None | None |
| house_painter_with_roller | oui | non | 1 | 5 | None | True |
| labrador_retriever | oui | non | 1 | 6 | None | True |
| mountain_gorilla | oui | **OUI (résiduel)** | 1 | 1 | None | None |
| playful_dolphin | oui | **OUI (résiduel)** | 1 | 1 | None | None |
| running_cheetah | oui | **OUI (résiduel)** | 1 | 1 | None | None |
| running_giraffe | oui | **OUI (résiduel)** | 1 | 1 | None | None |
| sheep_with_lamb | oui | non | 1 | 6 | None | True |
| snow_leopard | oui | non | 1 | 6 | None | True |
| spotted_hyena | oui | non | 1 | 6 | None | True |

Tous les v1 portent `image_duplication` (cohérent avec la sélection rerun). Toutes les paires sont annotées des deux côtés.

**6/13 v2 résiduels avec `image_duplication`** : `bactrian_camel`, `golden_retriever`, `mountain_gorilla`, `playful_dolphin`, `running_cheetah`, `running_giraffe`.

Règle skill : ≥ 4 v2 résiduels ⇒ **Fix insuffisant**.

**>>> Verdict A : Fix insuffisant**

Sous-pattern observé (à confirmer humainement) : 5 des 6 résiduels sont des Solo animal en pose de course/mouvement (cheetah, giraffe — `running_*`) ou en contexte aquatique/photogénique (dolphin) ou avec dimorphisme/duplication par symétrie (camel à deux bosses, gorilla, golden retriever). 7 solos statiques en profil sont fixés sans résiduel. Hypothèse à challenger : le `_ISOLATION` suffix + NEGATIVE_V3 fonctionnent sur la pose statique de profil, échouent sur la pose dynamique ou la silhouette compacte.

### 3. Verdict B — composition méta-patterns

Pour chaque méta-pattern, comptage des 4 défauts canoniques skill (présents dans le mapping v1→v2). Taux de référence tirés de SKILL.md §"Défauts annotés" : `2_objets ~8%`, `3_jambes ~6%`, `prompt_incohérent ~4%`, `traits_flous ~2%`.

| Méta-pattern | N | 2_objets | 3_jambes | prompt_incohérent | traits_flous | Score moyen | Publishable | Verdict mécanique |
|---|---|---|---|---|---|---|---|---|
| Grille imagier annoté | 8 | 0/8=0% | 0/8=0% | 0/8=0% | 0/8=0% | **1.00** | **0/8** | Composition OK *(mécanique)* |
| Imagier différencié 3×3 | 8 | 0/8=0% | 0/8=0% | 0/8=0% | 0/8=0% | 3.38 | 4/8 | Composition OK *(mécanique)* |
| Frise narrative 1×N (pattern X2) | 8 | 0/8=0% | 0/8=0% | 0/8=0% | 0/8=0% | 2.38 | 2/8 | Composition OK *(mécanique)* |
| Multi-sujets via grille (méta-pattern §2) | 10 | 0/10=0% | 0/10=0% | 0/10=0% | 0/10=0% | **1.50** | **1/10** | Composition OK *(mécanique)* |

Tags `image_tags` réellement présents sur ces 4 classes :

| Méta-pattern | Tags v2 effectifs |
|---|---|
| Grille imagier annoté | `image_pas_coherente: 8`, `image_incomprehensible: 8` (chaque image porte les deux) |
| Imagier différencié 3×3 | `image_pas_coherente: 4`, `image_incomprehensible: 4` |
| Frise narrative 1×N | `image_pas_coherente: 5`, `image_incomprehensible: 5`, `image_compo_bonne: 2` |
| Multi-sujets via grille | `image_pas_coherente: 1`, `image_incomprehensible: 1` |

**Avertissement explicite** : la règle skill mécanique conclut "Composition OK" sur les 4 classes parce que les 4 défauts canoniques (anatomie/duplication/prompt/flou) sont par construction inadaptés aux échecs de composition de grille/frise. Le signal humain (score moyen 1.00 sur Grille, 0/8 publishable ; score 1.50 sur Multi-sujets, 1/10 publishable) **contredit frontalement le verdict mécanique**.

Cause : le vocabulaire skill (T2/T3/T4 associés à `prompt_incohérent`) ne capture pas le mode d'échec dominant des grilles/frises ERNIE — qui se manifeste sous les tags `image_pas_coherente` et `image_incomprehensible`, hors mapping. Les rapports antérieurs `2026-05-09_audit-cartographie-templates.md` et `2026-05-09_fix-templates-2objets.md` ne couvrent pas ce sous-pattern.

**>>> Verdict B mécanique (skill literal)** : 4/4 classes "Composition OK".
**>>> Verdict B effectif (signal humain) : NON CONCLUSIBLE par règle automatique. Les 4 méta-patterns présentent un effondrement composition non détectable par les 4 défauts canoniques. Arbitrage architecte requis pour : étendre la liste des défauts canoniques skill aux deux nouveaux tags, ou recalibrer les méta-patterns indépendamment de cette analyse.**

### 4. Verdict C — workflow_classes "OU"

Le brief annonçait 12 classes "OU". L'extraction donne :
- 14 fichiers `index-*_ou_*.json` (les indexes nominalement disjonctifs)
- En filtrant `Variable (solo objet ou frise pour party)` (le "ou" est dans une parenthèse descriptive, pas un OU disjonctif au sens strict) → **13 classes "OU"**
- `Solo personnage ou créature` apparaît côté annotations (via `index-humans.json`) sans son propre index dédié — non comptabilisé strictement
- Ambiguïté de casse sur `Solo humain OU objet` vs `Solo humain ou objet` : un seul index produit les deux variantes — agrégé en une seule classe

Critère par classe : score_moy ≥ 4.0 ET 0 annotation `image_prompt_non_respecte`.

| workflow_class | n | score_moy | n_image_prompt_non_respecte | Verdict |
|---|---|---|---|---|
| Comparatif before/after OU Solo | 10 | 1.00 | 0 | **Incohérent** (score < 4) |
| Humain + entité OU Solo | 9 | 4.22 | 0 | Cohérent |
| Humain + entité OU Solo humain pose statique | 10 | 4.70 | 0 | Cohérent |
| Imagier annoté 3×3 OU Solo visage | 10 | 1.10 | 0 | **Incohérent** (score < 4) |
| Imagier différencié OU Solo | 7 | 1.57 | 1 | **Incohérent** (score < 4 ET n_inc > 0) |
| Scène ou solo personnage | 10 | 4.30 | 0 | Cohérent |
| Solo humain OU objet | 6 | 3.83 | 0 | **Incohérent** (score < 4) |
| Solo objet en vol OU au sol | 9 | 4.56 | 0 | Cohérent |
| Solo objet ou Humain + entité | 8 | 3.00 | 0 | **Incohérent** (score < 4) |
| Solo objet ou comparatif | 8 | 1.00 | 0 | **Incohérent** (score < 4) |
| Solo objet ou humain en scaphandre | 10 | 4.60 | 0 | Cohérent |
| Solo objet ou personnage robot | 8 | 4.88 | 0 | Cohérent |
| Solo objet ou scène | 6 | 3.00 | 0 | **Incohérent** (score < 4) |

**>>> Verdict C : 6/13 cohérentes** (Humain+entité OU Solo, Humain+entité OU Solo humain pose statique, Scène ou solo personnage, Solo objet en vol OU au sol, Solo objet ou humain en scaphandre, Solo objet ou personnage robot).
**7/13 incohérentes** : `Comparatif before/after OU Solo`, `Imagier annoté 3×3 OU Solo visage`, `Imagier différencié OU Solo`, `Solo humain OU objet`, `Solo objet ou Humain + entité`, `Solo objet ou comparatif`, `Solo objet ou scène`.

### 5. Synthèse

| Critère | Verdict mécanique | Confiance |
|---|---|---|
| A | **Fix insuffisant** (6 v2 résiduels sur 13 paires) | Haute — règle stricte appliquée, vocab v2 mappe directement |
| B | "Composition OK" mécanique sur 4/4 classes — **contredit par le signal humain** (Grille score 1.00 / 0% publishable, Multi-sujets 1.50 / 10% publishable) | **Basse** — gap vocab non couvert par skill |
| C | **6/13 cohérentes**, 7 incohérentes | Moyenne — règle stricte mais nombre de classes (13) diffère du brief (12) |

**Exceptions à arbitrer humainement** (5) :
1. **Pattern résiduel A** : sous-classe "Solo animal en mouvement / pose dynamique" (running_cheetah, running_giraffe) et silhouettes à duplication latente (bactrian_camel deux bosses, golden_retriever, mountain_gorilla, playful_dolphin) — décider si NEGATIVE_V3 + `_ISOLATION` doivent être renforcés différemment pour ces tiers, ou si la résolution doit changer (848×1264 ?). Précédents : `docs/reports/2026-05-09_fix-templates-2objets.md`.
2. **Gap vocab skill (B)** : décider si `image_pas_coherente` et `image_incomprehensible` doivent être ajoutés à la table canonique skill (SKILL.md §"Défauts annotés") et au mapping `migrate_benchmark_annotations.py:33`, avec un taux de référence à dériver. Sans ce fix, la règle B est aveugle aux échecs de composition non-anatomiques.
3. **Effondrement Grille imagier annoté + Multi-sujets via grille** : score moyen 1.00 et 1.50, 0/8 et 1/10 publishable. Le signal humain est sans appel ; la règle mécanique skill le manque. Arbitrage : reclasser ces deux méta-patterns en "Composition KO effectif" (override manuel) avant de figer le critère B comme satisfait.
4. **Comptage classes "OU"** : 13 trouvées vs 12 annoncées. Identifier laquelle est en trop ou en moins (peut-être `Solo personnage ou créature` qui vit dans `index-humans.json`, ou exclusion de `Solo objet ou comparatif` traité ailleurs).
5. **`Solo humain OU objet`** : score moyen 3.83 → seuil 4.0 manqué de peu (différence de 1 image annotée +1). Si la classe est statistiquement bordeline, l'archi peut décider de la repasser dans 1-2 itérations plutôt que la trancher maintenant.

### 6. Capitalisation prête à coller (pour validation archi)

**A — Fix insuffisant ⇒ proto T19 non émissible** (le critère n'est pas validé). Si l'archi tranche "fix partiel acceptable" pour les 7 paires éteintes, alors :

```
T19 — Suffixe d'isolement + négatif duplication NEGATIVE_V3 (Solo animal statique)

Hypothèse : Pour les Solo animal en pose statique de profil, ajouter le suffixe
"isolated subject, no other animals or objects nearby" en fin de positif et étendre
le négatif avec "multiple animals, other animals, companion animal, group of animals,
animal in background, second subject, multiple subjects" éteint le défaut 2_objets.

Variable testée : suffixe positif `_ISOLATION` + bloc négatif `NEGATIVE_V3`
(cf. `src/services/prompt_generator.py`).

Défaut ciblé : `2_objets` (= `image_duplication` v2)

Échantillon : 13 paires v1/v2 du rerun seed_offset=100 (poc-scale-benchmark/rerun-2objets.json)
Leaf_ids fixés sans résiduel (7) : chimpanzee, eid_al_adha_sheep, house_painter_with_roller,
labrador_retriever, sheep_with_lamb, snow_leopard, spotted_hyena.

Critère de succès : 0 v2 portant `image_duplication` ; partiel acceptable si ≤ 3.
Résultat observé : 6 v2 résiduels (NON validé strictement).

Précédent : docs/reports/2026-05-09_fix-templates-2objets.md
            docs/reports/2026-05-10_analyse-annotations-poc-scale-benchmark.md
Limite confirmée : technique inefficace sur Solo animal pose dynamique (running_*) et
silhouettes à duplication latente (camel à deux bosses, gorilla, dolphin).
À retravailler — ne pas figer comme T19 dans references/techniques.md tant que
l'archi n'a pas tranché le seuil partiel acceptable.
```

**B — non valide en l'état** (la règle mécanique conclut "OK" mais le signal humain dit "KO"). Si l'archi décide d'ajouter `image_pas_coherente` + `image_incomprehensible` au mapping, recalculer le verdict avant émission de l'entrée MEMORY.

**C — partiel** : 6/13 OU classes validées. Entrée MEMORY proposée si l'archi acte le partiel :

```
## Décisions actées — 2026-05-10

### Cohérence des workflow_classes "OU" (poc-scale-benchmark)

6 classes "OU" sur 13 sont cohérentes (score moyen ≥ 4.0 ET 0 annotation
`image_prompt_non_respecte`) :

- Humain + entité OU Solo (score 4.22, n=9)
- Humain + entité OU Solo humain pose statique (score 4.70, n=10)
- Scène ou solo personnage (score 4.30, n=10)
- Solo objet en vol OU au sol (score 4.56, n=9)
- Solo objet ou humain en scaphandre (score 4.60, n=10)
- Solo objet ou personnage robot (score 4.88, n=8)

7 classes incohérentes à reprompter ou recartographier :
- Comparatif before/after OU Solo (score 1.00, n=10) — patron before/after non maîtrisé
- Imagier annoté 3×3 OU Solo visage (score 1.10, n=10) — voir gap composition (Verdict B)
- Imagier différencié OU Solo (score 1.57, n=7) — idem
- Solo humain OU objet (score 3.83, n=6) — bordeline, repasser à n=10
- Solo objet ou Humain + entité (score 3.00, n=8)
- Solo objet ou comparatif (score 1.00, n=8)
- Solo objet ou scène (score 3.00, n=6) — bordeline

Source : docs/reports/2026-05-10_analyse-annotations-poc-scale-benchmark.md
```

## Points d'attention

- **Gap vocab skill ↔ annotations v2** (priorité haute) : `image_pas_coherente` et `image_incomprehensible` représentent ~25% des tags posés et ne sont mappés vers aucun défaut canonique. Toute règle skill mécanique fondée sur les 4 défauts canoniques en `migrate_benchmark_annotations.py:33` est **structurellement aveugle** aux modes d'échec composition (grille, frise, multi-sujets). Cf. impact direct sur le Verdict B.
- **Comptage classes "OU"** : brief annonce 12, l'analyse en trouve 13 strictes (excl. `Variable (...)` parenthétique). Liste exhaustive normalisée (`all_ou_normalized_seen` dans la sortie structurée du script) : 16 valeurs après normalisation lower+accents — y compris des doublets de casse au sein du même index (ex. `Solo humain OU objet` / `Solo humain ou objet` produits par `index-solo_humain_ou_objet.json`).
- **Sample size** : 4 méta-patterns du Verdict B ont N = 8/8/8/10. Pour des taux de référence à 2-8%, la puissance statistique est faible (p.ex. 8% × 8 = 0.64 défaut attendu). Une vraie évaluation des défauts canoniques sur ces patterns demande N ≥ 25-50 par classe ; or les annotations actuelles n'en fournissent pas.
- **Annotation incomplete v1 côté rerun A** : `bactrian_camel` est marqué `publishable_v1=False, publishable_v2=False`. `golden_retriever`, `mountain_gorilla`, `playful_dolphin`, `running_cheetah`, `running_giraffe` ont `publishable_v2=None` (non statué). Les 6 v2 résiduels n'ont PAS été tranchés sur la publication par l'annotateur — la résolution éditoriale est en attente.
- **49 annotations sans index match** (sur 515) : surtout des images en variantes batch (`*_b1_*`, `*_b2_*`, `*_b3_*`) ou des doublons v2 (`*_v2.png`) absents des 38 indexes — ces 49 entrées n'entrent ni dans Verdict B ni dans Verdict C, mais entrent dans le décompte vocab et dans Verdict A si elles sont dans le rerun.
- **`Variable` workflow_class** (ex. `eid_al_adha_sheep`) : valeur générique posée par l'index générateur de la cartographie, ne correspond à aucun méta-pattern OU et n'est pas comptée dans Verdict B/C. À confirmer si c'est l'intention.

## Décision / Action suivante

Exceptions précises à arbitrer (par priorité) :

1. **[BLOQUANT — gap vocab]** Trancher l'extension du mapping skill pour inclure `image_pas_coherente` et `image_incomprehensible`. Sans cela, le Verdict B reste mécaniquement "OK" mais factuellement KO sur ≥ 2 classes. Action proposée : ajouter 1 ligne au mapping dans `migrate_benchmark_annotations.py:33` (vers un nouveau défaut canonique skill, p.ex. `composition_KO`) + ajouter une ligne au tableau "Défauts annotés" de `SKILL.md` avec un taux de référence à dériver d'un comptage global (130/515 = 25% serait probablement faux par construction — seuil à fixer). Sans le faire, **Verdict B reste non concluable**.
2. **[Décision A]** Acter "Fix partiel acceptable" sur 7/13 ou exiger une vraie itération sur le sous-pattern Solo animal dynamique + silhouettes compactes (6 résiduels). Si "fix partiel" = OK pour l'archi, le proto T19 ci-dessus peut être ajouté à `references/techniques.md` après ajustement du critère.
3. **[Décision C]** Acter "6/13 cohérentes" comme bilan partiel et programmer un nouveau cycle ciblant les 7 incohérentes, ou rejeter le critère et reprompter en bloc. Si bordeline `Solo humain OU objet` (3.83) doit être inclus, redire explicitement le seuil ≥ 3.5 plutôt que ≥ 4.
4. **[Investigation]** Identifier la cause du delta 12 vs 13 OU classes (le brief en annonçait 12).
5. **[Diagnostic]** Si le pattern A est confirmé (dynamique vs statique), prévoir un POC Solo animal dynamique séparé (running_*) avec NEGATIVE_V3 enrichi de `motion blur, dynamic pose duplication, replicated limbs in motion` ou bascule vers résolution portrait 848×1264.
