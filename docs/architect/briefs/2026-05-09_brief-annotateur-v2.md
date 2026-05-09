# Brief — Annotateur v2 (P1 + P2 + P3 consolidés)

Date : 2026-05-09
Auteur : architecte / PMO
Destinataire : claude-code dev

## Objectif

Refondre `data/benchmark-annotator.html` (et endpoints `/api/benchmark/*` quand nécessaire) pour livrer **rapidement** une version **utilisable pour l'annotation des POC en cours** (~470 images annotées, plus à venir).

Trois axes consolidés dans un seul livrable :

- **P1** — Affichage compact et ergonomique
- **P2** — Raccourcis clavier
- **P3** — Grille d'évaluation structurée alignée sur le modèle pipeline

Hors scope ici : intégration prod (greffon DB) — voir brief séparé `2026-05-09_brief-greffon-prod.md`.

## Fichiers concernés

- `data/benchmark-annotator.html` (front, ~767 lignes — refonte structurelle)
- `src/api/routes/benchmark.py` (back, ~530 lignes — endpoints + écriture `annotations.json` au nouveau schéma)
- `tests/test_benchmark_routes.py` (à mettre à jour pour le nouveau schéma)
- `scripts/migrate_benchmark_annotations.py` (à créer — script de migration des `annotations.json` existants)

## Contraintes (CLAUDE.md)

- **Tests SQLite-portables** : le storage benchmark est sur fichier (`data/<dir>/annotations.json`), pas DB → pas d'enjeu Postgres ici. Les tests doivent rester verts.
- **Multi-schéma index** : 3 schémas supportés actuellement (`subjects`, `results` keyed par leaf_id, `results` legacy). **Ne pas casser** — les 11 tests de `test_benchmark_routes.py` doivent rester verts (ou être adaptés en gardant la couverture des 3 schémas).
- **Pas de migration Alembic** dans ce brief — seulement script de migration JSON sur fichiers.

## P1 — Affichage compact et ergonomique

### Pain points (cf. cadrage)

1. Layout 2-col fixe `1fr / 380px`, header non-sticky → on perd la nav au scroll
2. Trop d'éléments au-dessus de l'image (filename + tags + image + titre + ℹ + meta-badges + tier) → dispersion visuelle
3. Image cap 800×800 sans zoom
4. Side-pane charge cognitive élevée
5. Responsive sous 1100px = scroll long
6. Progression peu visible (barre 4px)
7. Filename brut redondant avec les tags décomposés

### Cibles

- **Header sticky** : titre + dir + reload + thème + counter + nav prev/next/non-annotée + save status, toujours visibles au scroll.
- **Image en focus** : taille moyenne par défaut (~600px max), **clic = lightbox plein écran** (échap pour fermer).
- **Score row déplacé sous l'image** (pas dans la side-pane), atteignable sans scroll.
- **Bouton "Copier prompt" + "Copier négatif"** visibles à côté du titre ou dans le tooltip ℹ. Utiliser l'API Clipboard (`navigator.clipboard.writeText`).
- **Détails métadonnées** (filename, tags décomposés, prompt-info, badges) regroupés dans un **accordéon "▾ Détails"** sous l'image, replié par défaut.
- **Side-pane plus dense** : padding réduit, défauts en grille 2-col, score 1-6 en barre horizontale unique.
- **Auto-suggestion des dirs** : ajouter `GET /api/benchmark/dirs` qui liste les sous-dossiers de `data/` contenant des PNG, retourner triés par mtime desc. Front : datalist HTML5 ou autocomplete simple sur le `dir-input`.
- **Progress enrichie** : "X annotés / Y total · Z restants" sous la barre.
- **Responsive** : breakpoint abaissé à 960px ; en dessous, side-pane sticky-bottom (pas en colonne défilante).

### Wireframe cible

```
┌─ HEADER STICKY ──────────────────────────────────────────────┐
│ 📋 Annotator · dir [autocomplete] [Charger] · counter · ‹ › │
│ ⏭ · save status · 🌙                                          │
├──────────────────────────────────────────────────────────────┤
│             [tags concept/sampler/cfg…]                       │
│             ┌───────────────────────┐    ┌──────────────┐    │
│             │      IMAGE            │    │  side-pane   │    │
│             │  (~600px)             │    │  (grille P3) │    │
│             │  click → lightbox     │    │              │    │
│             └───────────────────────┘    │              │    │
│             [ 1 2 3 4 5 6 ]   ← score    │              │    │
│             ▾ Détails                    │              │    │
│               filename · tags · prompt-info              │    │
│               [📋 Copier prompt] [📋 Copier négatif]    │    │
│             X annotés / Y · Z restants  [progress]       │    │
└──────────────────────────────────────────────────────────────┘
```

