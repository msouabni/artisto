# Brief — Vocabulaires annotateur : source unique back

Date : 2026-05-09
Auteur : architecte / PMO
Destinataire : claude-code dev
Prérequis : Annotateur v2 livré (commits `164c02c` + `ca7118f`), schéma annotation v2 figé.

## Objectif

Éliminer la duplication des **vocabulaires de tags** entre back (`src/api/routes/benchmark.py` — `IMAGE_TAGS_VOCAB`, `PROMPT_TAGS_VOCAB`) et front (`data/benchmark-annotator.html` — `IMAGE_AXIS`, `PROMPT_AXIS`).

Aujourd'hui : **2 sources de vérité** ; si on ajoute un tag, il faut modifier les deux. Le test `test_vocabularies_match_brief_count` garde les **comptes** (18 / 8) mais pas les **valeurs**, ce qui peut masquer une dérive.

Cible : **back source unique + front qui découvre les vocabulaires au démarrage** via un endpoint de découverte. Modifier un tag = modifier **un seul endroit**.

## Contexte technique

### Existant côté back (`src/api/routes/benchmark.py`)

```python
IMAGE_TAGS_VOCAB: set[str] = {
    "image_compo_bonne", "image_coherente", "image_creative",
    "image_complexe",
    "image_compo_mauvaise", "image_pas_coherente", "image_simpliste",
    "image_incomprehensible", "image_traces_couleur", "image_gris_residuel",
    "image_symetrie_incomplete", "image_duplication", "image_flou",
    "image_anatomie_pb", "image_physique_pb", "image_traits_pb",
    "image_hors_sujet", "image_prompt_non_respecte",
}  # 18 clés

PROMPT_TAGS_VOCAB: set[str] = {
    "prompt_interessant", "prompt_creatif",
    "prompt_complexe",
    "prompt_ambigu", "prompt_approximatif", "prompt_vide",
    "prompt_creux", "prompt_ennuyeux",
}  # 8 clés
```

→ Ce sont des `set[str]` (clés seules) utilisés pour la **validation** des payloads `POST /api/benchmark/annotate`.

### Existant côté front (`data/benchmark-annotator.html`)

Le front a besoin de **plus** que les clés pour rendre l'UI :
- **clé** (ex `image_compo_bonne`)
- **label** affichable (ex "Bonne composition")
- **polarité** (`pos` / `neut` / `neg`) → couleur du pill
- **axe** (`image` / `prompt`)
- **numéro chord** (1-9 pour image_tags via `D`, 1-8 pour prompt_tags via `T`) — utilisé par le système de raccourcis P2

Aujourd'hui ces métadonnées sont **codées en dur** dans le HTML (constantes JS `IMAGE_AXIS` et `PROMPT_AXIS`). Le back n'a **que** les clés.

### Problème

Si on ajoute le tag `image_aberration` côté back uniquement, le front ne le rend pas (pas de label/polarité/numéro). Le test compte (18) le détecte, mais aucun test ne vérifie que **la clé est connue côté front**.

Si on ajoute le tag côté front uniquement, le back rejette en 400 sur `POST /annotate` les payloads qui le contiennent.

## Cible

### 1. Source unique côté back — enrichie (clé + label + polarité + numéro chord)

Refonte de `IMAGE_TAGS_VOCAB` / `PROMPT_TAGS_VOCAB` en **listes ordonnées** de dicts (pour préserver l'ordre d'affichage et la numérotation chord) :

```python
# src/api/routes/benchmark.py (ou nouveau src/api/benchmark_vocab.py)

IMAGE_AXIS: list[dict] = [
    {"key": "image_compo_bonne", "label": "Bonne composition", "polarity": "pos"},
    {"key": "image_coherente",   "label": "Cohérente",         "polarity": "pos"},
    # ... 18 entrées dans l'ordre d'affichage et de numérotation chord (1-9 pour les 9 premiers, 0 pour le 10ᵉ — à confirmer avec l'existant front)
]

PROMPT_AXIS: list[dict] = [
    {"key": "prompt_interessant", "label": "Intéressant", "polarity": "pos"},
    # ... 8 entrées
]

# Sets dérivés (pour la validation rapide, conservés pour rétrocompat interne)
IMAGE_TAGS_VOCAB: set[str] = {t["key"] for t in IMAGE_AXIS}
PROMPT_TAGS_VOCAB: set[str] = {t["key"] for t in PROMPT_AXIS}
```

**Important** : récupérer les valeurs `label` et `polarity` exactes depuis l'actuel HTML pour éviter toute dérive cosmétique. La numérotation chord se déduit de l'ordre dans la liste.

### 2. Endpoint de découverte

