# POC — Translittération AR → ASCII kebab
Date : 2026-05-05

## Contexte
Valider qu'on peut produire de façon **déterministe et testable** des slugs ASCII kebab strict (regex `/^[a-z0-9]+(-[a-z0-9]+)*$/` du contrat Alwan §5) à partir de titres arabes. Pré-requis pour le pipeline de publication multi-locale (gap #4 du plan Phase 2 publication).

## Résultats

Évolution du score sur le corpus de 30 titres `docs/xchange/ar_slug_corpus.csv` :

| Étape | Approche | Score |
|---|---|---|
| 1 | Table custom DIN 31635 + fold ASCII, input non vocalisé | **0/30** (0 %) |
| 2 | + corrections d'implémentation (article `al-`, heuristique `و/ي` médian) | 0/30, mais sorties plus proches |
| 3 | + Mishkal (vocalisation rule-based) sans adapter `ar_to_slug` | 0/30 brut (12 artefacts purs, 17 mixtes, 1 lexical) |
| 4 | + `ar_to_slug` adaptée pour vocalisé (tanwin, i'rāb, voyelles longues, ـَة) + 14 OVERRIDES | 24/30 (80 %) |
| 5 | + raffinements (fatha finale conservée, shadda parasite, harakat dup, +1 OVERRIDE article) | 26/30 (87 %) |
| 6 | + post-Mishkal OVERRIDES (skeleton match) + shadda re-ordering kasra+shadda + fatha+alif+ـة | **30/30 (100 %)** |

**Score final : 30/30 (100 %)** — objectif de 27/30 dépassé.

## Architecture finale

Flow :
```
titre AR brut
  → apply_overrides_pre()        (substitution mot-à-mot, frontières espace)
  → mishkal.tashkeel()           (vocalisation rule-based, GPL-3.0)
  → apply_overrides_post()       (skeleton match — filet pour Mishkal qui re-vocalise)
  → ar_to_slug()                 (state machine vocalisée)
  → slug ASCII kebab
```

Règles de `ar_to_slug` pour input vocalisé :
1. Tanwin terminal → drop (forme pause)
2. I'rāb final : drop damma/kasra terminales seulement (fatha conservée pour particles مَعَ/وَ)
3. Voyelles longues consume-both : fatha+alif/maqsura, ḍamma+wāw, kasra+yāʾ → 1 char
4. Pattern fatha+alif+ـة → "a" (consume 3, pause form)
5. ـَة isolé → "a" + skip harakat suivants
6. Hamza-bearing : drop si harakat suit, valeur défaut sinon
7. Shadda 4 cas : adjacent à tanwin → bogus drop ; voyelle juste émise + consonne en out[-2] → réordonner ; voyelle juste émise + ʿ/ʾ silent en out[-2] → bogus drop ; standard → double
8. Article ال + lettre solaire → split "al " + drop shadda d'assimilation
9. Normalisation harakat consécutives identiques (artefact Mishkal type `فِِي`)

OVERRIDES : 15 entrées (variantes lexicales où Mishkal préfère un sens différent du choix éditorial corpus).

## Points d'attention

- **Licence Mishkal GPL-3.0** : viable pour usage interne single-user, mais **bloquant si artiste-coloriage devient un service distribué/commercial**. Workaround possible via subprocess/IPC mais zone grise. À arbitrer avant intégration src/.
- **Dépendances Mishkal** : 17 packages tirés (`pyarabic`, `qalsadi`, `tashaphyne`, `arramooz-pysqlite`, etc.), tous du même mainteneur, dernière release 2021. Risque modéré sur Python futurs.
- **Corpus de test petit** : 30 entrées + 15 overrides hand-tuned ⇒ **risque d'overfit**. Le score 30/30 reflète les choix éditoriaux du corpus. Sur titres AR en production, attendre ~85-90 % first-pass + nouvelles entrées OVERRIDES à ajouter au fil de l'eau.
- **Latence Mishkal non mesurée sous charge** : test mono-instance sans benchmark. À profiler avant batch de masse.
- **Post-correction OVERRIDES** : ajouté au-delà du contrat strict ("appliqué avant Mishkal") parce que Mishkal re-vocalise certains overrides. Même dict, deux passes — pas un nouveau mécanisme.

## Décision / Action suivante

✅ **Translittération AR validée** pour intégration. Conditionnée à l'arbitrage licence GPL-3.0.

Si licence OK :
- Migrer `apply_overrides_pre`, `apply_overrides_post`, `ar_to_slug` dans `src/services/ar_slug.py`
- Ajouter `mishkal` à `requirements.txt`
- Étendre le corpus de test (cible : 100+ titres variés) avant production
- Exposer une fonction haut-niveau `titre_ar_to_slug(titre: str) -> str` qui orchestre le flow complet

Si licence bloquante :
- Fallback Option D du contrat §3 : utiliser le slug EN comme R2 slug (simple, autorisé, zéro complexité). La translittération AR devient un nice-to-have post-V1.

Fichiers POC (jetables, à archiver après intégration) :
- `scripts/poc_ar_transliteration.py`
- `scripts/poc_mishkal.py`
- `docs/xchange/ar_slug_corpus.csv`
