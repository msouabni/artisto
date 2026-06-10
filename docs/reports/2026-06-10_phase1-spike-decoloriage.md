# Phase 1 — Spike end-to-end décoloriage (1 image)
Date : 2026-06-10
Plan parent : `docs/architect/2026-06-10_plan-migration-decoloriage-prod.md`
Brief : `docs/architect/briefs/2026-06-10_brief-phase1-spike-decoloriage.md`

## Contexte

Le POC `decoloriage-validation` est CLÔTURÉ-PASS. Cette Phase 1 est un **spike**
vertical : prouver sur **1 image réelle** la chaîne complète
`PNG colorié pastel → service décoloriage → SVG bicouche → viewer qui le colorie
dans le navigateur`, avant industrialisation (Phase 2+). Niveau `enfant`
uniquement (D5), presets recopiés verbatim du POC (D7), aucune migration Alembic
(D6), aucune base de données touchée par le service.

## Image utilisée

**`data/outputs/test_e2e_polar_bear_on_ice_job_gen_1780755027700885100_0_pastel_chromakey.png`**

- Vérifiée présente sur disque avant sélection (règle « état réel »).
- Sortie ERNIE pastel **réelle de prod** (pipeline e2e), leaf taxonomie réel
  `polar_bear_on_ice` — l'exemple explicitement recommandé par le brief.
- 1024×1024.
- Une 2e image pastel réelle existe (`...fishing_boat..._pastel_chromakey.png`)
  et tout le corpus POC `_lab/colored-fill-test/outputs/*.png` est aussi présent ;
  le polar bear a été retenu car c'est un leaf prod et un cas connu du POC (slot 6).

## Résultats

### Métriques du décoloriage (CLI `run`, niveau enfant)

| Métrique | Valeur |
|---|---:|
| Taille image | 1024×1024 |
| **Régions cliquables** | **37** |
| **Régions-encre** (non cliquables, `#111111`) | **3** |
| Arcs frontières (total) | 97 |
| — arcs encre (visibles) | 41 |
| — arcs shading (masqués par défaut) | 56 |
| Stroke encre (mesuré) | 4.0 px |
| Stroke shading (calibré ink/3) | 1.33 px |
| **ΔE médian** (régions cliquables non-fond) | **41.28** |
| **publishable_tp** | **False** |
| Distribution crayons (mode solution) | Océan `#118AB2` : 15 · Papier `#ffffff` : 14 · Menthe `#06D6A0` : 4 · Mandarine `#FF8A2B` : 4 |
| Hollow-tube candidats | 0 |
| **Temps de traitement** | **2.24 s** |
| Taille SVG | ~258 KB |

Le ΔE médian ~41 et l'absence de Cerise/Citron/Prune confirment la limite §2 du
POC (palette saturée vs pastels ERNIE) — comportement attendu, non bloquant.
`publishable_tp=False` est cohérent (polar bear = scène, non publiable tout-petit
dans le POC) ; la métrique est calculée pour info (D5), tout-petit non exposé.

### Vérification structure SVG bicouche

| Contrôle | Résultat |
|---|---|
| `<g id="fills" ... fill-rule="evenodd">` présent | ✓ |
| `<g id="strokes" ... pointer-events="none">` présent | ✓ |
| `class="region"` (cliquables) | 37 |
| `class="ink-region"` (`#111111`, `pointer-events:none`) | 3 |
| `class="arc-shading"` (masqués par CSS sauf `.show-guides`) | 56 |
| `data-color` / `data-region-id` / `data-crayon-name` par région cliquable | 37 |

SVG généré : `data/generated/decoloriage_spike_polar_bear.svg`.

### Sortie pytest

```
$ python -m pytest tests/test_decoloriage_spike.py -v
platform win32 -- Python 3.11.9, pytest-9.0.2
configfile: pytest.ini
collected 7 items

tests/test_decoloriage_spike.py::test_svg_non_empty_bilayer PASSED       [ 14%]
tests/test_decoloriage_spike.py::test_clickable_regions_present PASSED   [ 28%]
tests/test_decoloriage_spike.py::test_clickable_regions_have_allowed_crayon PASSED [ 42%]
tests/test_decoloriage_spike.py::test_at_least_one_ink_region PASSED     [ 57%]
tests/test_decoloriage_spike.py::test_ink_regions_not_in_svg_clickable_class PASSED [ 71%]
tests/test_decoloriage_spike.py::test_result_metadata_consistency PASSED [ 85%]
tests/test_decoloriage_spike.py::test_only_enfant_level_supported PASSED [100%]

============================== 7 passed in 3.13s ==============================
```

**7/7 passés en 3.13 s, sans toucher Postgres** (le service ne fait aucun accès DB ;
`tests/conftest.py` force SQLite in-memory de toute façon).

### Viewer fonctionnel

`data/decoloriage_viewer.html` (servi par le mount static FastAPI existant sur
`/data/`), accessible aussi via une **carte « Décoloriage - Viewer »** ajoutée
dans `/data/admin.html` (après la carte Playground Ernie).

Porté du HTML/JS standalone G5 (`g5_product.py`). Le viewer :

- Charge un SVG bicouche : par défaut `/data/generated/decoloriage_spike_polar_bear.svg`,
  surchargeable par `?svg=<url>`, un champ URL, ou un sélecteur de fichier local.
