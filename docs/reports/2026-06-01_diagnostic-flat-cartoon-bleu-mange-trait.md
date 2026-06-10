# Analyse — flat_cartoon : couleurs vives sombres mangées par le masque trait
Date : 2026-06-01

## Contexte

Lors d'un test du pipeline `floodfill_chromakey_v1` sur une génération flat_cartoon (image `ernie_turbo_q8_01323_.png`, fireplace), constat utilisateur : la silhouette tracée en bleu vif `#0252FF` apparaît noire dans le rendu final, et les régions bleues attendues sont absentes.

## Reconstitution du pipeline

Diagnostic offline sur l'image (1024×1024, 1 048 576 pixels) :

| Métrique | Valeur |
|---|---:|
| Pixels chromakey green | **0.00 %** (image générée sans chromakey) |
| Pixels masque trait | 22.12 % |
| Pixels bleu vif #0252FF (distance Euclid < 30) | 5.52 % (~58 000 px) |
| **Pixels bleus dans le masque trait** | **100 %** |
| Pixels bleus dans la palette LAB du sujet | 0 % |
| Régions détectées par floodfill | 21 (aucune bleue) |

Le bleu vif a été classé trait par la branche **Otsu OR** du détecteur de masque ink (`_detect_ink_mask`) :

| Pixel | Luma | HSV V | HSV S | Verdict |
|---|---:|---:|---:|---|
| `#0252FF` royal blue | 78 | 255 | 99 % | Échappe HSV strict mais **luma < seuil Otsu (90)** → capturé |
| `#000000` trait noir vrai | 0 | 0 | 0 % | Capturé HSV strict |

## Cause root identifiée

Deux problèmes superposés que la session précédente avait confondus :

1. **Image hors-périmètre du preset** : `floodfill_chromakey_v1` suppose chromakey green > 30 %. Ici 0 % → pipeline en mode dégradé sans signal d'erreur.
2. **Otsu OR mange les couleurs vives sombres** : tout pixel avec luma < 90 est classé trait, indépendamment de sa saturation. Affecte structurellement les couleurs flat_cartoon de palette par défaut.

### Échec de la tentative de fix par filtre saturation

Une première tentative (session précédente) avait proposé d'exiger `S < 60` sur la branche Otsu pour préserver les couleurs saturées. Échec : l'**anti-aliasing du trait noir contre une région saturée** a paradoxalement saturation HAUTE (mélange noir + couleur vive). Le filtre rejette les deux populations indistinctement → trait discontinu → régions macro fusionnées.

Leçon enregistrée en mémoire : avant de proposer un filtre colorimétrique global, identifier le pixel adverse et vérifier qu'il n'a pas la même signature. Si oui → basculer sur critère spatial (connectivité), pas colorimétrique.

## Décision : modifier le prompt flat_cartoon

Choix retenu : agir côté **prompt** plutôt que pipeline. Le prompt flat_cartoon citait littéralement des couleurs avec luma < 90 :

| Couleur citée (avant) | Luma | Action |
|---|---:|---|
| bright red (255,0,0) | 76 | → `coral red` (luma ~167) |
| royal blue (2,82,255) | 78 | → `sky blue` (luma ~195) |
| purple (128,0,128) | 52 | → `lavender` (luma ~153) |
| grass green | — | retiré (collision avec chromakey green) |
| sunny yellow, vivid orange, hot pink, turquoise | > 140 | conservées |

## Modifications appliquées (durables)

`src/services/prompt_generator.py` — `STYLE_CONFIGS["flat_cartoon"]` :

1. **Header** : `"bold flat cartoon children's illustration on pure cinema chromakey green background (#00B140)"`
2. **Positive suffix** : palette restreinte aux couleurs luma > 90 + `every region including the outer silhouette bordered by crisp pure black outlines (#000000)` + `no green tint anywhere in the subject`
3. **Negative add** : ajout `colored outlines, blue outlines, dark navy contours, contours in subject colors, royal blue, bright red, dark red, deep purple, navy, maroon, any color darker than middle gray, green in the subject`

## Validation

- 28 tests pastel + routes : ✅ passants
- Prompt généré contrôlé visuellement (header + suffix + negative cohérents)
- Effet attendu sur ERNIE :
  - Toutes les régions générées seront luma > 90 → aucune ne sera confondue avec trait
  - Chromakey green forcé → chromakey_mask ~30 %+ → pipeline floodfill_chromakey_v1 retrouve son fonctionnement nominal
  - Outlines pure black explicites + interdits colorés → silhouette restera noire

## Points d'attention

- **Cette modification rend flat_cartoon "chromakey-compatible" mais perd la palette "pure saturated dark" initiale** (bright red, royal blue, purple). Si volonté de retrouver ces couleurs intenses, créer un style séparé (ex: `flat_cartoon_intense`) et l'utiliser sans pipeline chromakey.
- Le problème générique "Otsu OR mange luma < seuil" reste présent pour les autres styles si l'utilisateur génère hors prompt. La solution pipeline reste l'option B (géodésique) si on veut couvrir ce cas génériquement.
- Les images flat_cartoon déjà générées avec l'ancien prompt restent affectées. Régénération nécessaire.

## Décision / Action suivante

- ✅ Modification flat_cartoon appliquée et validée
- 🔍 Test utilisateur : régénérer la même `ernie_turbo_q8_01323_*` avec le nouveau prompt et lancer 🟢 Chromakey
- 🤔 À discuter ensuite : faut-il aussi appliquer la même prudence (palette luma > 90 ou pure neutre) sur les autres styles à risque (`crayon` notamment qui peut citer des couleurs sombres) ?
