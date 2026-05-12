# Transfert T5 + T6 + T7 — strip noms couleur / ancres conceptuelles / surfaces 3D (prophylactique)

## Contexte

L'analyse `docs/reports/2026-05-10_analyse-annotations-transferts-skill.md` §3 #10 identifie un transfert **prophylactique** : aucun filtre `strip_color_nouns` / `strip_glossy_terms` / `replace_color_anchors` n'existe en pre-processing du `name_en` ou de la description.

Volume bas dans le corpus actuel (`image_gris_residuel` = 1 occurrence — `jaguar_in_jungle`), mais :

- Le critère prod CLAUDE.md exige `cr < 0.001` sur la majorité des sujets.
- Le QC histogram Pillow est en amont de l'annotation, donc certains défauts couleur ont déjà été filtrés avant que les humains annotent.
- Le schéma v2 ne porte pas la dimension couleur résiduelle hors `image_gris_residuel`.

Règles skill (`references/techniques.md`) :

- **T5** : strip noms de couleur explicites (`red`, `blue`, `golden`, `silver`, etc.).
- **T6** : strip ancres conceptuelles colorées (`rainbow`, `sunset`, `autumn`, `tropical`, `fire`, `flame`).
- **Extension T6** : strip / remplacer surfaces réfléchissantes (`shiny`, `glossy`, `metallic`, `chrome`, `glass`, `wet`, `chocolate`).
- **T7** : strip termes 3D involontaires (`shaded`, `volumetric`, `realistic textures`).

## Objectif

Transférer T5 + T6 + T7 sous forme de filtres pre-processing centralisés, appliqués au `name_en` et à toute description avant injection dans les templates.

## Périmètre

**Créer** :

- `src/services/prompt_filters.py` (nouveau module) :
  - `_COLOR_NOUNS = {"red", "blue", ...}` (vocabulaire skill T5).
  - `_COLOR_ANCHORS = {"rainbow", "sunset", "autumn", "tropical", "fire", "flame"}` (vocabulaire skill T6).
  - `_GLOSSY_TERMS = {"shiny", "glossy", "metallic", "chrome", "glass", "wet", "chocolate"}` (extension T6).
  - `_3D_TERMS = {"shaded", "volumetric", "realistic textures", "depth shading"}` (vocabulaire skill T7).
  - Fonction `strip_color_nouns(text: str) -> str`.
  - Fonction `replace_color_anchors(text: str) -> str` (remplacer par terme générique : `rainbow` → `colorful arc`, etc. — voir skill pour mappings).
  - Fonction `strip_glossy_terms(text: str) -> str`.
  - Fonction `strip_3d_terms(text: str) -> str`.
  - Fonction `apply_all_filters(text: str) -> str` qui chaîne les 4.
- `tests/test_prompt_filters.py` (nouveau fichier) :
  - Tests unitaires pour chaque filtre (input → output attendu).
  - Test composition `apply_all_filters`.
  - Test non-régression : texte neutre (sans terme ciblé) inchangé.

**Modifier** :

- `src/services/prompt_generator.py` :
  - Importer `apply_all_filters`.
  - Appliquer aux entrées texte (`name_en`, `description` si présente) avant injection dans les templates.
  - Préserver les `LEAF_OVERRIDES` et `anatomical_overrides` (pas de filtre sur les overrides — ils sont écrits par humain validés).
- Tests `tests/test_prompt_generator.py` :
  - Test : leaf avec `red apple` dans `name_en` → positive ne contient pas « red ».
  - Test : leaf avec `rainbow` → positive ne contient pas « rainbow » mais le terme générique.
  - Test : leaf avec `shiny metal` → positive ne contient ni « shiny » ni « metal » (ou substitut).
  - Test non-régression : leafs sans terme filtré inchangés.

## Critères d'acceptation

- Module `prompt_filters.py` créé avec 4 filtres + composition.
- Vocabulaires conformes au skill (à citer en commentaire).
- Filtres appliqués en pre-processing dans `PromptGenerator`.
- Tests pytest verts (existants + nouveaux).
- `LEAF_OVERRIDES` non filtrés (test explicite).

**Mesure post-transfert (optionnelle, faible volume corpus)** : rerun sur `jaguar_in_jungle` + 5-10 leafs avec couleur/surface dans le nom (seed offset +900). Vérifier `cr < 0.001`. Volume corpus actuel ne permet pas mesure significative — c'est un transfert prophylactique.

## Reporting

`docs/reports/2026-05-10_transfert-skill-T5-T6-T7-couleur-surfaces.md`.

## Hors scope

- Refonte de `NEGATIVE_V3` (déjà couverte dans briefs précédents).
- Filtre AR (harakat, longueur) — mécanique distincte couverte dans `services/ollama_json.py`.

## Estimation

~45-60 min dev + tests + rapport.