```
GET /api/benchmark/vocabularies

Response 200 application/json:
{
  "image_axis":  [{"key":"image_compo_bonne","label":"Bonne composition","polarity":"pos"}, ...],
  "prompt_axis": [{"key":"prompt_interessant","label":"Intéressant","polarity":"pos"}, ...],
  "score_range": {"min": 1, "max": 6},
  "schema_version": 2
}
```

→ Pas de query params. Endpoint stable, idempotent, cacheable côté front (1 fetch au boot, en mémoire pour la durée de la session).

### 3. Front consume au boot

`data/benchmark-annotator.html` :
- **Supprimer** les constantes `IMAGE_AXIS` / `PROMPT_AXIS` codées en dur.
- Au boot, **fetch** `/api/benchmark/vocabularies`, stocker en variable globale.
- Construire le rendu (pills, polarité, chord number) à partir du résultat fetch.
- Si fetch échoue : fallback minimal qui montre une erreur visible ("Vocabulaires inaccessibles — recharger la page") — ne pas planter silencieusement.

## Critères d'acceptation

- [ ] Une seule source : `IMAGE_AXIS` / `PROMPT_AXIS` côté back (en `list[dict]`), avec les clés `key`/`label`/`polarity`. Les labels et polarités sont **identiques** aux valeurs actuelles du front (pas de dérive cosmétique).
- [ ] `IMAGE_TAGS_VOCAB` / `PROMPT_TAGS_VOCAB` deviennent des **dérivés** des listes (set comprehension). Validation `POST /annotate` continue de fonctionner exactement comme avant.
- [ ] `GET /api/benchmark/vocabularies` retourne le payload spécifié, schema_version=2.
- [ ] Front fetch + consume au boot ; aucune constante de tag codée en dur ne reste dans le HTML.
- [ ] Numérotation chord (raccourcis `D`+chiffre, `T`+chiffre) reste cohérente avec l'ordre des listes back.
- [ ] Test ajouté : `test_vocabularies_endpoint_returns_axes` (présence des 18+8 entrées, structure `key/label/polarity`, schema_version=2).
- [ ] Test mis à jour : `test_vocabularies_match_brief_count` → garder l'esprit (compte 18/8) mais sourcer désormais sur les `IMAGE_AXIS`/`PROMPT_AXIS` (set dérivés OK).
- [ ] Aucun autre test cassé (24/24 verts dans `tests/test_benchmark_routes.py`).
- [ ] Validation manuelle : ouvrir l'annotateur sur 1 dir, vérifier que les pills, leurs couleurs, et les chords clavier fonctionnent identiquement.

## Hors-scope

- Pas de modification du **schéma JSON v2** des annotations (clés inchangées).
- Pas d'ajout/retrait de tags — c'est une refonte structurelle "à iso-fonctionnalité".
- Pas de localisation des labels (FR uniquement comme aujourd'hui).
- Pas d'extension polymorphe à d'autres domaines (taxonomy_tags, etc.) — voir greffon prod.

## Fichiers concernés

- `src/api/routes/benchmark.py` (modif — refonte vocab + ajout route `/vocabularies`)
- `data/benchmark-annotator.html` (modif — suppression constantes JS, fetch + consume)
- `tests/test_benchmark_routes.py` (modif — adaptation test compte + nouveau test endpoint)
- (option) Extraction dans `src/api/benchmark_vocab.py` si la lisibilité y gagne — laisser au jugement dev.

## Estimation dev

- Refonte vocab côté back + endpoint : ~30 min
- Refonte fetch+render côté front : ~20 min
- Tests + validation : ~15 min
- **Total ~1h**

## Livrable

- Code livré
- Rapport `docs/reports/2026-05-XX_phase-vocabulaires-source-unique.md` (avant/après, screenshots si possible)
- Maj `docs/architect/MEMORY.md` : retirer la dette "Vocabulaires annotateur dupliqués back/front" de la table dette technique connue
- Maj `docs/use-cases/use_cases.yaml` : entrée `BENCHMARK_ANNOTATOR_V2` enrichie de `src/api/benchmark_vocab.py` si le fichier est créé

## Points d'attention

- **Ne pas casser** les chord raccourcis P2 — l'ordre des entrées dans la liste back **est** la numérotation chord côté front. Toute permutation de l'ordre = changement de l'expérience utilisateur. Préserver l'ordre actuel à l'identique sur cette refonte.
- **Validation côté back conservée stricte** : tags inconnus → 400. Comportement identique pour les anciens et nouveaux clients.
- **Cache front** : le fetch ne se fait **qu'au boot** ; pas de polling. Si on veut hot-reload des vocabulaires, c'est un cycle ultérieur.
