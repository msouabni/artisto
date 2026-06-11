# POC 2 décoloriage-styles — Log d'exploration
Statut : **EXPLORATION — capitalisée T20 (2026-06-12)**, pas encore figée prod. Mis à jour : 2026-06-12

## Progression

| Étape | Quoi | Verdict |
|---|---|---|
| S0 | Corpus croisé 3 sujets × 4 styles (manga, réaliste, peinture, 3D), prompts stylistiques sans flat colors | PASS (corpus gelé) |
| S1 | Baseline POC 1 inchangé sur les 12 | Diagnostic : manga ≈ OK, réaliste/peinture/3D dégradés (fragmentation k-means + pas d'encre native) |
| S2 (spike) | SAM 2 (manga) + informative-drawings contour (3D) | Les 2 outils marchent (SAM 2 : peacock 641→49 ; infodraw contour : vrai line-art sur 3D) |
| **Pivot** | Abandon de l'adaptation des styles durs → **styles coloriables par construction** | Décision utilisateur 2026-06-11 |
| S0-adapted | 4 styles adaptés : low_poly, stained_glass, papercut, kawaii_bold | low-poly + kawaii prometteurs ; stained_glass trop fragmenté (1288 régions) ; papercut borderline |
| v2 | Fix fusion sujet↔fond (fond chromakey) + trait kawaii fin | Museau préservé 6/6 ; trait kawaii 8,8→2,0 px |
| v3 | Fidélité : partition **adulte** (max détail) + couleurs **fidèles** (hex ERNIE) + low-poly **sans noir** (guides gris) + zooms | Convergé vers cible adulte/fidélité |

## Les 2 pistes prometteuses (recette gagnante)

**Recette commune** : prompt avec **fond chromakey vert** (« on a solid chroma key green background ») → séparation chromakey ΔE=40 → fond=Papier, sujet préservé (museau OK) ; partition **adulte** (rm_v3 brut, max détail) ; mode couleur **fidèle** (`data-color` = hex moyen d'origine, pas mapping 6 crayons) ; pipeline g3/g4/g5 POC 1 réutilisé par import.

1. **low_poly** (« origami / triangles », réf Adobe utilisateur)
   - Prompt : `low poly geometric art of <sujet>, triangulated polygonal facets, flat shaded triangles, sharp clean edges, many small triangular facets, highly detailed, intricate, on a solid chroma key green background`
   - Trait : **gris #999 1px** (PAS de noir — facettes en guides légers). `n_ink_regions=0`.
   - Détail : 280–639 régions adulte. Cible adulte.
   - Réserve : `low_poly_dog` artefact gen « 2 têtes » → re-gen seed.

2. **kawaii_bold** (coloriage cartoon)
   - Prompt : `cute kawaii cartoon of <sujet>, fine thin clean black outlines, flat color fills, simple clean shapes, highly detailed, on a solid chroma key green background` (négatif : thick heavy outlines)
   - Trait : **noir fin #15151B 2px** (outline du style conservé).
   - Couleurs solution : fidèles aux tons ERNIE.
   - Réserve : `kawaii_peacock` très encré (centres de plumes noirs natifs) → re-gen ou accepter.

## Styles écartés / en attente
- **manga / réaliste / peinture / 3D** : baseline POC 1 insuffisant ; nécessitent S2 (SAM 2 + traits appris). Non poursuivis (le pivot styles-adaptés est plus rentable). Outils S2 validés et disponibles si on y revient.
- **stained_glass** : encre native mais explose en régions (1288) + blank trop noir. Récupérable via re-gen sujet isolé chromakey + grandes vitres, ou SAM 2. **Backlog.**
- **papercut** : ombres portées douces = maillon faible. À retester en recette v3 si besoin.

## Capitalisation (à figer SEULEMENT après validation catalogue)
- Par style validé → T20+ dans `references/techniques.md` (prompt chromakey + recette pipeline).
- Décision catalogue Alwan → MEMORY (quels styles entrent, lesquels exclus).
- Statut actuel : **pistes en exploration, pas encore figées.**

## Livrables techniques
- Corpus + sorties : `poc/decoloriage_styles/` (corpus*.json, s1_out/, s2_out/, s3_out/, s3_out_v2/, s3_out_v3/)
- Scripts (import-only POC 1) : generate_s0/s0_adapted/v2/v3, s1_baseline, s2a_sam2, s2b_infodraw, s3_endtoend(_v2/_v3), make_*_gallery.
- HTML interactifs v3 : `s3_out_v3/{low_poly,kawaii_bold}_dog.html`.

## Pistes de génération à explorer (brainstorm 2026-06-11)
Voir la proposition envoyée à l'utilisateur (mosaïque, mandala/zentangle, art nouveau, géométrique islamique/zellige, pop art, art déco, papercut-v3…). Cible adulte → privilégier les styles ornementaux riches à zones franches.

## Suite 2026-06-12 — sujets natifs + lineart-fill + architecture 2-modes (capitalisé T20)

### Pivot « sujet natif »
Forcer la taxonomie (dog/castle/peacock) sur les styles ornementaux = parachuté. Génération par **sujets natifs** au style (zellige → étoiles/médaillons ; mandala → floral/géom/lotus ; zentangle → hibou/plume/papillon ; mosaïque → poisson/oiseau/médaillon), en **line-art N&B**. Résultat : 12/12 pages adulte propres, **zéro explosion** (vs ~1500 régions en forcé). cf. `native_batch/`, mémoire `feedback_styles_ornementaux_sujet_natif`.

### Découverte architecturale — 2 modes
Le pipeline décoloriage (k-means sur couleur) est le **mauvais outil sur du line-art N&B** (il trace la structure au lieu d'isoler les cellules). D'où **2 modes** :
- **décoloriage** (T19) : image colorée → régions + encre. → pastel, kawaii, low-poly colorés.
- **lineart-fill** (T20) : line-art N&B → composantes connexes du blanc. → mandala/zentangle/zellige/mosaïque + tout line-art (dont lineart d'origine).

### lineart-fill production (`lineart_fill_v2.py`)
2 défauts production corrigés (retours humains) :
- **Halo blanc autour des traits** → expansion Voronoi des cellules sous le trait → couverture canvas 79 %→**100 %**, zéro halo.
- **Traits non lisses** (encre raster) → vectorisation VTracer (`services.vectorizer`) → traits lisses, SVG 100 % vectoriel (~773 Ko ; option raster ~392 Ko).
Preuve : `fill_v3/<id>_demo_filled.png` + `<id>_zoom.png` (AVANT/APRÈS). Cellules indépendantes, médiane ~480, couverture 100 %.

### Pistes catalogue (cible adulte, validées en exploration)
- **mandala, zentangle, zellige, mosaïque** (line-art natif + lineart-fill). zellige = différenciant marque Alwan ; mandala = standard marché adulte.
- low_poly + kawaii (mode décoloriage, fond chromakey, couleurs fidèles) — v3 validé visuellement.
- Réserves : artefacts gen ponctuels (re-gen seed) ; SVG lourds à optimiser.

### Backlog prod (= T20 §Backlog dans references/techniques.md)
c1 intégrer lineart-fill comme 3e moteur worker · c2 alléger encre · c3 appliquer aux lineart d'origine · c4 re-gen artefacts · c5 stained_glass/mosaïque colorée via chromakey/SAM 2 · c6 figer variantes prod + décision catalogue.