### Critères d'acceptation P1

- [ ] Header reste visible au scroll
- [ ] Sur 1920×1080 zoom 100%, image + score + grille visibles **sans scroll**
- [ ] Détails repliables, accessibles ≤ 1 clic
- [ ] Lightbox image fonctionnelle (entrée par clic image ou raccourci `Z`, sortie par échap ou clic dehors)
- [ ] Boutons "Copier prompt" + "Copier négatif" fonctionnels
- [ ] Auto-suggestion dirs opérationnelle (endpoint `/api/benchmark/dirs` à ajouter)
- [ ] Responsive utilisable en fenêtre 960px (~50% écran 1920)
- [ ] Aucune régression sur multi-schéma `subjects`/`results`/`results-legacy`
- [ ] Thème dark/light toujours cohérent

## P2 — Raccourcis clavier

### Bindings cibles

```
─── Navigation ────────────────────────────────
←  / →            : prev / next
Shift + ←  / →    : prev/next non-annotée
U                 : non-annotée suivante (legacy)
Home / End        : première / dernière

─── Score ─────────────────────────────────────
1-6               : score = 1-6
(7-9, 0)          : libres, pas de binding par défaut

─── Image ─────────────────────────────────────
Z                 : toggle lightbox zoom
Échap             : fermer lightbox
C                 : copier prompt
Shift+C           : copier négatif

─── Annotation rapide (chord-style) ───────────
D puis 1-9        : toggle défaut/tag IMAGE n° N (chord)
T puis 1-8        : toggle tag PROMPT n° N (chord)
M                 : toggle flag pattern
S                 : toggle flag sample (échantillon)
P                 : toggle publishable (legacy)

─── Aide ──────────────────────────────────────
?                 : ouvre cheat-sheet modale
```

### Règles focus

- Ne pas intercepter quand le focus est sur `INPUT`, `TEXTAREA`, ou `[contenteditable="true"]`
- Indicateur visuel de focus sur les pills/scores (outline 2px primary color)
- Le chord (`D`, `T`) : appuyer la lettre dans une fenêtre de 1500ms → afficher un overlay "D-mode active, press 1-9", le chiffre suivant déclenche le toggle, échap annule

### Cheat-sheet modale (`?`)

HTML simple, fond semi-transparent, table des bindings groupés par section. Fermable par échap ou clic hors modale.

### Critères d'acceptation P2

- [ ] Cheat-sheet `?` fonctionnelle
- [ ] Tous les bindings actifs sans conflit input
- [ ] Indicateur focus visible
- [ ] Rétro-compat : `←` `→` `1-6` `0` `P` `U` continuent de fonctionner
- [ ] Chords `D` et `T` opérationnels avec overlay et timeout
- [ ] Aide pied-de-page mise à jour ou supprimée au profit de `?`

## P3 — Grille d'évaluation structurée

### Schéma de tags

#### Axe IMAGE (17 tags, polarité visuelle)

| Polarité | Clé | Label |
|---|---|---|
| 🟢 POS | `image_compo_bonne` | Bonne composition |
| 🟢 POS | `image_coherente` | Cohérente |
| 🟢 POS | `image_creative` | Créative |
| ⚪ NEUT | `image_complexe` | Complexe |
| 🔴 NEG | `image_compo_mauvaise` | Mauvaise composition |
| 🔴 NEG | `image_pas_coherente` | Pas cohérente |
| 🔴 NEG | `image_simpliste` | Trop simpliste |
| 🔴 NEG | `image_incomprehensible` | Incompréhensible |
| 🔴 NEG | `image_traces_couleur` | Traces de couleur |
| 🔴 NEG | `image_gris_residuel` | Gris résiduel (ombres / shading) |
| 🔴 NEG | `image_symetrie_incomplete` | Symétrie incomplète |
| 🔴 NEG | `image_duplication` | Duplication |
| 🔴 NEG | `image_flou` | Flou |
| 🔴 NEG | `image_anatomie_pb` | Problème anatomie |
| 🔴 NEG | `image_physique_pb` | Pb physique / disposition |
| 🔴 NEG | `image_traits_pb` | Pb traits (doubles / discontinus / incomplets) |
| 🔴 NEG | `image_hors_sujet` | Hors sujet |
| 🔴 NEG | `image_prompt_non_respecte` | Prompt non respecté |

#### Axe PROMPT (8 tags)