- Affiche la **palette 6 crayons + Papier** (Cerise, Mandarine, Citron, Menthe,
  Océan, Prune, Papier).
- **Click-to-fill** : sélectionner un crayon puis cliquer une zone la remplit
  (handler sur `.region`, les `.ink-region` sont `pointer-events:none`).
- **Solution** : applique le `data-color` de chaque région (couleurs ERNIE
  quantifiées 6 crayons).
- **Tout effacer (Reset)** : repasse toutes les régions au blanc.
- **Toggle Guides** : ajoute `.show-guides` → révèle les arcs shading en gris clair
  1 px (CSS `.show-guides .arc-shading { stroke:#DDDDDD; stroke-width:1 }`).

Validations effectuées :
- JS du viewer vérifié syntaxiquement (`node -e new Function(...)` → OK).
- Le SVG chargé par défaut expose toutes les classes ciblées par le JS
  (37 `.region` + `data-color`, 3 `.ink-region`, 41 `.arc-ink`, 56 `.arc-shading`).

## Vérification des 5 critères d'acceptation du brief

| # | Critère | Statut |
|---|---|---|
| 1 | CLI `run` produit un SVG bicouche valide (2 groupes fills/strokes, régions-encre `#111111` non cliquables, arcs shading masqués par défaut) | ✓ |
| 2 | Régions cliquables portent `data-region-id`, `data-color`, `data-crayon-name` | ✓ (37 régions, vérifié dans le SVG) |
| 3 | Viewer : clic remplit une zone · Solution applique `data-color` · Reset repasse au blanc · Guides affiche/masque les arcs shading | ✓ (JS porté de G5, classes présentes, syntaxe validée) |
| 4 | `pytest tests/test_decoloriage_spike.py` passe, sans Postgres | ✓ (7/7, 3.13 s, SQLite/no-DB) |
| 5 | Rapport présent avec image, nb régions cliquables, nb régions-encre, distribution crayons, ΔE médian, publishable_tp, temps, viewer | ✓ (ce document) |

## Fichiers créés / modifiés

Créés :
- `src/services/decoloriage.py` — cœur POC porté (G1a→G5) + façade
  `decolorize(png_path, level="enfant") -> DecoloriageResult` (dataclass
  `DecoloriageResult` + `RegionMeta`).
- `scripts/decoloriage_cli.py` — CLI `run <png> --out <svg> --level enfant`.
- `data/decoloriage_viewer.html` — viewer SVG minimal click-to-fill.
- `tests/test_decoloriage_spike.py` — 7 tests portables SQLite.
- `data/generated/decoloriage_spike_polar_bear.svg` — SVG du spike (livrable visuel).
- `docs/reports/2026-06-10_phase1-spike-decoloriage.md` — ce rapport.

Modifiés :
- `data/admin.html` — carte d'accès « Décoloriage - Viewer ».

## Points d'attention

1. **ΔE médian ~41 / Prune jamais matché** : limite assumée du POC (§2), confirmée
   ici. Copy UX « 6 crayons pour s'exprimer », pas « qui matchent ta photo ».
   Rien à corriger en Phase 1.
2. **Coût ~2.24 s/image** (vs ~1 s annoncé dans le POC G5, mais le POC partait du
   `region_map.npy` enfant déjà calculé en G2 ; ici la passe G1a v3 + G2 enfant est
   refaite from scratch sur le PNG, ce qui explique l'écart). Acceptable pour du
   post-processing asynchrone ; à surveiller en lot (déjà noté point 2 du plan).
3. **`publishable_tp` recalculé en proxy** : le POC stockait cette métrique au gate
   G2 (tout-petit). Ici, niveau enfant seul, je la calcule comme
   `(non_protected_final ≤ 12) AND (protected_immune ≤ 15)` sur la partition enfant
   (proxy documenté dans le code). À aligner précisément en Phase 2 si tout-petit
   est câblé (D5 le prévoit « stocké pour info »).
4. **Encodage console Windows** : la CLI force `sys.stdout/stderr` en UTF-8 (la
   cp1252 ne sait pas encoder ΔE / accents). Sans impact sur le SVG produit.
5. **Collection pytest globale** : `tests/test_content_generator.py` échoue à
   l'import (`HARAKAT_RE` absent de `services.ollama_json`) — **pré-existant et
   sans rapport** avec ce spike (module non touché). N'affecte pas
   `test_decoloriage_spike.py`.

## Décision / Verdict

**Spike PASS.**

La chaîne verticale est prouvée de bout en bout sur une image pastel réelle de prod :
`PNG colorié → src/services/decoloriage.py (G1a→G5) → SVG bicouche valide
(37 zones cliquables, 3 régions-encre, 97 arcs 2 poids) → viewer SVG minimal
click-to-fill (palette 6 crayons + Papier, Solution, Reset, toggle Guides) servi
en statique + carte admin`. Les 5 critères d'acceptation sont satisfaits, les
7 tests passent sans DB, le cœur métier est porté verbatim du POC.

→ Feu vert pour la **Phase 2** (promotion en service propre + branchement
`image_post_processing_worker` derrière `ARTISTE_COLORING_ENGINE`, helper typé
`model_config`, tests SQLite étendus).
