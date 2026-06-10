# Phase — Split hétérogène floodfill + palette spread-LAB
Date : 2026-06-01

## Contexte

Suite à l'analyse `2026-06-01_diagnostic-flat-cartoon-bleu-mange-trait.md`, identification d'un second problème sur l'image `ernie_turbo_q8_01328_.png` : 2 composantes massives (140k et 94k pixels) contenaient 4 couleurs distinctes chacune (ΔE inter-cluster jusqu'à 168). Cause : `cv2.connectedComponentsWithStats` détermine la connectivité spatialement, indépendamment de la couleur. Si le trait noir entre régions est discontinu, des régions chromatiquement distinctes fusionnent en une seule composante.

Discussion utilisateur : l'idée de **distribuer la palette en LAB** (couleurs maximalement éloignées) pour faciliter la détection chromatique post-fusion. Décision : combiner palette spread-LAB côté prompt + split k-means LAB par composante côté pipeline.

## Modifications appliquées

### 1. Palette spread-LAB (côté prompt — `flat_cartoon`)

Calibration validée par calcul ΔE :

| Couleur | Hex | RGB | Luma |
|---|---|---|---:|
| vivid red | `#E63946` | (230,57,70) | 110 |
| bright orange | `#F18F01` | (241,143,1) | 156 |
| sunny yellow | `#FFE03A` | (255,224,58) | 214 |
| cyan | `#00B4D8` | (0,180,216) | 130 |
| bright sapphire blue | `#3A86FF` | (58,134,255) | 125 |
| vibrant magenta | `#D946EF` | (217,70,239) | 133 |

**ΔE minimum entre paires : 60** (bleu ↔ magenta). Toutes paires > 50.  
**Luma minimum : 110** (rouge). Toutes > 90 = compat Otsu OR.

Modif `src/services/prompt_generator.py` — `STYLE_CONFIGS["flat_cartoon"]["positive_suffix"]` :

```
high-contrast 6-color palette (vivid red, bright orange, sunny yellow, cyan,
bright sapphire blue, vibrant magenta), no two adjacent regions sharing
similar colors, every region including the outer silhouette bordered by
crisp pure black outlines (#000000), ...
```

### 2. Split hétérogène par composante (côté pipeline)

**Nouveau helper** : `_split_heterogeneous_component` dans `src/services/extract_palette.py`.

**Algorithme** :
1. Pour chaque composante connexe issue de `connectedComponentsWithStats`
2. Calculer norm L2 de `pixels_LAB.std(axis=0)` (mesure d'hétérogénéité)
3. Si > `floodfill_split_std_threshold` (default 25), k-means LAB k=`floodfill_split_k` (default 4)
4. Pour chaque cluster k-means, re-appliquer `connectedComponents` (cas îles disjointes)
5. Garder les sous-régions ≥ `floodfill_split_min_subcluster_pct` × area mère (default 5 %)
6. Split validé seulement si ≥ 2 sous-régions résultantes (sinon revert au comportement normal)

**Nouveaux paramètres** dans `ExtractPaletteParams` :

| Paramètre | Default | Rôle |
|---|---:|---|
| `floodfill_split_heterogeneous` | `False` | Active la passe (opt-in, rétrocompat préset prod) |
| `floodfill_split_std_threshold` | `25.0` | Seuil norme L2 std LAB pour déclencher split |
| `floodfill_split_k` | `4` | Nombre de clusters k-means par composante |
| `floodfill_split_min_subcluster_pct` | `0.05` | Filtre sous-clusters < 5 % de la composante mère |

**Activé dans** : `PRESETS["floodfill_chromakey_v1"]` uniquement.

## Validation

### Test sur `ernie_turbo_q8_01328_.png` (image diagnostique)

| Métrique | Sans split | Avec split |
|---|---:|---:|
| Régions au final | 17 | 26 (+9) |
| Composantes std_LAB > 25 (top 10) | 3 / 10 | 2 / 10 |
| Composante #2 (140k px, std 78) | Conservée fusionnée | Splittée en 6 sous-régions (lavande/orange/jaune/rouge/cyan/...) |
| Composante #3 (94k px, std 61) | Conservée fusionnée | Splittée en sous-régions cohérentes |
| Composante #1 (fond green, 648k px, std 78) | Conservée | Conservée (heuristique : fond, splitter casse le lock_bg) |

Note : les 2 composantes résiduelles std_LAB > 25 sont l'orange (26.2) et le cyan (36.5) — résultats du split mais marginalement au-dessus du seuil. Peuvent être splittées plus finement en augmentant k ou abaissant le seuil, mais le rendu actuel est déjà cohérent.

### Tests automatiques

- 28 tests pastel + routes : ✅ passants
- Préset prod pastel (`iso_trait_v3_anomaly_split`) : `floodfill_split_heterogeneous = False` (inchangé)
- Mécanisme cousin existant (`anomaly_detection_enabled = True`) intact

## Points d'attention

- **Coût de calcul** : k-means k=4 par composante hétérogène + connectedComponents sur 4 sous-masques. Estimation : +30-50 % sur le temps d'extraction pour images avec beaucoup de fusion. Acceptable pour exploration playground, à benchmarker en prod.
- **Fond hétérogène conservé** : le fond chromakey green (variation interne ERNIE) reste classé comme une composante avec std élevé. C'est intentionnel car `lock_bg` (UX coloriage) attend une composante unique. Pour éviter qu'il soit splitté, on pourrait ajouter un filtre `min_area_for_split_consideration` mais pas critique actuellement.
- **Si trait totalement absent** entre régions : k-means k=4 fait au mieux mais peut sous-segmenter une zone à 5-6 sous-couleurs. Augmenter `floodfill_split_k` à 6-8 ou rendre k automatique (silhouette score) si nécessaire.

## Décision / Action suivante

- ✅ Palette spread-LAB intégrée
- ✅ Split hétérogène implémenté et activé sur préset chromakey
- ✅ Tests rétrocompat passants
- 🔍 Test utilisateur : régénérer `ernie_turbo_q8_01328_*` avec nouveau prompt flat_cartoon (palette spread) puis lancer 🟢 Chromakey (split actif)
- 🔍 Si le résultat est production-ready, capitaliser comme nouveau préset `floodfill_chromakey_v2_split` ou conserver v1 (à décider)
- 🤔 Question ouverte : faut-il appliquer split au préset prod pastel ? Cousin = `anomaly_detection` qui traite déjà les anomalies majeures (composante > 30 % canvas). Le split serait complémentaire (fusion interne < 30 %) mais nécessite calibration des seuils.