| Polarité | Clé | Label |
|---|---|---|
| 🟢 POS | `prompt_interessant` | Intéressant |
| 🟢 POS | `prompt_creatif` | Créatif |
| ⚪ NEUT | `prompt_complexe` | Complexe |
| 🔴 NEG | `prompt_ambigu` | Ambigu |
| 🔴 NEG | `prompt_approximatif` | Approximatif |
| 🔴 NEG | `prompt_vide` | Vide |
| 🔴 NEG | `prompt_creux` | Creux |
| 🔴 NEG | `prompt_ennuyeux` | Ennuyeux |

#### Axe CUSTOM (libre, persistant)

- Champ texte d'ajout libre + datalist auto-complete dérivée des `custom_tags` déjà utilisés (toutes images, tous dirs)
- Endpoint suggéré : `GET /api/benchmark/custom-tags` qui agrège l'union des `custom_tags` connus
- Suppression : croix sur la pill custom (comportement existant à conserver)

#### Flags (booléens hors axes)

| Clé | Label | Sémantique |
|---|---|---|
| `flag_pattern` | 🔍 Pattern à analyser | Marquer pour revue collective |
| `flag_pattern_note` | _texte libre_ | Apparaît sous le flag dès qu'il est coché ; champ multiline 2-3 lignes max |
| `flag_sample` | 📌 Échantillon | Image retenue pour set de référence |
| `publishable` | ✅ Publiable | Conservé de l'existant |

### Score 1-6 (au lieu de 1-10)

UI : 6 boutons au lieu de 10. Raccourcis 1-6.

### Schéma JSON cible (annotation par image)

```json
{
  "score": 4,
  "score_legacy": 7,
  "image_tags": ["image_compo_bonne", "image_anatomie_pb"],
  "prompt_tags": ["prompt_complexe", "prompt_creatif"],
  "custom_tags": ["sujet_iconique", "ramadan_set"],
  "flags": {
    "pattern": true,
    "pattern_note": "Symétrie systémique sur Solo bird flying",
    "sample": false,
    "publishable": false
  },
  "updated_at": "2026-05-09T14:32:11+00:00"
}
```

### Migration des annotations existantes

Script : `scripts/migrate_benchmark_annotations.py`

```python
"""
Usage:
  python scripts/migrate_benchmark_annotations.py [--dry-run] [--dir <dir>]

- Parcourt tous les sous-dossiers de data/ contenant un annotations.json (ou un dir spécifique)
- Backup chaque fichier en .bak avant écriture
- Convertit selon table de mapping ci-dessous
- Produit un rapport docs/reports/2026-05-XX_migration-annotateur-grille-v2.md
- --dry-run par défaut : aucune écriture, juste un diff résumé
"""
```

#### Table de mapping (auto)

| Ancien `defects[*]` | Nouveau `image_tags[*]` |
|---|---|
| `3_jambes` | `image_anatomie_pb` |
| `2_objets` | `image_duplication` |
| `couleurs_résiduelles` | `image_traces_couleur` |
| `traits_flous` | `image_flou` |
| `traits_doubles` | `image_traits_pb` |
| `traits_discontinus` | `image_traits_pb` |
| `perspective_KO` | `image_physique_pb` |
| `gris_résiduel` | `image_gris_residuel` |
| `prompt_incohérent` | `image_prompt_non_respecte` |

| Ancien `notes[*]` (JSON pill) | Nouveau cible |
|---|---|
| `prompt_trop_vague` | `prompt_tags: ["prompt_ambigu"]` |
| `prompt_trop_complexe` | `prompt_tags: ["prompt_complexe"]` |
| `sujet_hors_catégorie` | `image_tags: ["image_hors_sujet"]` |
| `sujet_tronqué` | `image_tags: ["image_compo_mauvaise"]` |
| `composition_déséquilibrée` | `image_tags: ["image_compo_mauvaise"]` |
| `trop_chargé` | `image_tags: ["image_complexe"]` |
| `couleurs_persistantes` | `image_tags: ["image_traces_couleur"]` |
| `traits_incomplets` | `image_tags: ["image_traits_pb"]` |
| `concept_difficile` | `prompt_tags: ["prompt_complexe"]` |

#### Mapping `score` 1-10 → 1-6

```
mapping = {1:1, 2:1, 3:2, 4:2, 5:3, 6:4, 7:4, 8:5, 9:5, 10:6}
new_score = mapping[old_score]
score_legacy = old_score   # conservé en parallèle
```

#### Mapping `publishable`

`publishable: true/false` → `flags.publishable: true/false`

### Endpoints back à modifier

