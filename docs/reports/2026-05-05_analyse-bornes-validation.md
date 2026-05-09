# Analyse — Bornes de validation : HARD caps Zod plateforme vs SOFT caps éditoriaux pipeline
Date : 2026-05-05

## Contexte
Clarification reçue d'Alwan Books le 2026-05-05 : les hard caps Zod côté plateforme sont uniformes pour toutes les locales (EN / FR / AR). Les bornes que nos POC et notre `validate-regen` loop manipulaient (40-60 / 80-130 pour EN/FR, 25-55 / 40-100 pour AR) sont des **sweet spots éditoriaux internes**, pas des contraintes plateforme. Le présent rapport documente cette distinction pour qu'aucune itération future ne les confonde.

## Résultats

### Hypothèse initiale (avant clarification)
Les POC `ar-content-quality`, `ar-anchored-content`, `ar-content-prompts-v2` et `llm-benchmark*` ont mesuré le respect de bornes en partant du principe que :
- les bornes EN/FR (40-60 / 80-130) étaient quelque chose de proche du contrat plateforme,
- les bornes AR (25-55 / 40-100) étaient une recalibration *à valider côté plateforme*.

Conséquence : les rapports parlaient parfois de "bornes Zod" ou "bornes contrat" en visant ces valeurs, ce qui était imprécis.

### Ce que la plateforme a confirmé (réponse 2026-05-05, ADR §1.13)
Les HARD caps Zod plateforme **sont uniformes toutes locales** :

| Champ | HARD cap Zod plateforme |
|---|---|
| `title` | [5, 100] |
| `title_card` | [5, 40] |
| `description` | [20, 200] |

→ Tout `title` entre 5 et 100 caractères passera le build Astro, en EN, FR ou AR.

### Nos SOFT caps éditoriaux internes (inchangés, mais clarifiés comme "soft")
Les valeurs que le pipeline Python utilise pour son `validate-regen` loop :

| Champ | SOFT cap pipeline EN/FR | SOFT cap pipeline AR |
|---|---|---|
| `title` | [40, 60] | [25, 55] |
| `title_card` | (cible ≤ 30) | ≤ 25 |
| `description` | [80, 130] | [40, 100] |

Ces bornes correspondent à nos cibles qualité (titre lisible, description suffisamment riche, AR plus court car densité lexicale ~50 % inférieure à EN/FR).

### Tableau récapitulatif

| Champ | HARD Zod (plateforme) | SOFT EN/FR (pipeline) | SOFT AR (pipeline) |
|---|---|---|---|
| `title` | **[5, 100]** | [40, 60] | [25, 55] |
| `title_card` | **[5, 40]** | ≤ 30 | ≤ 25 |
| `description` | **[20, 200]** | [80, 130] | [40, 100] |

Les SOFT caps sont strictement inclus dans les HARD caps : tout contenu accepté par notre pipeline est publiable côté plateforme.

## Points d'attention

- **Le validate-regen loop rejette sur les SOFT caps, jamais sur les HARD caps.** Le build Astro côté Alwan ne cassera jamais sur nos longueurs AR — les SOFT sont une gate qualité interne, distincte de la contrainte plateforme.
- **Pourquoi garder les SOFT caps AR plus stricts** : densité lexicale AR ~50 % inférieure à EN/FR. Un title AR de 100 chars (HARD max) contiendrait ~2× plus de mots qu'un title EN de 100 chars — pas le format qu'on veut côté UX. Garder [25, 55] AR aligne le **nombre de mots affichés** entre locales.
- **Les SOFT caps sont calibrables** au fil du temps (ex. POC-LLM-v2 a montré que gemma4:26b atteint [25, 55] AR à 10/10, qwen3:8b à 8/10 ; on peut élargir si on veut tolérer plus de variance). Les HARD caps sont contractuels et ne se renégocient pas sans nouvelle ronde avec la plateforme.
- **Risques identifiés mais non bloquants** :
  - Les rapports antérieurs de POC parlent de "bornes Zod" en visant les SOFT caps. Inexact mais sans impact pratique : aucun code n'a été basé sur l'hypothèse fausse (les SOFT sont strictement plus stricts que les HARD).
  - Le contrat `docs/xchange/PIPELINE-CONTRACT.md` §4 mentionne déjà les bornes Zod réelles (cf. tableau "Schéma Post — frontmatter complet") — ce rapport documente que les SOFT pipeline en sont distincts.

## Décision / Action suivante

✅ **Pas de changement de comportement code à faire**. Les SOFT caps actuels du `validate-regen` (Python) restent en place, sont *strictement plus stricts* que les HARD caps Zod plateforme, donc le contenu validé en interne passe sans difficulté côté Astro.

✅ **Documentation mise à jour** :
- `docs/workflow-pipeline.md` Phase 3 ⑥b et Points d'attention §7 — distinction HARD vs SOFT explicite, lien vers ce rapport.
- `CLAUDE.md` — nouvelle section "Validation de contenu" avec le tableau et la règle d'implémentation.

⚠ **Convention pour les futurs POC et rapports** : ne jamais parler de "bornes Zod" en référence aux sweet spots pipeline. Toujours préciser **HARD plateforme** (uniforme, contractuelle) ou **SOFT éditoriale** (par locale, pipeline interne).

🔁 **Recalibration future possible** : si POC-LLM-v2 ou un POC ultérieur montre que la regen loop rejette plus de 30 % du contenu sur les SOFT AR, élargir [25, 55] vers [25, 65] par exemple. Ce sera une décision interne, pas une question plateforme.

## Annexes

- Source contractuelle plateforme : `docs/xchange/PIPELINE-CONTRACT.md` §4 (Schéma Post)
- Source ADR plateforme : ADR §1.13 (référencée dans `PIPELINE-CONTRACT.md`)
- POC ayant utilisé les SOFT caps : `2026-05-05_poc-ar-anchored-content`, `2026-05-05_poc-ar-content-prompts-v2`, `2026-05-05_poc-llm-benchmark`, `2026-05-05_poc-llm-benchmark-v2`
- Doc workflow mise à jour : `docs/workflow-pipeline.md`
- Doc mémoire projet mise à jour : `CLAUDE.md` (nouvelle section "Validation de contenu")