- `POST /api/benchmark/annotate` : accepter le nouveau payload (champs ci-dessus). **Validation** côté API : refuser tags inconnus (sauf `custom_tags` libres), score hors plage [1,6], etc.
- `GET /api/benchmark/images` : retourner l'annotation au nouveau format (lecture transparente — si annotations.json déjà migré → format v2 ; sinon → format legacy v1, le front gère les deux).
- `GET /api/benchmark/dirs` : **NOUVEAU** — liste les sous-dossiers contenant des PNG.
- `GET /api/benchmark/custom-tags` : **NOUVEAU** — union des `custom_tags` connus.

### UI side-pane cible

```
┌─ SIDE PANE ─────────────────┐
│ ━━ IMAGE ━━━━━━━━━━━━━━━━━ │
│ 🟢 POS                      │
│   [Bonne compo] [Cohér.]   │
│   [Créative]                │
│ ⚪ NEUT                     │
│   [Complexe]                │
│ 🔴 NEG                      │
│   [Mauv compo] [Pas coh.]  │
│   [Simpliste] [Incompr.]   │
│   [Couleurs] [Gris ombres] │
│   [Sym. inc.] [Duplication]│
│   [Flou] [Anatomie]         │
│   [Pb physique] [Pb traits]│
│   [Hors sujet] [Prompt KO] │
│                             │
│ ━━ PROMPT ━━━━━━━━━━━━━━━━ │
│ 🟢 [Intéressant] [Créatif] │
│ ⚪ [Complexe]               │
│ 🔴 [Ambigu] [Approx.]      │
│   [Vide] [Creux] [Ennuyeux]│
│                             │
│ ━━ CUSTOM ━━━━━━━━━━━━━━━━ │
│ [+ ajouter… ▾ datalist]    │
│ [sujet_iconique ×]         │
│                             │
│ ━━ FLAGS ━━━━━━━━━━━━━━━━━ │
│ [ ] 🔍 Pattern             │
│   ┌─ note (visible si ☑) ──┐│
│   │ texte libre…           ││
│   └────────────────────────┘│
│ [ ] 📌 Échantillon         │
│ [ ] ✅ Publiable           │
└─────────────────────────────┘
```

### Critères d'acceptation P3

- [ ] Schéma JSON v2 implémenté en lecture/écriture
- [ ] 3 axes (Image / Prompt / Custom) + flags rendus dans le side-pane
- [ ] Score 1-6, raccourcis 1-6 OK, `score_legacy` persisté
- [ ] `pattern_note` sauvegardé/restauré
- [ ] Auto-complete custom tags fonctionnel (datalist)
- [ ] Indication visuelle polarité (groupes POS/NEUT/NEG par axe)
- [ ] Script `migrate_benchmark_annotations.py` :
  - [ ] Mode `--dry-run` par défaut
  - [ ] Backup `.bak` avant écriture
  - [ ] Rapport `docs/reports/2026-05-XX_migration-annotateur-grille-v2.md` (nb fichiers, nb annotations migrées, conflits)
- [ ] 100 % des annotations existantes migrées sans perte
- [ ] Tests `test_benchmark_routes.py` adaptés et verts (multi-schéma toujours couvert)

## Estimation dev

| Bloc | Estimation |
|---|---|
| Refonte UI complète (P1 + P2 + P3) | ~3.5h |
| Endpoints back (annotate v2, dirs, custom-tags) | ~1h |
| Script migration + dry-run + rapport | ~1h |
| Adaptation tests | ~30 min |
| Validation manuelle + screenshots | ~30 min |
| **Total** | **~6.5h** |

## Livrable de fin de chantier

- Le code livré
- Rapport `docs/reports/2026-05-XX_phase-annotateur-v2.md` (ce qui a changé, fichiers touchés, screenshots before/after, résultats migration)
- Mise à jour `docs/use-cases/use_cases.yaml` si un use case correspond
- Pas de doc CLAUDE.md modifiée (pas d'évolution de convention projet)

## Points d'attention

- Le storage benchmark **reste sur fichier** (`data/<dir>/annotations.json`), aucune modif DB ici.
- Le front doit gérer **lecture rétro-compat** : si `annotations.json` est encore au schéma v1 (script de migration pas encore passé sur ce dir), afficher l'ancien format en mode dégradé sans perte de données. Dès qu'une annotation est sauvegardée, elle passe au schéma v2.
- Les **chords clavier** sont une nouveauté UX, prévoir un overlay visuel pour signaler le mode chord actif.
- **Ne pas casser** les 11 tests existants de `test_benchmark_routes.py`. S'ils ne couvrent pas le nouveau schéma, les compléter.
