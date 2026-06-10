"""Service prod : decompose un PNG colorie en palette + zones colorees + trait noir.

Promu depuis ``_lab/extract-palette/extract.py`` le 2026-05-31 apres
validation production sur 47 PNG ERNIE pastel + 3 leafs taxonomie reels.

PRESET PROD = ``PROD_PRESET`` (alias de ``iso_trait_v3_anomaly_split``).

Pipeline :
    PNG colorié (sortie ERNIE pastel)
        -> detection trait noir V3 (HSV + Otsu plafonne + dilate + close)
        -> detection regions (k-means BGR, n_colors=12) sur image lissee
        -> isolation background classique + DETECTION ANOMALIE auto-correctif
           (composantes > 30 % du canvas -> re-k-means k=2 LAB local + split
           si delta-E > 10 et un seul touche le bord)
        -> merge_small_regions (< 400 px fusionnees dans voisin majoritaire)
        -> expand_to_ink (Voronoi vers le trait)
        -> vectorisation trait via VTracer bw_polygon
        -> composition SVG (background + paths colorés + ink overlay)

API publique :
    >>> from services.extract_palette import extract_palette, make_params, render_svg
    >>> params = make_params("iso_trait_v3_anomaly_split")
    >>> result = extract_palette(png_path, params)
    >>> svg = render_svg(result, mode="full")

Voir aussi :
    - ``_lab/extract-palette/CAPITALISATION.md`` : historique evolution presets
    - ``_lab/POC_METHODOLOGY.md`` : methodologie POC suivie
"""
from __future__ import annotations

import argparse
import base64
import html
import json
import re
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np
from scipy.ndimage import distance_transform_edt
from skimage.morphology import skeletonize as _skimage_skeletonize


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))
import vtracer  # noqa: E402

COLORED_FILL_DIR = PROJECT_ROOT / "_lab" / "colored-fill-test" / "outputs"

# On cible les variantes "good" + D (Eric Carle) pour le bench.
BENCH_CASES = [
    "C_named.png",
    "E_vector.png",
    "F_pastel.png",
    "D_carle.png",
    "B_16primary.png",
]


# === Presets nommes (capitalisation des paliers de parametrage) ==============
# A NE PAS MUTER : chaque preset est fige. Les ajouts/iterations creent un
# NOUVEAU preset, pas une modification des existants. Le bench-presets permet
# de comparer toutes les versions cote-a-cote sur les memes images.
#
# Historique des versions :
#   v1 (2026-05-30) : HSV strict seul. Trait fin, mais discontinuites sur les
#                     frontieres couleur (anti-aliasing manque). reg_cov ~88-91%.
#   v3 (2026-05-30) : HSV + Otsu plafonne (90) + dilate 1 + close 3. Trait
#                     continu, regions strictes au contour. reg_cov ~82-87%.
#                     Halo blanc visible en mode "regions only".
#   v4 (2026-05-30) : v3 + expansion Voronoi vers le trait. Plus de halo.
#                     reg_cov ~89-95%. La vue regions-only est magnifique
#                     mais l'expansion peut creer des artefacts sur certaines
#                     images.
def _params(**overrides) -> "ExtractPaletteParams":
    return ExtractPaletteParams(**overrides)


PRESETS: dict[str, dict] = {
    # v1 baseline : HSV strict, sans Otsu, sans dilate, sans expand.
    # Trait fin mais discontinuites possibles ; regions precises au pixel pres.
    "strict_v1": dict(
        use_otsu_grayscale=False,
        ink_dilate=0,
        close_radius=2,
        expand_to_ink=False,
    ),
    # v1 + stroke meme couleur 2 px : comble les halos blancs en mode
    # "regions only" sans toucher a la segmentation. Visuellement les regions
    # "remontent" au trait, geometrieinchangee. Tres leger en SVG (2 attrs en plus).
    "strict_v1_stroked_2px": dict(
        use_otsu_grayscale=False,
        ink_dilate=0,
        close_radius=2,
        expand_to_ink=False,
        region_stroke_width=2,
    ),
    "strict_v1_stroked_3px": dict(
        use_otsu_grayscale=False,
        ink_dilate=0,
        close_radius=2,
        expand_to_ink=False,
        region_stroke_width=3,
    ),
    # v1 + pre-simplification couleurs (avant k-means).
    # Le but : moins de regions, plus pertinentes semantiquement.
    "strict_v1_median7": dict(
        use_otsu_grayscale=False,
        ink_dilate=0,
        close_radius=2,
        expand_to_ink=False,
        simplify_method="median",
        simplify_strength=3,  # -> ksize = 7
    ),
    "strict_v1_bilateral": dict(
        use_otsu_grayscale=False,
        ink_dilate=0,
        close_radius=2,
        expand_to_ink=False,
        simplify_method="bilateral",
        simplify_strength=2,  # 2 passes
    ),
    "strict_v1_meanshift": dict(
        use_otsu_grayscale=False,
        ink_dilate=0,
        close_radius=2,
        expand_to_ink=False,
        simplify_method="mean_shift",
        simplify_strength=1,
    ),
    # Mean-shift renforce : plus aplati, plus lent.
    "strict_v1_meanshift_strong": dict(
        use_otsu_grayscale=False,
        ink_dilate=0,
        close_radius=2,
        expand_to_ink=False,
        simplify_method="mean_shift",
        simplify_strength=2,
    ),
    # === Posterization seule (ecrase bruit invisible, instantane) ===========
    "strict_v1_posterize_8": dict(
        use_otsu_grayscale=False,
        ink_dilate=0,
        close_radius=2,
        expand_to_ink=False,
        posterize_levels=8,  # 512 couleurs max
    ),
    "strict_v1_posterize_6": dict(
        use_otsu_grayscale=False,
        ink_dilate=0,
        close_radius=2,
        expand_to_ink=False,
        posterize_levels=6,  # 216 couleurs max
    ),
    "strict_v1_posterize_4": dict(
        use_otsu_grayscale=False,
        ink_dilate=0,
        close_radius=2,
        expand_to_ink=False,
        posterize_levels=4,  # 64 couleurs max (tres agressif)
    ),
    # === Combo posterize + bilateral (le combo le plus puissant et rapide) ===
    "strict_v1_posterize8_bilateral": dict(
        use_otsu_grayscale=False,
        ink_dilate=0,
        close_radius=2,
        expand_to_ink=False,
        posterize_levels=8,
        simplify_method="bilateral",
        simplify_strength=2,
    ),
    "strict_v1_posterize6_meanshift": dict(
        use_otsu_grayscale=False,
        ink_dilate=0,
        close_radius=2,
        expand_to_ink=False,
        posterize_levels=6,
        simplify_method="mean_shift",
        simplify_strength=1,
    ),
    # === Quality presets : LAB k-means + merge similar + morpho cleanup =====
    # Trait reste immutable (ink_mask sur image originale).
    # quality_v1 : compromis qualite/vitesse, sans mean-shift.
    "quality_v1": dict(
        use_otsu_grayscale=False,
        ink_dilate=0,
        close_radius=2,
        expand_to_ink=False,
        posterize_levels=8,
        simplify_method="bilateral",
        simplify_strength=2,
        kmeans_color_space="lab",
        merge_similar_delta_e=8.0,
        morpho_cleanup_radius=2,
    ),
    # quality_v2 : plus aggressif, mean-shift inclus.
    "quality_v2": dict(
        use_otsu_grayscale=False,
        ink_dilate=0,
        close_radius=2,
        expand_to_ink=False,
        posterize_levels=6,
        simplify_method="mean_shift",
        simplify_strength=1,
        kmeans_color_space="lab",
        merge_similar_delta_e=10.0,
        morpho_cleanup_radius=3,
    ),
    # quality_max : tout au maximum (le plus lent, le plus propre).
    "quality_max": dict(
        use_otsu_grayscale=False,
        ink_dilate=0,
        close_radius=2,
        expand_to_ink=False,
        posterize_levels=6,
        simplify_method="mean_shift",
        simplify_strength=2,
        kmeans_color_space="lab",
        merge_similar_delta_e=12.0,
        morpho_cleanup_radius=4,
    ),
    # === Presets palette large : on "ne loupe rien" puis on collapse =========
    # n_colors eleve = on capture toutes les nuances, meme imperceptibles.
    # merge_similar_delta_e plus eleve = on fusionne ce qui n'est pas distinct
    # a l'oeil. Resultat final : nombre de couleurs adapte a l'image, pas
    # fixe arbitrairement.
    "quality_v2_n16": dict(
        n_colors=16,
        use_otsu_grayscale=False,
        ink_dilate=0,
        close_radius=2,
        expand_to_ink=False,
        posterize_levels=6,
        simplify_method="mean_shift",
        simplify_strength=1,
        kmeans_color_space="lab",
        merge_similar_delta_e=10.0,
        morpho_cleanup_radius=3,
    ),
    "quality_v2_n24": dict(
        n_colors=24,
        use_otsu_grayscale=False,
        ink_dilate=0,
        close_radius=2,
        expand_to_ink=False,
        posterize_levels=6,
        simplify_method="mean_shift",
        simplify_strength=1,
        kmeans_color_space="lab",
        merge_similar_delta_e=12.0,
        morpho_cleanup_radius=3,
    ),
    "quality_v2_n32": dict(
        n_colors=32,
        use_otsu_grayscale=False,
        ink_dilate=0,
        close_radius=2,
        expand_to_ink=False,
        posterize_levels=6,
        simplify_method="mean_shift",
        simplify_strength=1,
        kmeans_color_space="lab",
        merge_similar_delta_e=14.0,
        morpho_cleanup_radius=3,
    ),
    # Variante rapide : posterize+bilateral (au lieu de mean-shift) avec
    # palette large. Compromis vitesse/qualite.
    "quality_fast_n24": dict(
        n_colors=24,
        use_otsu_grayscale=False,
        ink_dilate=0,
        close_radius=2,
        expand_to_ink=False,
        posterize_levels=8,
        simplify_method="bilateral",
        simplify_strength=2,
        kmeans_color_space="lab",
        merge_similar_delta_e=10.0,
        morpho_cleanup_radius=2,
    ),
    # === Pipeline trait skeleton : trait fin + continu + uniforme ===========
    # Detection permissive -> CLOSE -> filter speckles -> skeleton 1px ->
    # redilate a thickness fixe. Le trait final est :
    #   - CONTINU (pas de discontinuites)
    #   - FIN (epaisseur uniforme reglable)
    #   - SANS SPECKLE (parasites elimines)
    # Sans bouffer les couleurs sombres (le redilate reste fin).
    "strict_v1_ink_skeleton_2px": dict(
        use_otsu_grayscale=False,
        ink_dilate=0,
        close_radius=2,
        expand_to_ink=False,
        ink_pipeline="skeleton",
        ink_target_thickness=2,
        ink_min_speckle_px=20,
    ),
    "strict_v1_ink_skeleton_3px": dict(
        use_otsu_grayscale=False,
        ink_dilate=0,
        close_radius=2,
        expand_to_ink=False,
        ink_pipeline="skeleton",
        ink_target_thickness=3,
        ink_min_speckle_px=30,
    ),
    # Combo quality + skeleton ink : la combinaison optimale a tester.
    "quality_v2_n32_ink_skeleton": dict(
        n_colors=32,
        use_otsu_grayscale=False,
        ink_dilate=0,
        close_radius=2,
        expand_to_ink=False,
        posterize_levels=6,
        simplify_method="mean_shift",
        simplify_strength=1,
        kmeans_color_space="lab",
        merge_similar_delta_e=14.0,
        morpho_cleanup_radius=3,
        ink_pipeline="skeleton",
        ink_target_thickness=2,
        ink_min_speckle_px=20,
    ),
    # === SEPARATION CONTOUR / REGIONS ========================================
    # Le contour est extrait avec les params strict_v1 (immutable) sur l'image
    # ORIGINALE. Le k-means utilise un ink_mask dilate (ink_kmeans_dilate=2)
    # pour exclure l'anti-aliasing du trait des clusters couleur, SANS toucher
    # au trait visible final.
    "iso_trait_v1": dict(
        # contour : exactement strict_v1
        use_otsu_grayscale=False,
        ink_dilate=0,
        close_radius=2,
        expand_to_ink=False,
        # k-means : exclut un halo de 2 px autour du trait
        ink_kmeans_dilate=2,
    ),
    "iso_trait_quality_v2_n32": dict(
        # contour : strict_v1 strict
        use_otsu_grayscale=False,
        ink_dilate=0,
        close_radius=2,
        # k-means : exclut halo 2px ET applique le pipeline qualite
        ink_kmeans_dilate=2,
        n_colors=32,
        expand_to_ink=False,
        posterize_levels=6,
        simplify_method="mean_shift",
        simplify_strength=1,
        kmeans_color_space="lab",
        merge_similar_delta_e=14.0,
        morpho_cleanup_radius=3,
    ),
    "iso_trait_quality_v2_n24": dict(
        use_otsu_grayscale=False,
        ink_dilate=0,
        close_radius=2,
        ink_kmeans_dilate=2,
        n_colors=24,
        expand_to_ink=False,
        posterize_levels=6,
        simplify_method="mean_shift",
        simplify_strength=1,
        kmeans_color_space="lab",
        merge_similar_delta_e=12.0,
        morpho_cleanup_radius=3,
    ),
    # Variante rapide (sans mean_shift) avec separation trait/regions
    "iso_trait_fast": dict(
        use_otsu_grayscale=False,
        ink_dilate=0,
        close_radius=2,
        ink_kmeans_dilate=2,
        n_colors=24,
        posterize_levels=8,
        simplify_method="bilateral",
        simplify_strength=2,
        kmeans_color_space="lab",
        merge_similar_delta_e=10.0,
        morpho_cleanup_radius=2,
    ),
    # === Trait V3 (epais et continu, capture user 2026-05-30) ===============
    # Restauration des params ink de balanced_v3 (15.4% ink sur C) qui
    # donnaient un contour parfait : continu, epais, bien dessine autour de
    # chaque detail. Combinaison avec separation trait/regions.
    #
    # Trait params :
    #   use_otsu_grayscale=True, otsu_max_threshold=90 (capte les sombres)
    #   ink_dilate=1 (couvre l'anti-aliasing)
    #   close_radius=3 (ressoude les micro-coupures)
    "iso_trait_v3": dict(
        # contour : params V3 (trait epais continu)
        use_otsu_grayscale=True,
        otsu_max_threshold=90,
        ink_dilate=1,
        close_radius=3,
        # k-means strict n=12, separation contour/regions
        ink_kmeans_dilate=2,
        expand_to_ink=False,
    ),
    "iso_trait_v3_quality_v2_n24": dict(
        # trait V3 + regions quality n=24
        use_otsu_grayscale=True,
        otsu_max_threshold=90,
        ink_dilate=1,
        close_radius=3,
        ink_kmeans_dilate=2,
        n_colors=24,
        expand_to_ink=False,
        posterize_levels=6,
        simplify_method="mean_shift",
        simplify_strength=1,
        kmeans_color_space="lab",
        merge_similar_delta_e=12.0,
        morpho_cleanup_radius=3,
    ),
    "iso_trait_v3_quality_v2_n32": dict(
        # trait V3 + regions quality n=32 (le combo "all in")
        use_otsu_grayscale=True,
        otsu_max_threshold=90,
        ink_dilate=1,
        close_radius=3,
        ink_kmeans_dilate=2,
        n_colors=32,
        expand_to_ink=False,
        posterize_levels=6,
        simplify_method="mean_shift",
        simplify_strength=1,
        kmeans_color_space="lab",
        merge_similar_delta_e=14.0,
        morpho_cleanup_radius=3,
    ),
    # Reproduction exacte de la capture user (filled_v4) :
    # trait V3 + expansion Voronoi -> 15.4% ink + 95.5% reg_cov sur C.
    "iso_trait_v3_filled": dict(
        use_otsu_grayscale=True,
        otsu_max_threshold=90,
        ink_dilate=1,
        close_radius=3,
        ink_kmeans_dilate=2,
        expand_to_ink=True,
        expand_max_distance=0,
    ),
    # === Anti-gap presets : eliminer les micro-blancs trait/regions ==========
    # simplify_ratio bas (0.0005 = 4x plus fidele) + stroke 1px de meme couleur
    # qui comble les ecarts de Douglas-Peucker sans modifier les regions.
    "iso_trait_v3_filled_no_gap": dict(
        use_otsu_grayscale=True,
        otsu_max_threshold=90,
        ink_dilate=1,
        close_radius=3,
        ink_kmeans_dilate=2,
        expand_to_ink=True,
        expand_max_distance=0,
        simplify_ratio=0.0005,    # contours 4x plus fideles au pixel
        region_stroke_width=1,    # stroke meme couleur, comble les micro-ecarts
    ),
    # iso_trait_v3_filled_no_gap + fusion des petites regions (< 400 px) dans
    # leur voisin majoritaire. Reduit le nombre de clics pour colorier en UX.
    # + isolation stricte via trait epaissi 6 px (ferme les gaps jusqu'a 12 px)
    # -> aucun fragment ne peut rester rattache au fond exterieur.
    "iso_trait_v3_filled_no_gap_merged": dict(
        use_otsu_grayscale=True,
        otsu_max_threshold=90,
        ink_dilate=1,
        close_radius=3,
        ink_kmeans_dilate=2,
        expand_to_ink=True,
        expand_max_distance=0,
        simplify_ratio=0.0005,
        region_stroke_width=1,
        merge_small_regions_px=400,
        isolate_background_thick_radius=6,
    ),
    # Variante "agressive merge" : seuil plus eleve (1000 px) pour vraiment
    # ne garder que les regions visuellement significatives.
    "iso_trait_v3_filled_no_gap_merged_aggressive": dict(
        use_otsu_grayscale=True,
        otsu_max_threshold=90,
        ink_dilate=1,
        close_radius=3,
        ink_kmeans_dilate=2,
        expand_to_ink=True,
        expand_max_distance=0,
        simplify_ratio=0.0005,
        region_stroke_width=1,
        merge_small_regions_px=1000,
    ),
    # Variante "strong" : isolation fond plus stricte (gaps jusqu'a 20 px bouches).
    # A utiliser sur les images avec gros gaps dans le trait (ex : pastel_cat).
    # Risque : peut boucher des ouvertures legitimes > 20 px (par ex entre 2 pattes).
    "iso_trait_v3_filled_no_gap_merged_strong": dict(
        use_otsu_grayscale=True,
        otsu_max_threshold=90,
        ink_dilate=1,
        close_radius=3,
        ink_kmeans_dilate=2,
        expand_to_ink=True,
        expand_max_distance=0,
        simplify_ratio=0.0005,
        region_stroke_width=1,
        merge_small_regions_px=400,
        isolate_background_thick_radius=10,  # vs 6 dans le merged standard
    ),
    # Variante "very strong" : gaps jusqu'a 24 px bouches.
    "iso_trait_v3_filled_no_gap_merged_very_strong": dict(
        use_otsu_grayscale=True,
        otsu_max_threshold=90,
        ink_dilate=1,
        close_radius=3,
        ink_kmeans_dilate=2,
        expand_to_ink=True,
        expand_max_distance=0,
        simplify_ratio=0.0005,
        region_stroke_width=1,
        merge_small_regions_px=400,
        isolate_background_thick_radius=12,
    ),
    # === Approche semantique : detection fond par COULEUR (LAB delta-E) ====
    # Independante du trait et de la connectivite. Robuste sur les images ou
    # le fond a une couleur distincte du sujet (typique des coloriages ERNIE).
    # delta_e=20 : tolerance moyenne. 25 = plus permissif (peut manger des
    # zones tres claires du sujet). 15 = plus strict.
    "iso_trait_v3_color_bg": dict(
        use_otsu_grayscale=True,
        otsu_max_threshold=90,
        ink_dilate=1,
        close_radius=3,
        ink_kmeans_dilate=2,
        expand_to_ink=True,
        expand_max_distance=0,
        simplify_ratio=0.0005,
        region_stroke_width=1,
        merge_small_regions_px=400,
        # Approche semantique pure : detection par couleur des coins
        isolate_background_thick_radius=0,  # OFF, on n'utilise plus l'epaississement
        bg_color_detection_delta_e=20.0,
        bg_color_corner_size=10,
    ),
    # Combo : detection couleur + isolation classique trait epaissi (ceinture
    # ET bretelles).
    "iso_trait_v3_color_bg_combo": dict(
        use_otsu_grayscale=True,
        otsu_max_threshold=90,
        ink_dilate=1,
        close_radius=3,
        ink_kmeans_dilate=2,
        expand_to_ink=True,
        expand_max_distance=0,
        simplify_ratio=0.0005,
        region_stroke_width=1,
        merge_small_regions_px=400,
        isolate_background_thick_radius=6,
        bg_color_detection_delta_e=20.0,
        bg_color_corner_size=10,
    ),
    # === SILHOUETTE SPLIT : approche structurelle ===========================
    # Detection du masque silhouette une fois, puis split de chaque cluster
    # k-means qui chevauche silhouette/fond. Resout le bug "region#1 fond+tete"
    # sans dependre des seuils de couleur ni de la connectivite des gaps.
    "iso_trait_v3_silhouette_split": dict(
        use_otsu_grayscale=True,
        otsu_max_threshold=90,
        ink_dilate=1,
        close_radius=3,
        ink_kmeans_dilate=2,
        expand_to_ink=True,
        expand_max_distance=0,
        simplify_ratio=0.0005,
        region_stroke_width=1,
        merge_small_regions_px=400,
        # OFF les approches precedentes (la silhouette split les remplace).
        isolate_background_thick_radius=0,
        bg_color_detection_delta_e=0.0,
        # ON la nouvelle approche.
        use_silhouette_split=True,
        silhouette_corner_size=10,
        silhouette_split_min_overlap=0.05,
        silhouette_close_radius=5,
    ),
    # === ANOMALY DETECTION : approche autonome (ne touche que les zones suspectes) ==
    # Detecte les composantes > 30% canvas et tente un split local k-means k=2 LAB.
    # Ne necessite PAS de detection silhouette globale. Auto-correctif.
    "iso_trait_v3_anomaly_split": dict(
        use_otsu_grayscale=True,
        otsu_max_threshold=90,
        ink_dilate=1,
        close_radius=3,
        ink_kmeans_dilate=2,
        expand_to_ink=True,
        expand_max_distance=0,
        simplify_ratio=0.0005,
        region_stroke_width=1,
        merge_small_regions_px=400,
        # Approche autonome : ne touche que les zones anormales
        anomaly_detection_enabled=True,
        anomaly_size_pct_threshold=0.30,  # > 30% canvas = suspect
        anomaly_min_delta_e=10.0,
        anomaly_max_passes=2,
    ),
    # === PRESET FLOODFILL CHROMAKEY (alternative au k-means) ================
    # Suppose : prompt ERNIE avec fond chromakey green #00B140 + trait net.
    # Pipeline : detection fond par couleur + composantes connexes des pixels
    # libres. Pas de k-means, pas d'anomaly_split. Resout structurellement
    # le bug "fond fuit dans silhouette" via chromakey LAB-distinct.
    # Idee : 2026-05-31. POC en parallele du preset prod (iso_trait_v3_anomaly_split).
    "floodfill_chromakey_v1": dict(
        # Trait V3 (immutable, comme preset prod)
        # NB: ink_otsu_max_saturation NON utilise ici - tentative 2026-06-01
        # rollback (cassait l'anti-aliasing du trait contre regions saturees
        # qui paradoxalement a saturation haute, cf analyse 2026-06-01).
        use_otsu_grayscale=True,
        otsu_max_threshold=90,
        ink_dilate=1,
        close_radius=3,
        # Split heterogene 2026-06-01 : k-means LAB par composante quand le
        # trait noir est discontinu entre regions adjacentes (fusion par
        # connectivite). Combine avec palette spread-LAB cote prompt
        # (flat_cartoon updated 2026-06-01), deltaE inter-cluster > 50.
        floodfill_split_heterogeneous=True,
        floodfill_split_std_threshold=25.0,
        floodfill_split_k=4,
        # 0.02 (au lieu de 0.05 default) : permet de capturer les sous-regions
        # qui representent une faible proportion de la composante mere mais
        # une couleur distincte. Ex 01354 : bleu royal = 26k px (2.8% de la
        # composante massive de 950k) - serait filtre a 5% mais utile a 2%.
        floodfill_split_min_subcluster_pct=0.02,
        # Filtre geodesique du trait 2026-06-01 (option B) : un pixel n'est
        # trait que s'il est connecte au "noir vrai" (luma<30 AND S<30).
        # Resout le cas ou ERNIE genere des couleurs de region sombres saturees
        # (ex royal blue #0E24F1 luma 53) qui forment des composantes isolees
        # mais sont capturees par Otsu OR.
        ink_geodesic_enabled=True,
        ink_core_luma_max=30,
        ink_core_sat_max=30,
        # Pre-extraction + injection du trait (strategie adoptee 2026-06-01) :
        # extrait trait HSV strict puis peint en noir pur (0,0,0) dans l'image
        # source avant detection des regions. Cree un "noir vrai" parfait que
        # les couleurs de region sombres saturees ne peuvent plus imiter.
        preextract_ink_inject=True,
        # Pipeline alternatif
        use_floodfill=True,
        chromakey_rgb=(0, 177, 64),       # #00B140 standard cinema
        chromakey_delta_e=25.0,            # NB: plus strict pour ne pas classer
                                           # l'anti-aliasing sujet/fond comme chromakey
        flood_pre_dilate=1,
        flood_min_region_area_px=50,      # NB: 50 au lieu de 200 (preserve les micro-details)
        min_region_area_ratio=0.0002,      # NB: 0.0002 = ~200 px sur 1024 (au lieu de 0.001 = ~1048)
        # Rendu
        simplify_ratio=0.0005,
        region_stroke_width=6,             # NB: 6 px valide 2026-05-31 - recouvre les pixels
                                           # orphelins en bordure (zones de contact sujet/fond).
                                           # Le trait noir reste par-dessus via z-order.
        # Tous les params k-means / anomaly / expand sont IGNORES quand
        # use_floodfill=True, mais on les fixe explicitement a OFF pour clarte
        anomaly_detection_enabled=False,
        merge_small_regions_px=0,
        expand_to_ink=False,
        isolate_background=False,
    ),
    # Variante "tolerante" : delta-E plus large (chromakey eventuellement
    # imparfait dans la generation ERNIE) + dilate trait 2 px.
    "floodfill_chromakey_v1_tolerant": dict(
        use_otsu_grayscale=True,
        otsu_max_threshold=90,
        ink_dilate=1,
        close_radius=3,
        use_floodfill=True,
        chromakey_rgb=(0, 177, 64),
        chromakey_delta_e=45.0,            # plus tolerant
        flood_pre_dilate=2,                # plus de dilate
        flood_min_region_area_px=200,
        simplify_ratio=0.0005,
        region_stroke_width=1,
        anomaly_detection_enabled=False,
        merge_small_regions_px=0,
        expand_to_ink=False,
        isolate_background=False,
    ),
    # Version plus sensible (declenche sur 20% au lieu de 30%)
    "iso_trait_v3_anomaly_split_sensitive": dict(
        use_otsu_grayscale=True,
        otsu_max_threshold=90,
        ink_dilate=1,
        close_radius=3,
        ink_kmeans_dilate=2,
        expand_to_ink=True,
        expand_max_distance=0,
        simplify_ratio=0.0005,
        region_stroke_width=1,
        merge_small_regions_px=400,
        anomaly_detection_enabled=True,
        anomaly_size_pct_threshold=0.20,
        anomaly_min_delta_e=8.0,
        anomaly_max_passes=3,
    ),
    # Combo : silhouette split + isolation classique (ceinture + bretelles).
    "iso_trait_v3_silhouette_split_combo": dict(
        use_otsu_grayscale=True,
        otsu_max_threshold=90,
        ink_dilate=1,
        close_radius=3,
        ink_kmeans_dilate=2,
        expand_to_ink=True,
        expand_max_distance=0,
        simplify_ratio=0.0005,
        region_stroke_width=1,
        merge_small_regions_px=400,
        isolate_background_thick_radius=6,
        use_silhouette_split=True,
        silhouette_corner_size=10,
        silhouette_split_min_overlap=0.05,
        silhouette_close_radius=5,
    ),
    # Variante "precise" : seulement le simplify_ratio bas, sans stroke.
    # Sert a isoler l'effet du simplify pour le diagnostic.
    "iso_trait_v3_filled_precise": dict(
        use_otsu_grayscale=True,
        otsu_max_threshold=90,
        ink_dilate=1,
        close_radius=3,
        ink_kmeans_dilate=2,
        expand_to_ink=True,
        expand_max_distance=0,
        simplify_ratio=0.0005,
    ),
    # Variante "stroked" : simplify standard mais stroke 1px partout.
    # Sert a isoler l'effet du stroke pour le diagnostic.
    "iso_trait_v3_filled_stroked": dict(
        use_otsu_grayscale=True,
        otsu_max_threshold=90,
        ink_dilate=1,
        close_radius=3,
        ink_kmeans_dilate=2,
        expand_to_ink=True,
        expand_max_distance=0,
        region_stroke_width=1,
    ),
    # v3 default : combo Otsu plafonne + dilate 1 + close 3. Trait continu.
    # Recommande par defaut.
    "balanced_v3": dict(
        use_otsu_grayscale=True,
        otsu_max_threshold=90,
        ink_dilate=1,
        close_radius=3,
        expand_to_ink=False,
    ),
    # v4 filled : v3 + expansion Voronoi des regions jusqu'au trait. Vue
    # "regions only" sans halo blanc. Conviendra si le rendu colorie sans
    # contour est exploite (ex : version 'aperçu' destinee au marketing).
    "filled_v4": dict(
        use_otsu_grayscale=True,
        otsu_max_threshold=90,
        ink_dilate=1,
        close_radius=3,
        expand_to_ink=True,
        expand_max_distance=0,
    ),
    # variante agressive : Otsu permissif (max 110) + dilate 2 + close 4 +
    # expand. Pour images tres texturees / traits epais.
    "aggressive_v4": dict(
        use_otsu_grayscale=True,
        otsu_max_threshold=110,
        ink_dilate=2,
        close_radius=4,
        expand_to_ink=True,
        expand_max_distance=0,
    ),
}


def make_params(preset: str | None = None, **overrides) -> "ExtractPaletteParams":
    """Construit des ExtractPaletteParams depuis un preset + overrides.

    >>> make_params(PROD_PRESET)  # equivalent a make_params("iso_trait_v3_anomaly_split")
    >>> make_params("iso_trait_v3_anomaly_split")
    >>> make_params(PROD_PRESET, n_colors=16)  # override partiel
    >>> make_params(None)  # = ExtractPaletteParams() defaults
    """
    base = PRESETS[preset] if preset else {}
    merged = {**base, **overrides}
    return ExtractPaletteParams(**merged)


# === Preset prod (adopte le 2026-05-31) ====================================
# Voir _lab/extract-palette/CAPITALISATION.md pour historique evolution.
PROD_PRESET = "iso_trait_v3_anomaly_split"
"""Preset prod par defaut. Adopte 2026-05-31 apres validation 47 PNG pastel +
3 leafs taxonomie. Cle dans dict PRESETS. Pour rollback : utiliser
"iso_trait_v3_filled_no_gap_merged" (ancien prod) ou n'importe quel preset
historique."""


@dataclass
class ExtractPaletteParams:
    """Parametres de la decomposition."""

    # === Pipeline FLOODFILL CHROMAKEY (alternative au k-means) ==============
    # Quand True : detection fond par couleur chromakey + composantes connexes
    # sur le masque "pixels disponibles" (NOT trait AND NOT chromakey).
    # Chaque composante = une region. Couleur calculee a posteriori (moyenne BGR).
    # Suppose un prompt ERNIE qui impose un fond chromakey green vif et trait net.
    # Pipeline radicalement plus simple : pas de k-means, pas d'anomaly_split.
    use_floodfill: bool = False
    chromakey_rgb: tuple = (0, 177, 64)  # type: tuple[int, int, int] -- #00B140 standard cinema
    chromakey_delta_e: float = 30.0  # tolerance LAB autour de la couleur chromakey
    flood_pre_dilate: int = 1  # dilate trait avant flood (bouche gaps fins)
    flood_min_region_area_px: int = 200  # filtre micro-bassins parasites

    # === Palette imposee (court-circuite k-means) ===========================
    # Si fournie : chaque pixel non-trait est attribue a la couleur de la
    # palette la PLUS PROCHE en LAB perceptuel (au lieu de k-means BGR aveugle).
    # Format : liste de tuples (R, G, B) uint8.
    # Cas d'usage : on connait la palette imposee par le prompt ERNIE
    # ('pale yellow, peach, sky-blue, ...'). On utilise cette palette comme
    # cible d'attribution directe -> 0 cluster invente artificiellement par
    # k-means, 0 fragmentation sur des nuances perceptuellement identiques.
    forced_palette_rgb: list = None  # type: list[tuple[int,int,int]] | None

    # === Masque trait noir =====
    # HSV : pixels sombres + peu colores.
    ink_max_value: int = 80
    ink_max_saturation: int = 60
    # Otsu grayscale : combine en OR avec le HSV pour rattraper l'anti-aliasing
    # entre le trait et les zones colorees vives.
    use_otsu_grayscale: bool = True
    # Plafond dur sur Otsu : on n'utilise Otsu que jusqu'a ce seuil de gray.
    # Sinon Otsu sur une image avec couleurs sombres dominantes (brun, violet)
    # va classer ces couleurs comme "trait" -> sur-encrage.
    # 90 = compromis : capture l'anti-aliasing du trait (gris 50-90) sans
    # manger les couleurs moyennes (gris > 100).
    otsu_max_threshold: int = 90
    # Filtre saturation sur la branche Otsu (anti-faux-positif couleurs saturees
    # sombres). Un pixel n'est classe comme trait via Otsu QUE si sa saturation
    # est sous ce seuil. Empeche les couleurs vives sombres (ex: #0252FF royal
    # blue, luma=78 < Otsu mais S=99%) d'etre confondues avec le trait noir.
    # 255 = pas de filtre (comportement historique, default).
    # 60 = neutre (trait noir/gris uniquement). Recommande pour styles a
    # couleurs saturees comme flat_cartoon.
    ink_otsu_max_saturation: int = 255
    # === Filtre geodesique du trait (option B 2026-06-01) ===
    # Quand active, le masque trait final ne garde que les composantes connexes
    # qui touchent le "noir vrai" (luma < ink_core_luma_max AND S < ink_core_sat_max).
    # Resout le cas ou ERNIE genere des couleurs de region sombres saturees
    # (ex royal blue luma 53) qui forment des composantes isolees loin du
    # trait noir vrai mais sont capturees par Otsu OR. L'anti-aliasing du
    # trait noir reste preserve car connecte au core. Sans casser la
    # continuite du trait (cf echec du filtre saturation global).
    ink_geodesic_enabled: bool = False
    ink_core_luma_max: int = 30
    ink_core_sat_max: int = 30
    # === Pre-extraction et injection du trait (2026-06-01) ===
    # Strategie adoptee pour pipeline chromakey : avant de detecter le ink_mask
    # par les voies normales, on extrait le trait via HSV strict pur (V<80 ET
    # S<60, sans Otsu OR ni geodesic) puis on injecte du noir pur (0,0,0)
    # dans l'image source aux pixels du trait. Le pipeline normal voit alors
    # un noir vrai parfait (luma 0, S 0) qui rentre dans le core, et les
    # couleurs sombres saturees (royal blue, etc.) restent intactes dans
    # les regions. Resout structurellement la confusion couleur-region /
    # couleur-trait sans necessiter d'heuristiques colorimetriques.
    preextract_ink_inject: bool = False
    # Distance maximum (px) d'un pixel candidat au "noir vrai" le plus proche
    # pour qu'il soit garde comme trait. 8 px = sweet spot calibre 2026-06-01
    # apres feedback "trait discontinu" : preserve 91-100% du noir vrai
    # (continuite du trait visuel) au prix de 22% du bleu sombre encore
    # classe trait (rendus comme contours noirs fins en bordure des regions,
    # visuellement acceptable). Distance moyenne du royal blue au noir vrai
    # = 17.6 px - donc 80% du bleu est bien rejete a max_d=8.
    ink_geodesic_max_distance: int = 8
    # === Split heterogene par composante (pipeline floodfill) ===
    # Quand active, chaque composante connexe est verifie pour homogeneite
    # chromatique (std LAB). Si > seuil, k-means local LAB k=floodfill_split_k
    # split la composante en sous-regions. Resout les fusions par connectivite
    # quand le trait noir est discontinu entre regions adjacentes.
    floodfill_split_heterogeneous: bool = False
    floodfill_split_std_threshold: float = 25.0
    floodfill_split_k: int = 4
    floodfill_split_min_subcluster_pct: float = 0.05
    # Dilatation du trait apres masquage : couvre les pixels anti-aliases qui
    # passent encore au travers. 1 px suffit.
    # NOTE : ce dilate s'applique au ink_mask UTILISE POUR LE RENDU (le trait
    # visible final). Si tu veux dilater seulement pour exclure du k-means
    # sans epaissir le trait visible, utilise ``ink_kmeans_dilate`` ci-dessous.
    ink_dilate: int = 1
    close_radius: int = 3       # morpho CLOSE final (ressoude micro-coupures)
    # Dilatation SUPPLEMENTAIRE applique uniquement au masque qui sert a EXCLURE
    # les pixels du k-means (pas au rendu). Permet d'eviter que les pixels
    # anti-aliases en bordure de trait polluent les clusters couleur, tout en
    # gardant le trait visible IMMUTABLE.
    # Recommande : 2 px pour quality_*, 0 pour strict_v1 si tu veux des
    # frontieres regions = frontiere trait au pixel pres.
    ink_kmeans_dilate: int = 0
    # === Pipeline de detection du trait =====================================
    # 'simple'   : pipeline historique (HSV + Otsu optionnel + close + dilate).
    # 'skeleton' : detection permissive -> CLOSE -> filter speckles -> skeleton
    #              -> redilate a thickness uniforme. Trait continu + fin +
    #              epaisseur stable, sans bouffer les couleurs sombres.
    ink_pipeline: str = "simple"
    # Pipeline 'skeleton' uniquement :
    ink_target_thickness: int = 2     # epaisseur finale apres skeleton
    ink_min_speckle_px: int = 20      # composantes < N px = speckle a virer
    ink_permissive_v_max: int = 110   # V max plus large pour le mask permissif
    ink_permissive_s_max: int = 100   # S max plus large pour le mask permissif
    ink_skeleton_close_radius: int = 3  # CLOSE morpho avant skeletonize
    # === Quantification couleurs ===
    n_colors: int = 12
    kmeans_attempts: int = 5
    # Espace colorimetrique du k-means : 'bgr' ou 'lab'.
    # LAB est perceptuellement uniforme : 2 couleurs visuellement identiques
    # restent groupees meme si leurs RGB differ. Recommande pour qualite max.
    kmeans_color_space: str = "bgr"
    # Fusion post-k-means des clusters trop proches en LAB (delta-E CIE76).
    # 0 = off. 5 = juste imperceptible. 10 = fusion modere. 20 = aggressive.
    # Reduit le nombre de couleurs effectives a ce qui est visuellement distinct.
    merge_similar_delta_e: float = 0.0
    # Morpho cleanup intra-label : OPEN + CLOSE sur chaque region pour eliminer
    # les speckles internes (petits ilots) et combler les micro-trous.
    # 0 = off. 2 = leger. 3-4 = plus aggressif (peut deformer les contours fins).
    morpho_cleanup_radius: int = 0
    # Isolation du vrai background vs fragments interieurs partageant son label.
    # Sans ca, le fond fuit a l'interieur de la silhouette via les gaps du trait
    # -> click sur le fond colorie aussi des morceaux interieurs. Avec ca :
    #   1. Composante du background touchant le bord = vrai fond.
    #   2. Autres composantes meme label = fragments interieurs -> reattribues
    #      a la region voisine non-fond la plus proche (distance transform).
    # ON par defaut.
    isolate_background: bool = True
    # Fusion semantique : toute composante connexe < N pixels est fusionnee
    # dans son voisin MAJORITAIRE (le label le plus represente a sa frontiere).
    # Reduit le nombre de clics pour colorier (moins de petites zones isolees).
    # 0 = off. 100-300 = leger. 500-1000 = plus aggressif.
    # Multi-passes : on continue tant qu'on trouve des fusions a faire (max 3).
    merge_small_regions_px: int = 0
    merge_small_max_passes: int = 3
    # Isolation STRICTE du background via trait epaissi virtuel.
    # Dilatation de N px du masque trait original ferme tous les gaps fins
    # (un gap < 2*N px est totalement bouche). On refait alors connectedComponents
    # sur l'inverse de ce masque epaissi pour distinguer vrai fond exterieur
    # (touche le bord) vs interieur strict du sujet. Tout pixel bg_label qui
    # tombe dans l'interieur strict est reattribue a la region voisine.
    # 0 = off. 6 = recommande (ferme gaps jusqu'a 12 px). 10 = plus aggressif.
    isolate_background_thick_radius: int = 0
    # === Detection du fond par COULEUR (LAB) ===
    # Approche semantique : sampler la couleur des 4 coins du canvas, mesurer
    # la distance LAB de chaque pixel a cette couleur de reference. Pixels avec
    # distance < seuil = vrai fond. Tout pixel label==bg_label qui N'EST PAS
    # dans ce mask = fragment interieur faussement classe -> reattribue.
    # Indépendant du trait, des gaps et de la connectivite topologique.
    # 0 = off. 15-25 = recommande (delta-E LAB). Plus haut = plus tolerant.
    bg_color_detection_delta_e: float = 0.0
    bg_color_corner_size: int = 10  # taille de la zone sample dans chaque coin
    # === SILHOUETTE SPLIT : approche structurelle ===
    # Detecte un masque silhouette (interieur du sujet) une fois pour toutes,
    # puis split chaque region k-means qui chevauche silhouette/fond en 2
    # sous-regions distinctes. Resout structurellement le bug "label bg qui
    # contient des morceaux interieurs" sans dependre de la connectivite.
    # ON par defaut sur les nouveaux presets _split_.
    use_silhouette_split: bool = False
    # Taille zone sample 4 coins pour detection couleur du fond.
    silhouette_corner_size: int = 10
    # Min ratio de chevauchement pour declencher le split (0.05 = 5%).
    # Si < 5% en intersection avec silhouette, on considere la region comme
    # purement fond ou purement interieur. Si > 5% et < 95%, on split.
    silhouette_split_min_overlap: float = 0.05
    # Morpho close radius sur le masque silhouette (lisse les contours).
    silhouette_close_radius: int = 5
    # Methode de detection de la silhouette : 'kmeans2' (robuste) ou 'otsu_distance'.
    silhouette_method: str = "kmeans2"
    # === Detection par ANOMALIE et split local ===
    # Detecte les composantes connexes anormalement grandes (> seuil % canvas)
    # et tente un re-k-means k=2 LAB local pour les splitter en sous-regions.
    # Validation : split applique uniquement si delta_E LAB entre les 2
    # sous-clusters > 10 ET seulement 1 des 2 touche le bord du canvas.
    # Plus robuste que la silhouette globale : analyse uniquement les zones
    # SUSPECTES de contenir fond + interieur.
    anomaly_detection_enabled: bool = False
    anomaly_size_pct_threshold: float = 0.30  # composante > 30% canvas = suspect
    anomaly_min_delta_e: float = 10.0  # ecart LAB min entre les 2 sous-clusters
    anomaly_max_passes: int = 2  # nb max de passes (chaque passe peut creer de nouvelles anomalies)
    # Expansion des regions jusqu'aux pixels du trait via distance transform.
    # Sans ca, les pixels ink restent unclassed -> halo blanc autour des regions
    # quand on dessine "regions only" (sans trait).
    # DEFAUT OFF : conserve la frontiere stricte au trait. Voir PRESETS['filled']
    # pour la version qui remplit jusqu'au contour.
    expand_to_ink: bool = False
    # Limite : si la distance au pixel-region le plus proche depasse N px, on
    # laisse ink (evite que des regions s'etendent a travers de gros artefacts).
    # 0 = pas de limite (recommande pour line-art classique).
    expand_max_distance: int = 0
    # === Filtrage regions ===
    min_region_area_ratio: float = 0.001
    max_regions_per_color: int = 50
    simplify_ratio: float = 0.002
    # === Pre-clean ===
    despeckle: bool = True
    # === Posterization (avant tout, ecrase le bruit invisible) ===
    # Quantification dure des canaux RGB : chaque canal force a N niveaux.
    # Ecrase les micro-variations sous le seuil de perception (compression,
    # anti-aliasing interne d'ERNIE) qui creent de faux clusters k-means.
    # 0 = off ; 8 = 512 couleurs max ; 6 = 216 ; 4 = 64 (tres agressif).
    posterize_levels: int = 0
    # === Pre-simplification des couleurs (avant k-means) ===
    # Aplatit les zones visuellement uniformes en eliminant les micro-variations
    # de teinte (anti-aliasing interne, compression). Resultat : moins de
    # regions, plus pertinentes semantiquement.
    # Methodes :
    #   - 'none'       : pas de simplification (comportement initial)
    #   - 'median'     : medianBlur(strength*2+1) ; rapide, bon contre speckle
    #   - 'bilateral'  : bilateralFilter, lisse couleur + preserve bords nets
    #   - 'mean_shift' : pyrMeanShiftFiltering, aplats nets style "cartoon"
    simplify_method: str = "none"
    simplify_strength: int = 1  # intensite/iterations (selon methode)
    # === Trait vectorise via VTracer bw_polygon ===
    vectorize_ink: bool = True
    # === Rendu SVG ===
    # Stroke ajoute autour de chaque region SVG, de la MEME couleur que le fill.
    # Comble visuellement les halos blancs aux contours (alternative legere a
    # l'expansion Voronoi des regions). 0 = pas de stroke (comportement V3
    # historique). 2-3 px = halo elimine sur la plupart des images.
    region_stroke_width: int = 0


@dataclass
class ColoredRegion:
    color_id: int
    color_rgb: tuple[int, int, int]
    area: int
    bbox: tuple[int, int, int, int]
    points: list[tuple[int, int]]


@dataclass
class PaletteResult:
    name: str
    width: int
    height: int
    palette: list[tuple[int, int, int]] = field(default_factory=list)
    regions: list[ColoredRegion] = field(default_factory=list)
    ink_svg_inline: str = ""
    ink_mask_data_uri: str = ""    # PNG noir/blanc du masque trait
    ink_coverage_ratio: float = 0.0
    regions_coverage_ratio: float = 0.0
    elapsed_ms: float = 0.0
    # Propage le stroke_width pour le rendu (pris du preset utilise).
    region_stroke_width: int = 0


# === Etape -1 : posterization (quantification dure des canaux) ===============
def _posterize(img_bgr: np.ndarray, levels: int) -> np.ndarray:
    """Quantifie chaque canal RGB a N niveaux discrets.

    Ecrase toute variation < (256 / levels) par canal. Utilise pour eliminer
    le bruit invisible a l'oeil mais perceptible par k-means (un aplat jaune
    avec R variant de 240 a 244 = 1 seul niveau apres posterize).

    levels=8 -> 8x8x8 = 512 couleurs max
    levels=6 -> 216 couleurs max
    levels=4 -> 64 couleurs max (tres agressif)
    """
    if levels <= 0:
        return img_bgr
    step = max(1, 256 // levels)
    return ((img_bgr // step) * step).astype(np.uint8)


# === Etape 0 : pre-simplification des couleurs ================================
def _simplify_colors(img_bgr: np.ndarray, params: ExtractPaletteParams) -> np.ndarray:
    """Aplatit les couleurs avant segmentation, preserve les contours nets.

    Le but : reduire les micro-variations de teinte intra-region (anti-aliasing,
    compression JPEG, gradients legers) pour qu'un meme aplat visuel donne UNE
    seule region apres k-means + connected components, au lieu de N micro-regions.

    Methodes :
      - 'none'       : retourne img telle quelle.
      - 'median'     : medianBlur de taille (strength*2+1). Rapide, bon contre
                       le speckle. Peut adoucir les coins.
      - 'bilateral'  : bilateralFilter(d=9, sigmaColor=75, sigmaSpace=75) applique
                       'strength' fois. Lisse couleur + garantie bords nets.
      - 'mean_shift' : pyrMeanShiftFiltering(sp=21, sr=51) -- aplat "cartoon".
                       Le plus efficace pour ce cas d'usage mais le plus lent.
    """
    method = (params.simplify_method or "none").lower()
    strength = max(1, int(params.simplify_strength))

    if method == "none":
        return img_bgr

    if method == "median":
        ksize = max(3, strength * 2 + 1)
        if ksize % 2 == 0:
            ksize += 1
        return cv2.medianBlur(img_bgr, ksize)

    if method == "bilateral":
        out = img_bgr
        for _ in range(strength):
            out = cv2.bilateralFilter(out, 9, 75, 75)
        return out

    if method == "mean_shift":
        # sp = spatial radius, sr = color radius. Plus haut = plus aplati.
        sp = 21 + (strength - 1) * 8
        sr = 51 + (strength - 1) * 15
        return cv2.pyrMeanShiftFiltering(img_bgr, sp=sp, sr=sr)

    raise ValueError(f"simplify_method inconnu : {params.simplify_method}")


# === Etape 1 : masque trait noir =============================================
def _detect_ink_mask(img_bgr: np.ndarray, params: ExtractPaletteParams) -> np.ndarray:
    """Retourne un masque uint8 0/255 ou 255 = trait noir.

    Strategie combinee (OR) :
      - HSV : pixels sombres (V < ink_max_value) ET peu colores (S < ink_max_saturation).
      - Otsu grayscale (optionnel) : pixels classes "fond sombre" par seuillage global.
        Rattrape l'anti-aliasing entre trait noir et couleurs vives qui passe au
        travers du seul filtre HSV.
    Puis CLOSE morpho pour ressouder les gaps, et dilatation 1 px pour couvrir
    l'aliasing residuel.
    """
    if params.despeckle:
        img_bgr = cv2.medianBlur(img_bgr, 3)

    hsv = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2HSV)
    v = hsv[..., 2]
    s = hsv[..., 1]
    mask_hsv = (v < params.ink_max_value) & (s < params.ink_max_saturation)

    if params.use_otsu_grayscale:
        gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
        # Otsu donne un seuil T qui separe au mieux les 2 modes du histogramme.
        # Mais sur une image avec couleurs dominantes sombres, T peut etre > 100
        # et donc manger ces couleurs. On plafonne a otsu_max_threshold.
        t_otsu, _ = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        t_used = min(int(t_otsu), params.otsu_max_threshold)
        mask_otsu_dark = gray < t_used
        # Anti-faux-positif couleurs saturees sombres : un pixel n'est classe
        # trait via Otsu QUE si neutre (S < ink_otsu_max_saturation).
        # Empeche e.g. royal blue #0252FF (luma 78 mais S=99%) d'etre confondu
        # avec du trait noir. Inactif si seuil = 255 (comportement historique).
        if params.ink_otsu_max_saturation < 255:
            mask_otsu_dark = mask_otsu_dark & (s < params.ink_otsu_max_saturation)
        mask_combined = mask_hsv | mask_otsu_dark
    else:
        mask_combined = mask_hsv

    mask = mask_combined.astype(np.uint8) * 255

    # Filtre geodesique distance-based (option B 2026-06-01) : ne garder que
    # les pixels candidats a distance <= ink_geodesic_max_distance du "noir
    # vrai" (luma<30 AND S<30). Applique AVANT close/dilate.
    # Rationale : connectedComponents trop large car le noir et les zones
    # colorees sombres forment souvent UNE seule composante connexe (test
    # 01354 : bleu royal #0E24F1 a distance min 2px du noir mais distance
    # moyenne 17.6px - clairement zone separee spatialement).
    if params.ink_geodesic_enabled:
        ink_core = ((v < params.ink_core_luma_max) &
                    (s < params.ink_core_sat_max))
        if ink_core.any():
            try:
                from scipy.ndimage import distance_transform_edt
                dist_to_core = distance_transform_edt(~ink_core)
                keep = (mask > 0) & (dist_to_core <= params.ink_geodesic_max_distance)
                mask = (keep.astype(np.uint8) * 255)
            except ImportError:
                # scipy non disponible -> filtre desactive silencieusement
                pass

    if params.close_radius > 0:
        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE,
                                       (params.close_radius, params.close_radius))
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, k)

    if params.ink_dilate > 0:
        kd = cv2.getStructuringElement(cv2.MORPH_ELLIPSE,
                                        (2 * params.ink_dilate + 1, 2 * params.ink_dilate + 1))
        mask = cv2.dilate(mask, kd, iterations=1)

    return mask


# === Pipeline trait alternatif : skeleton + redilate ==========================
def _detect_ink_mask_skeleton(img_bgr: np.ndarray, params: ExtractPaletteParams) -> np.ndarray:
    """Pipeline trait avec normalisation thickness via skeletonize.

    Etapes :
        1. Detection PERMISSIVE (HSV elargi + Otsu permissif) : capture
           toute trace de trait, y compris l'anti-aliasing.
        2. CLOSE morpho (ink_skeleton_close_radius) : ressoude tous les
           micro-gaps invisibles.
        3. Connected components : on supprime les composantes < ink_min_speckle_px
           (speckles parasites, fragments isoles).
        4. skeletonize : ramene tout a 1 px d'epaisseur.
        5. Redilate (ink_target_thickness) : epaisseur finale uniforme.

    Resultat : trait CONTINU, FIN, epaisseur stable partout. Sans bouffer
    les couleurs sombres (le redilate final reste fin).
    """
    if params.despeckle:
        img_bgr = cv2.medianBlur(img_bgr, 3)

    # Detection permissive (capture tout, on filtrera ensuite).
    hsv = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2HSV)
    v = hsv[..., 2]
    s = hsv[..., 1]
    mask_hsv = (v < params.ink_permissive_v_max) & (s < params.ink_permissive_s_max)

    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    t_otsu, _ = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    # Otsu permissif : on autorise plus haut que la version 'simple' (otsu_max=90)
    t_used = min(int(t_otsu), params.otsu_max_threshold + 20)
    mask_otsu = gray < t_used

    mask = (mask_hsv | mask_otsu).astype(np.uint8) * 255

    # CLOSE pour ressouder.
    if params.ink_skeleton_close_radius > 0:
        k = cv2.getStructuringElement(
            cv2.MORPH_ELLIPSE,
            (params.ink_skeleton_close_radius, params.ink_skeleton_close_radius),
        )
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, k)

    # Filtre des speckles (composantes connexes < min_speckle_px).
    if params.ink_min_speckle_px > 0:
        n_lbl, lbl, stats, _ = cv2.connectedComponentsWithStats(
            (mask == 255).astype(np.uint8), connectivity=8
        )
        for i in range(1, n_lbl):
            if stats[i, cv2.CC_STAT_AREA] < params.ink_min_speckle_px:
                mask[lbl == i] = 0

    # Skeletonize → 1 px d'epaisseur partout.
    skel = _skimage_skeletonize(mask == 255).astype(np.uint8) * 255

    # Redilate a thickness uniforme.
    thick = max(1, int(params.ink_target_thickness))
    if thick > 1:
        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (thick, thick))
        out = cv2.dilate(skel, k, iterations=1)
    else:
        out = skel

    return out


# === Etape 2 bis : attribution PALETTE IMPOSEE (court-circuite k-means) =====
def _quantize_palette_forced(
    img_bgr: np.ndarray,
    ink_mask: np.ndarray,
    forced_palette_rgb: list,
) -> tuple[np.ndarray, np.ndarray]:
    """Attribue chaque pixel non-trait a la couleur de palette imposee la plus
    proche en LAB perceptuel.

    forced_palette_rgb : liste de (R, G, B) uint8.
    Retour : (label_img, palette_bgr) ou label = index dans la palette imposee.
    """
    h, w = img_bgr.shape[:2]
    non_ink = ink_mask == 0
    palette_arr = np.array(forced_palette_rgb, dtype=np.uint8)  # (K, 3) en RGB
    # On stocke en BGR pour le rendu (pipeline interne).
    palette_bgr = palette_arr[:, ::-1].copy()  # RGB -> BGR
    if not non_ink.any() or len(palette_bgr) == 0:
        return np.full((h, w), -1, dtype=np.int32), palette_bgr

    # Convertit palette + image en LAB.
    pal_3d = palette_bgr.reshape(1, -1, 3)
    pal_lab = cv2.cvtColor(pal_3d, cv2.COLOR_BGR2LAB).astype(np.float32).reshape(-1, 3)
    img_lab = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2LAB).astype(np.float32)
    pixels_lab = img_lab[non_ink]  # (N, 3)

    # Distance euclidienne LAB : pour chaque pixel, distance a chaque couleur palette.
    # Vectorise : on calcule la matrice des distances et on prend argmin.
    diffs = pixels_lab[:, None, :] - pal_lab[None, :, :]  # (N, K, 3)
    distances_sq = (diffs * diffs).sum(axis=2)  # (N, K)
    labels = distances_sq.argmin(axis=1).astype(np.int32)  # (N,)

    label_img = np.full((h, w), -1, dtype=np.int32)
    label_img[non_ink] = labels
    return label_img, palette_bgr


# === Etape 2 : k-means palette ===============================================
def _quantize_palette(img_bgr: np.ndarray, ink_mask: np.ndarray,
                       n_colors: int, attempts: int,
                       color_space: str = "bgr") -> tuple[np.ndarray, np.ndarray]:
    """K-means sur les pixels NON-trait. Retour (label_img, palette_bgr).

    label_img : ndarray int32 de meme shape que img, label par pixel (ou -1 = ink).
    palette_bgr : ndarray (n_colors, 3) uint8 -- toujours en BGR pour le rendu.

    ``color_space``:
        'bgr' = clustering euclidien BGR (rapide mais non perceptuel).
        'lab' = clustering en LAB perceptuel (recommande pour qualite max).
                Convertit BGR -> LAB, clustering en LAB, puis remappe les
                centres LAB -> BGR pour la palette de sortie.
    """
    h, w = img_bgr.shape[:2]
    non_ink = ink_mask == 0
    if not non_ink.any():
        return np.full((h, w), -1, dtype=np.int32), np.zeros((0, 3), dtype=np.uint8)

    if color_space == "lab":
        img_lab = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2LAB)
        pixels = img_lab[non_ink].astype(np.float32)
    else:
        pixels = img_bgr[non_ink].astype(np.float32)

    if len(pixels) < n_colors:
        return np.full((h, w), -1, dtype=np.int32), np.zeros((0, 3), dtype=np.uint8)

    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 10, 1.0)
    _compact, labels, centers = cv2.kmeans(
        pixels, n_colors, None, criteria, attempts, cv2.KMEANS_PP_CENTERS
    )
    label_img = np.full((h, w), -1, dtype=np.int32)
    label_img[non_ink] = labels.flatten()

    # Centres -> BGR pour le rendu uniforme.
    if color_space == "lab":
        # Centres en LAB (float) -> remap LAB uint8 -> BGR
        centers_lab = np.clip(centers, 0, 255).astype(np.uint8).reshape(1, -1, 3)
        centers_bgr = cv2.cvtColor(centers_lab, cv2.COLOR_LAB2BGR).reshape(-1, 3)
        return label_img, centers_bgr
    return label_img, centers.astype(np.uint8)


# === Etape 2.4 : fusion clusters proches (delta-E CIE76 en LAB) ==============
def _merge_similar_clusters(
    label_img: np.ndarray, palette_bgr: np.ndarray, delta_e_threshold: float
) -> tuple[np.ndarray, np.ndarray]:
    """Fusionne les clusters dont la distance LAB est < delta_e_threshold.

    Approche : union-find sur toutes les paires de couleurs, puis remapping.
    Reduit le nombre de couleurs effectives a celles qui sont visuellement
    distinctes (delta-E < 5 = imperceptible, < 10 = a peine perceptible).
    """
    if delta_e_threshold <= 0 or len(palette_bgr) < 2:
        return label_img, palette_bgr

    # Convertit la palette BGR -> LAB
    pal_3d = palette_bgr.reshape(1, -1, 3).astype(np.uint8)
    pal_lab = cv2.cvtColor(pal_3d, cv2.COLOR_BGR2LAB).reshape(-1, 3).astype(np.float32)

    n = len(pal_lab)
    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)

    # Fusion par seuil delta-E.
    for i in range(n):
        for j in range(i + 1, n):
            d = pal_lab[i] - pal_lab[j]
            delta_e = float(np.sqrt(np.dot(d, d)))
            if delta_e < delta_e_threshold:
                union(i, j)

    canonical = np.array([find(i) for i in range(n)], dtype=np.int32)
    unique_canonical = sorted(set(canonical.tolist()))
    remap = {old: new for new, old in enumerate(unique_canonical)}

    # Recalcule la palette : pour chaque cluster final, moyenne LAB des centres
    # originaux fusionnes, puis convertir en BGR.
    new_pal_lab = np.zeros((len(unique_canonical), 3), dtype=np.float32)
    counts = np.zeros(len(unique_canonical), dtype=np.int32)
    for old_id, canon in enumerate(canonical):
        new_id = remap[int(canon)]
        new_pal_lab[new_id] += pal_lab[old_id]
        counts[new_id] += 1
    new_pal_lab = new_pal_lab / np.maximum(counts[:, None], 1)
    new_pal_lab_uint8 = np.clip(new_pal_lab, 0, 255).astype(np.uint8).reshape(1, -1, 3)
    new_pal_bgr = cv2.cvtColor(new_pal_lab_uint8, cv2.COLOR_LAB2BGR).reshape(-1, 3)

    # Remappe label_img
    new_label_img = label_img.copy()
    for old_id in range(n):
        new_id = remap[int(canonical[old_id])]
        new_label_img[label_img == old_id] = new_id

    return new_label_img, new_pal_bgr


# === Etape 2.5b : isolation du vrai background ===============================
def _isolate_true_background(label_img: np.ndarray) -> np.ndarray:
    """Sépare le vrai fond extérieur des fragments intérieurs.

    Logique :
        1. Identifie le label background = label majoritaire sur les pixels de bord.
        2. Decompose ce label en composantes connexes.
        3. Composantes touchant le bord du canvas = vrai fond exterieur (preserve).
        4. Composantes ne touchant PAS le bord = fragments interieurs faussement
           classes en background. Reattribuees a leur region voisine non-fond
           la plus proche via distance_transform_edt.

    Retour : label_img modifie ou les fragments interieurs ont leur nouveau
    label de region voisine (au lieu du label background).
    """
    if (label_img < 0).all():
        return label_img.copy()
    h, w = label_img.shape

    # Label background = label majoritaire au bord.
    border = np.concatenate([
        label_img[0, :].ravel(),
        label_img[-1, :].ravel(),
        label_img[:, 0].ravel(),
        label_img[:, -1].ravel(),
    ])
    valid_border = border[border >= 0]
    if len(valid_border) == 0:
        return label_img.copy()
    unique, counts = np.unique(valid_border, return_counts=True)
    bg_label = int(unique[np.argmax(counts)])

    # Composantes connexes du background.
    bg_mask = (label_img == bg_label).astype(np.uint8)
    n_lbl, comp_lbl, stats, _ = cv2.connectedComponentsWithStats(bg_mask, connectivity=4)
    if n_lbl <= 1:
        return label_img.copy()

    out = label_img.copy()
    fragment_mask = np.zeros_like(label_img, dtype=bool)
    for i in range(1, n_lbl):
        x, y, ww, hh, _area = stats[i]
        # Touche le bord si x==0 ou y==0 ou x+ww==w ou y+hh==h.
        touches_border = (x <= 0 or y <= 0 or x + ww >= w or y + hh >= h)
        if not touches_border:
            fragment_mask |= (comp_lbl == i)

    if not fragment_mask.any():
        return out

    # Reattribution : pour chaque pixel fragment, trouver le pixel non-fond
    # non-fragment le plus proche via distance transform.
    non_bg_non_fragment = (label_img >= 0) & (label_img != bg_label)
    if not non_bg_non_fragment.any():
        # Si toutes les regions sont en fait du background, on ne peut pas
        # reattribuer -> on laisse tel quel.
        return out

    _distance, indices = distance_transform_edt(
        ~non_bg_non_fragment,
        return_indices=True,
    )
    nearest_y, nearest_x = indices
    out[fragment_mask] = label_img[nearest_y[fragment_mask], nearest_x[fragment_mask]]
    return out


# === Etape 2.5b' : isolation stricte via trait epaissi virtuel ==============
def _isolate_background_strict(
    label_img: np.ndarray,
    img_bgr: np.ndarray,
    thick_radius: int,
) -> np.ndarray:
    """Isolation forte du background via trait epaissi virtuel.

    Le ink_mask original a des gaps fins par lesquels le label background fuit
    a l'interieur de la silhouette. Solution : recalculer un masque trait
    EPAISSI (dilate de N px) qui ferme tous les gaps < 2N. ConnectedComponents
    sur l'inverse de ce masque epaissi distingue :
        - Composantes touchant le bord du canvas = vrai fond exterieur.
        - Composantes ne touchant pas le bord = interieur strict du sujet.

    Tout pixel du ``label_img`` dans le label background MAIS dans une
    composante "interieur strict" est reattribue a la region non-fond voisine
    la plus proche via distance_transform_edt.
    """
    if thick_radius <= 0:
        return label_img.copy()
    h, w = label_img.shape

    # Recalcule un masque trait epaissi sur l'image originale.
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    t_otsu, _ = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    t_used = min(int(t_otsu), 100)  # legerement permissif pour capter l'aliasing
    ink_thick = (gray < t_used).astype(np.uint8) * 255
    kk = cv2.getStructuringElement(cv2.MORPH_ELLIPSE,
                                    (2 * thick_radius + 1, 2 * thick_radius + 1))
    ink_thick = cv2.dilate(ink_thick, kk, iterations=1)

    # Composantes du papier (inverse du trait epaissi).
    paper = (ink_thick == 0).astype(np.uint8)
    n_comp, comp_lbl, stats, _ = cv2.connectedComponentsWithStats(paper, connectivity=4)
    if n_comp <= 1:
        return label_img.copy()

    # Determine quels comp_lbl sont "fond exterieur" (touchent le bord).
    bg_component_ids: set[int] = set()
    for i in range(1, n_comp):
        x, y, ww, hh, _area = stats[i]
        if x <= 0 or y <= 0 or x + ww >= w or y + hh >= h:
            bg_component_ids.add(i)

    if not bg_component_ids:
        return label_img.copy()

    # Identifie le label "background" dans label_img.
    border = np.concatenate([
        label_img[0, :].ravel(),
        label_img[-1, :].ravel(),
        label_img[:, 0].ravel(),
        label_img[:, -1].ravel(),
    ])
    valid_border = border[border >= 0]
    if len(valid_border) == 0:
        return label_img.copy()
    unique, counts = np.unique(valid_border, return_counts=True)
    bg_label = int(unique[np.argmax(counts)])

    # Masque interieur strict = pas dans bg_component_ids ni dans -1 (ink).
    interior_mask = np.zeros((h, w), dtype=bool)
    for i in range(1, n_comp):
        if i not in bg_component_ids:
            interior_mask |= (comp_lbl == i)

    # Pixels a reattribuer : ceux qui ont le bg_label MAIS sont dans l'interieur strict.
    to_reattribute = (label_img == bg_label) & interior_mask
    if not to_reattribute.any():
        return label_img.copy()

    # Reattribution via distance transform vers les pixels non-background.
    non_bg_non_target = (label_img >= 0) & (label_img != bg_label)
    if not non_bg_non_target.any():
        return label_img.copy()
    _distance, indices = distance_transform_edt(
        ~non_bg_non_target,
        return_indices=True,
    )
    nearest_y, nearest_x = indices
    out = label_img.copy()
    out[to_reattribute] = label_img[nearest_y[to_reattribute], nearest_x[to_reattribute]]
    return out


# === Etape 2.5b'' : isolation par DETECTION COULEUR DU FOND =================
def _isolate_background_by_color(
    label_img: np.ndarray,
    img_bgr: np.ndarray,
    delta_e_threshold: float,
    corner_size: int = 10,
) -> np.ndarray:
    """Detecte le vrai fond par sa COULEUR (sampling des coins) et reattribue
    les pixels du label background qui ne sont PAS de cette couleur.

    Approche semantique : la connectivite topologique echoue quand le fond
    fuit dans la silhouette via des gaps trop larges. La COULEUR est invariante.

    Algorithme :
        1. Sample 4 coins du canvas (corner_size x corner_size pixels).
        2. Couleur moyenne BGR -> LAB de reference.
        3. Pour chaque pixel : distance LAB a la couleur de reference.
        4. Pixels avec distance < delta_e_threshold = vrai fond.
        5. Identifie le bg_label dans label_img (majoritaire au bord).
        6. Tout pixel label==bg_label MAIS distance >= seuil = fragment interieur
           -> reattribue a la region non-fond voisine la plus proche (Voronoi).
    """
    if delta_e_threshold <= 0:
        return label_img.copy()
    h, w = label_img.shape
    cs = max(2, int(corner_size))

    # Sample 4 coins.
    corners = np.concatenate([
        img_bgr[:cs, :cs].reshape(-1, 3),
        img_bgr[:cs, -cs:].reshape(-1, 3),
        img_bgr[-cs:, :cs].reshape(-1, 3),
        img_bgr[-cs:, -cs:].reshape(-1, 3),
    ], axis=0).astype(np.float32)
    bg_color_bgr = corners.mean(axis=0).reshape(1, 1, 3).astype(np.uint8)
    bg_color_lab = cv2.cvtColor(bg_color_bgr, cv2.COLOR_BGR2LAB).astype(np.float32)[0, 0]

    # Distance LAB pour chaque pixel.
    img_lab = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2LAB).astype(np.float32)
    diff = img_lab - bg_color_lab
    distance = np.sqrt((diff * diff).sum(axis=2))
    is_bg_color = (distance < delta_e_threshold)

    # Identifie bg_label dans label_img.
    border = np.concatenate([
        label_img[0, :].ravel(),
        label_img[-1, :].ravel(),
        label_img[:, 0].ravel(),
        label_img[:, -1].ravel(),
    ])
    valid_border = border[border >= 0]
    if len(valid_border) == 0:
        return label_img.copy()
    unique, counts = np.unique(valid_border, return_counts=True)
    bg_label = int(unique[np.argmax(counts)])

    # Pixels a reattribuer = label==bg_label MAIS pas dans bg_color_mask.
    to_reattribute = (label_img == bg_label) & ~is_bg_color
    if not to_reattribute.any():
        return label_img.copy()

    # Réattribution via distance transform vers pixels non-background.
    non_bg_non_target = (label_img >= 0) & (label_img != bg_label)
    if not non_bg_non_target.any():
        return label_img.copy()
    _distance, indices = distance_transform_edt(
        ~non_bg_non_target,
        return_indices=True,
    )
    nearest_y, nearest_x = indices
    out = label_img.copy()
    out[to_reattribute] = label_img[nearest_y[to_reattribute], nearest_x[to_reattribute]]
    return out


# === Etape 2.5d : SILHOUETTE SPLIT (approche structurelle) ==================
def _detect_silhouette_mask(
    img_bgr: np.ndarray,
    corner_size: int = 10,
    close_radius: int = 5,
    method: str = "kmeans2",
    ink_mask: np.ndarray | None = None,
) -> np.ndarray:
    """Detecte un masque binaire de la silhouette du sujet (255 = interieur).

    Methodes :
        - 'kmeans2' (DEFAUT, robuste) : k-means k=2 sur l'image LAB (hors trait).
            Le cluster majoritaire au bord = fond ; l'autre = silhouette.
            Force exactement 2 modes par construction, robuste meme quand le
            fond est tres proche du sujet (par ex pastel sur fond blanc).
        - 'otsu_distance' : couleur des 4 coins -> distance LAB -> Otsu auto.
            Echoue quand le sujet est trop proche du fond (Otsu trouve un
            seuil trop eleve).
    """
    h, w = img_bgr.shape[:2]

    if method == "kmeans2":
        # === K-means k=2 sur image LAB (hors trait) =========================
        img_lab = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2LAB).astype(np.float32)
        if ink_mask is not None:
            non_ink = ink_mask == 0
            pixels = img_lab[non_ink].reshape(-1, 3)
        else:
            non_ink = np.ones((h, w), dtype=bool)
            pixels = img_lab.reshape(-1, 3)

        if len(pixels) < 2:
            return np.zeros((h, w), dtype=np.uint8)

        criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 10, 1.0)
        _, labels, centers = cv2.kmeans(pixels, 2, None, criteria, 5, cv2.KMEANS_PP_CENTERS)

        # Reconstruct full label map (-1 = ink).
        full_labels = np.full((h, w), -1, dtype=np.int32)
        full_labels[non_ink] = labels.flatten()

        # Le cluster qui domine les bords = fond.
        border_arr = np.concatenate([
            full_labels[0, :].ravel(),
            full_labels[-1, :].ravel(),
            full_labels[:, 0].ravel(),
            full_labels[:, -1].ravel(),
        ])
        border_valid = border_arr[border_arr >= 0]
        if len(border_valid) == 0:
            return np.zeros((h, w), dtype=np.uint8)
        bg_cluster = int(np.bincount(border_valid).argmax())

        # Silhouette = l'AUTRE cluster (+ le trait, qui appartient au sujet).
        silhouette = (full_labels != bg_cluster).astype(np.uint8) * 255
        if ink_mask is not None:
            silhouette[ink_mask == 255] = 255  # le trait fait partie du sujet
    else:
        # === OTSU sur distance LAB depuis couleur coins (fallback) ==========
        cs = max(2, int(corner_size))
        corners = np.concatenate([
            img_bgr[:cs, :cs].reshape(-1, 3),
            img_bgr[:cs, -cs:].reshape(-1, 3),
            img_bgr[-cs:, :cs].reshape(-1, 3),
            img_bgr[-cs:, -cs:].reshape(-1, 3),
        ], axis=0).astype(np.float32)
        bg_color_bgr = corners.mean(axis=0).reshape(1, 1, 3).astype(np.uint8)
        bg_color_lab = cv2.cvtColor(bg_color_bgr, cv2.COLOR_BGR2LAB).astype(np.float32)[0, 0]

        img_lab = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2LAB).astype(np.float32)
        diff = img_lab - bg_color_lab
        distance = np.sqrt((diff * diff).sum(axis=2))
        distance_u8 = np.clip(distance, 0, 255).astype(np.uint8)
        _, silhouette = cv2.threshold(
            distance_u8, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU
        )

    # === Morpho close : lisse contour + ferme micro-trous =================
    if close_radius > 0:
        k = cv2.getStructuringElement(
            cv2.MORPH_ELLIPSE, (2 * close_radius + 1, 2 * close_radius + 1)
        )
        silhouette = cv2.morphologyEx(silhouette, cv2.MORPH_CLOSE, k)

    # === Garde la composante connexe principale ============================
    n, comp, stats, _ = cv2.connectedComponentsWithStats(silhouette, connectivity=4)
    if n > 1:
        max_area = 0
        max_label = 1
        for i in range(1, n):
            if stats[i, cv2.CC_STAT_AREA] > max_area:
                max_area = int(stats[i, cv2.CC_STAT_AREA])
                max_label = i
        silhouette = ((comp == max_label).astype(np.uint8)) * 255

    return silhouette


def _split_regions_by_silhouette(
    label_img: np.ndarray,
    palette_bgr: np.ndarray,
    img_bgr: np.ndarray,
    silhouette_mask: np.ndarray,
    min_overlap_ratio: float = 0.05,
) -> tuple[np.ndarray, np.ndarray]:
    """Split chaque cluster k-means qui chevauche la frontiere silhouette/fond.

    Pour chaque composante connexe d'un cluster k-means :
        ratio_interior = pixels dans silhouette / total
        Si min_overlap_ratio < ratio_interior < (1 - min_overlap_ratio) :
            -> chevauchement : split en 2 sous-regions distinctes.
            La partie majoritaire garde le label original.
            La partie minoritaire recoit un NOUVEAU label, avec une nouvelle
            couleur (moyenne BGR des pixels minoritaires).

    Retour : (label_img_modifie, palette_etendue).
    """
    out = label_img.copy()
    new_palette: list[np.ndarray] = list(palette_bgr)
    next_label = int(out.max()) + 1 if out.max() >= 0 else 0

    is_interior = silhouette_mask == 255

    unique_labels = sorted(set(int(l) for l in np.unique(out) if l >= 0))
    for label_id in unique_labels:
        mask = (out == label_id).astype(np.uint8)
        n, comp, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=4)
        for i in range(1, n):
            comp_pixels = (comp == i)
            total = int(comp_pixels.sum())
            if total == 0:
                continue
            interior_count = int((comp_pixels & is_interior).sum())
            ratio_interior = interior_count / total

            if ratio_interior <= min_overlap_ratio:
                continue  # composante quasi-entierement hors silhouette
            if ratio_interior >= (1 - min_overlap_ratio):
                continue  # composante quasi-entierement dans silhouette

            # Chevauchement : on split en 2.
            if ratio_interior > 0.5:
                # Majoritaire = interieur (garde label_id).
                # Minoritaire = exterieur (nouveau label).
                minority = comp_pixels & ~is_interior
            else:
                # Majoritaire = exterieur (garde label_id).
                # Minoritaire = interieur (nouveau label).
                minority = comp_pixels & is_interior

            if not minority.any():
                continue

            # Couleur moyenne BGR des pixels minoritaires.
            mean_color = img_bgr[minority].mean(axis=0).astype(np.uint8)
            new_palette.append(mean_color)
            out[minority] = next_label
            next_label += 1

    new_palette_arr = np.array(new_palette, dtype=np.uint8)
    return out, new_palette_arr


# === Etape 2.5e : DETECTION ANOMALIE + split local ==========================
def _detect_and_split_anomalies(
    label_img: np.ndarray,
    palette_bgr: np.ndarray,
    img_bgr: np.ndarray,
    size_pct_threshold: float = 0.30,
    min_delta_e: float = 10.0,
    max_passes: int = 2,
) -> tuple[np.ndarray, np.ndarray]:
    """Detecte les composantes anormalement grandes et tente un split local.

    Pour chaque composante connexe d'aire > size_pct_threshold du canvas :
        1. Re-k-means k=2 LAB sur les pixels de la composante uniquement.
        2. Calcule delta-E LAB entre les 2 sous-clusters.
        3. Si delta-E < min_delta_e : composante homogene, on laisse tel quel
           (split non justifie).
        4. Sinon : un des 2 sous-clusters doit toucher le bord du canvas
           (= fond exterieur) et l'autre non (= interieur). Si ce critere
           est rempli, le sous-cluster interieur recoit un NOUVEAU label.

    Plusieurs passes : un split peut creer de nouvelles composantes encore
    > seuil, qu'on resplit dans la passe suivante.

    Retour : (label_img_modifie, palette_etendue).
    """
    h, w = label_img.shape
    canvas_size = h * w
    expected_max_size = canvas_size * size_pct_threshold

    out = label_img.copy()
    new_palette: list[np.ndarray] = list(palette_bgr)
    next_label = (int(out.max()) + 1) if (out.max() >= 0) else 0

    img_lab = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2LAB).astype(np.float32)

    for _pass in range(max_passes):
        any_split = False
        unique_labels = sorted(set(int(l) for l in np.unique(out) if l >= 0))
        for label_id in unique_labels:
            mask = (out == label_id).astype(np.uint8)
            n_comp, comp_lbl, stats, _ = cv2.connectedComponentsWithStats(
                mask, connectivity=4
            )
            for i in range(1, n_comp):
                area = int(stats[i, cv2.CC_STAT_AREA])
                if area <= expected_max_size:
                    continue
                # Composante anormalement grande -> tenter split.
                comp_mask = (comp_lbl == i)
                pixels_lab = img_lab[comp_mask]
                if len(pixels_lab) < 100:
                    continue
                # Re-k-means k=2 sur les pixels LAB.
                criteria = (
                    cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 10, 1.0
                )
                _, sub_labels, centers = cv2.kmeans(
                    pixels_lab.astype(np.float32),
                    2, None, criteria, 5, cv2.KMEANS_PP_CENTERS,
                )
                # Delta-E LAB entre les 2 centres.
                d = centers[0] - centers[1]
                delta_e = float(np.sqrt((d * d).sum()))
                if delta_e < min_delta_e:
                    continue  # composante homogene en couleur, pas de split

                # Reconstruction du sub-mask : 0 ou 1 pour chaque pixel de la
                # composante.
                sub_label_img = np.full((h, w), -1, dtype=np.int32)
                sub_label_img[comp_mask] = sub_labels.flatten()

                # Determine quel sous-cluster touche le bord du canvas.
                border_arr = np.concatenate([
                    sub_label_img[0, :].ravel(),
                    sub_label_img[-1, :].ravel(),
                    sub_label_img[:, 0].ravel(),
                    sub_label_img[:, -1].ravel(),
                ])
                border_valid = border_arr[border_arr >= 0]
                touches_0 = int((border_valid == 0).sum())
                touches_1 = int((border_valid == 1).sum())

                if touches_0 > 0 and touches_1 > 0:
                    # Les 2 sous-clusters touchent le bord : pas de separation
                    # nette fond/interieur. On split quand meme (le sous-cluster
                    # avec MOINS de pixels au bord = interieur).
                    if touches_0 < touches_1:
                        interior_sub = 0
                    else:
                        interior_sub = 1
                elif touches_0 == 0 and touches_1 > 0:
                    interior_sub = 0
                elif touches_1 == 0 and touches_0 > 0:
                    interior_sub = 1
                else:
                    # Aucun touche le bord (composante entierement interieure ?).
                    # On ne split pas dans ce cas.
                    continue

                interior_mask = sub_label_img == interior_sub
                if not interior_mask.any():
                    continue

                # Nouveau label avec couleur moyenne BGR.
                mean_color = img_bgr[interior_mask].mean(axis=0).astype(np.uint8)
                new_palette.append(mean_color)
                out[interior_mask] = next_label
                next_label += 1
                any_split = True

        if not any_split:
            break

    new_palette_arr = np.array(new_palette, dtype=np.uint8)
    return out, new_palette_arr


# === Etape 2.5c : fusion semantique des petites regions =====================
def _merge_small_regions(label_img: np.ndarray, min_area: int, max_passes: int = 3) -> np.ndarray:
    """Fusionne chaque composante < min_area dans son label voisin majoritaire.

    Algorithme :
        Pour chaque label_id present dans label_img :
            Trouve les composantes connexes (4-connectivity) de ce label.
            Pour chaque composante d'aire < min_area :
                Dilate d'1 px -> frontiere etendue
                Compte les labels de la frontiere (excluant le label courant et -1=ink)
                Reattribue la composante au label majoritaire trouve.
        Repete jusqu'a ce qu'aucune fusion ne soit faite (ou max_passes atteint).
    """
    if min_area <= 0:
        return label_img.copy()

    out = label_img.copy()
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))

    for _pass in range(max_passes):
        any_merged = False
        unique_labels = sorted(set(int(l) for l in np.unique(out) if l >= 0))
        for label_id in unique_labels:
            mask = (out == label_id).astype(np.uint8)
            n_lbl, comp_lbl, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=4)
            for i in range(1, n_lbl):
                area = int(stats[i, cv2.CC_STAT_AREA])
                if area >= min_area:
                    continue
                comp_mask = (comp_lbl == i).astype(np.uint8)
                dilated = cv2.dilate(comp_mask, kernel, iterations=1)
                border = (dilated == 1) & (comp_mask == 0)
                border_labels = out[border]
                valid = border_labels[(border_labels >= 0) & (border_labels != label_id)]
                if len(valid) == 0:
                    continue
                unique_n, counts_n = np.unique(valid, return_counts=True)
                new_label = int(unique_n[np.argmax(counts_n)])
                out[comp_lbl == i] = new_label
                any_merged = True
        if not any_merged:
            break

    return out


# === Etape 2.6 : morpho cleanup intra-label ==================================
def _morpho_cleanup_labels(label_img: np.ndarray, radius: int) -> np.ndarray:
    """Pour chaque label, applique OPEN puis CLOSE pour eliminer les speckles
    et combler les micro-trous. Les pixels retires deviennent -1 (orphelins).

    Si tu veux les ré-attribuer ensuite, lance _expand_regions_to_ink dessus.
    """
    if radius <= 0:
        return label_img

    out = label_img.copy()
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (radius, radius))

    for label_id in np.unique(label_img):
        if label_id < 0:
            continue
        mask = (label_img == label_id).astype(np.uint8)
        cleaned = cv2.morphologyEx(mask, cv2.MORPH_OPEN, k)
        cleaned = cv2.morphologyEx(cleaned, cv2.MORPH_CLOSE, k)
        # Pixels qui etaient dans le label mais sont maintenant orphelins.
        diff = (mask == 1) & (cleaned == 0)
        out[diff] = -1
        # Pixels qui n'etaient pas dans le label mais le sont maintenant (CLOSE)
        # -> ne pas envahir un autre label, on garde out[gain] = label_id
        # seulement si out[gain] valait deja label_id ou -1.
        gain = (mask == 0) & (cleaned == 1)
        safe_gain = gain & ((out == -1) | (out == label_id))
        out[safe_gain] = label_id

    return out


# === Etape 2.5 : extension Voronoi des regions vers le trait ================
def _expand_regions_to_ink(label_img: np.ndarray, max_distance: int = 0) -> np.ndarray:
    """Etend chaque region jusqu'aux pixels du trait via nearest-region (Voronoi).

    Pour chaque pixel ink (label == -1), trouve le pixel non-ink le plus proche
    en distance euclidienne, et lui attribue son label.

    ``max_distance`` : si > 0, les pixels a distance > max_distance restent -1
    (utile pour eviter qu'une region traverse un gros bloc d'artefacts noirs).
    Par defaut 0 = pas de limite, ce qui convient au cas line-art ou le trait
    est partout fin.
    """
    non_ink_mask = label_img >= 0
    if non_ink_mask.all() or not non_ink_mask.any():
        return label_img.copy()

    # distance_transform_edt(input) : pour chaque pixel a True, calcule la
    # distance au pixel a False le plus proche. On veut l'inverse : pour chaque
    # pixel ink, trouver le non-ink le plus proche -> on passe ~non_ink_mask.
    # return_indices=True donne (y_nearest, x_nearest) pour chaque pixel a True.
    distance, indices = distance_transform_edt(
        ~non_ink_mask,
        return_indices=True,
    )
    nearest_y, nearest_x = indices

    out = label_img.copy()
    ink_pixels = ~non_ink_mask
    out[ink_pixels] = label_img[nearest_y[ink_pixels], nearest_x[ink_pixels]]

    if max_distance > 0:
        out[distance > max_distance] = -1

    return out


# === Etape 3 : regions par couleur ============================================
def _simplify_contour(contour: np.ndarray, ratio: float) -> list[tuple[int, int]]:
    epsilon = max(1.0, ratio * cv2.arcLength(contour, True))
    approx = cv2.approxPolyDP(contour, epsilon, True)
    return [(int(p[0][0]), int(p[0][1])) for p in approx]


def _regions_for_color(
    label_img: np.ndarray,
    color_id: int,
    color_bgr: tuple[int, int, int],
    min_area: int,
    max_regions: int,
    simplify_ratio: float,
) -> list[ColoredRegion]:
    """Composantes connexes pour une couleur donnee."""
    mask = (label_img == color_id).astype(np.uint8)
    n, comp_labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=4)
    regions: list[ColoredRegion] = []
    cands = sorted(
        ((i, int(stats[i, cv2.CC_STAT_AREA])) for i in range(1, n) if stats[i, cv2.CC_STAT_AREA] >= min_area),
        key=lambda x: -x[1],
    )[:max_regions]
    for comp_id, area in cands:
        comp_mask = (comp_labels == comp_id).astype(np.uint8) * 255
        contours, _ = cv2.findContours(comp_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            continue
        contour = max(contours, key=cv2.contourArea)
        if len(contour) < 4:
            continue
        points = _simplify_contour(contour, simplify_ratio)
        if len(points) < 3:
            continue
        x, y, w, h = (
            int(stats[comp_id, cv2.CC_STAT_LEFT]),
            int(stats[comp_id, cv2.CC_STAT_TOP]),
            int(stats[comp_id, cv2.CC_STAT_WIDTH]),
            int(stats[comp_id, cv2.CC_STAT_HEIGHT]),
        )
        # BGR -> RGB pour le rendu SVG.
        color_rgb = (int(color_bgr[2]), int(color_bgr[1]), int(color_bgr[0]))
        regions.append(ColoredRegion(
            color_id=color_id,
            color_rgb=color_rgb,
            area=area,
            bbox=(x, y, w, h),
            points=points,
        ))
    return regions


# === Etape 4 : vectorise le trait via VTracer ================================
def _vtracer_ink_svg(ink_mask: np.ndarray) -> str:
    """Genere le layer encre vectoriel via VTracer (bw_polygon).

    ``ink_mask`` est 0/255 ou 255 = trait. On l'inverse pour VTracer (qui
    trace les pixels SOMBRES).
    """
    # VTracer attend du PNG : on ecrit le masque inverse (trait en noir).
    inverted = 255 - ink_mask
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp_png:
        png_path = Path(tmp_png.name)
    with tempfile.NamedTemporaryFile(suffix=".svg", delete=False) as tmp_svg:
        svg_path = Path(tmp_svg.name)
    try:
        cv2.imwrite(str(png_path), inverted)
        vtracer.convert_image_to_svg_py(
            str(png_path), str(svg_path),
            colormode="binary", hierarchical="stacked", mode="polygon",
            filter_speckle=4, corner_threshold=60, splice_threshold=45, path_precision=3,
        )
        svg = svg_path.read_text(encoding="utf-8", errors="replace")
        if svg.startswith("<?xml"):
            svg = svg.split("?>", 1)[-1].lstrip()
        return svg
    finally:
        for p in (png_path, svg_path):
            try:
                p.unlink()
            except OSError:
                pass


_SVG_OPEN_RE = re.compile(r"<svg\b[^>]*>", re.IGNORECASE)
_SVG_CLOSE_RE = re.compile(r"</svg\s*>", re.IGNORECASE)


def _extract_svg_inner(svg_text: str) -> str:
    om = _SVG_OPEN_RE.search(svg_text)
    cm = _SVG_CLOSE_RE.search(svg_text)
    if not om or not cm:
        return svg_text
    return svg_text[om.end():cm.start()].strip()


# === Pipeline principal ======================================================
def _split_heterogeneous_component(
    img_bgr: np.ndarray,
    comp_mask: np.ndarray,
    comp_area: int,
    std_threshold: float = 25.0,
    k: int = 4,
    min_subcluster_pct: float = 0.05,
    min_basin: int = 50,
) -> list[tuple[np.ndarray, np.ndarray]] | None:
    """K-means LAB local sur les pixels d'une composante connexe.

    Quand une composante (issue de connectedComponentsWithStats sur le sujet)
    est chromatiquement heterogene (std LAB > threshold), elle resulte
    probablement de la fusion de plusieurs regions adjacentes que le trait
    noir n'a pas suffi a separer. Cette fonction split ces composantes en
    sous-regions via k-means LAB local + connectedComponents par cluster.

    Retourne :
        None si composante homogene OU si le split n'aboutit qu'a 1 sous-region.
        Liste de (sub_mask_bool, mean_bgr_uint8) sinon.
    """
    pixels_bgr = img_bgr[comp_mask]
    if len(pixels_bgr) < max(k, 4):
        return None

    pixels_lab = cv2.cvtColor(
        pixels_bgr.reshape(-1, 1, 3).astype(np.uint8),
        cv2.COLOR_BGR2LAB,
    ).astype(np.float32).reshape(-1, 3)

    std_norm = float(np.linalg.norm(pixels_lab.std(axis=0)))
    if std_norm < std_threshold:
        return None  # composante homogene, pas de split necessaire

    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 10, 1.0)
    _, kmeans_labels, _ = cv2.kmeans(
        pixels_lab, k, None, criteria, 5, cv2.KMEANS_PP_CENTERS,
    )
    kmeans_labels = kmeans_labels.flatten()

    indices_2d = np.argwhere(comp_mask)  # (N, 2) en [y, x]
    min_pixels = max(min_basin, int(min_subcluster_pct * comp_area))

    results: list[tuple[np.ndarray, np.ndarray]] = []
    for k_id in range(k):
        sub_indices = indices_2d[kmeans_labels == k_id]
        if len(sub_indices) < min_pixels:
            continue
        sub_mask_u8 = np.zeros(comp_mask.shape, dtype=np.uint8)
        sub_mask_u8[sub_indices[:, 0], sub_indices[:, 1]] = 255
        # connectedComponents pour separer les iles disjointes d'un meme cluster
        n_sub, sub_lbls, sub_stats, _ = cv2.connectedComponentsWithStats(
            sub_mask_u8, connectivity=4,
        )
        for sl in range(1, n_sub):
            sl_area = int(sub_stats[sl, cv2.CC_STAT_AREA])
            if sl_area < min_basin:
                continue
            sl_mask = (sub_lbls == sl)
            sl_pixels = img_bgr[sl_mask]
            sl_mean_bgr = sl_pixels.mean(axis=0).astype(np.uint8)
            results.append((sl_mask, sl_mean_bgr))

    # Split valide seulement s'il produit >= 2 sous-regions
    return results if len(results) >= 2 else None


def _detect_chromakey_mask(img_bgr: np.ndarray, chromakey_rgb: tuple,
                            delta_e: float) -> np.ndarray:
    """Masque binaire des pixels chromakey (255 = pixel chromakey).

    Distance LAB perceptuelle a la couleur chromakey de reference. Robuste car
    le chromakey green standard cinema (#00B140) est tres eloigne de toute
    teinte pastel (delta-E > 80 vs n'importe quelle pastel).
    """
    r, g, b = chromakey_rgb
    chromakey_bgr = np.array([[[b, g, r]]], dtype=np.uint8)
    chromakey_lab = cv2.cvtColor(chromakey_bgr, cv2.COLOR_BGR2LAB).astype(np.float32)[0, 0]
    img_lab = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2LAB).astype(np.float32)
    diff = img_lab - chromakey_lab
    distance = np.sqrt((diff * diff).sum(axis=2))
    return (distance < delta_e).astype(np.uint8) * 255


def _extract_via_floodfill(png_path: Path, params: ExtractPaletteParams) -> PaletteResult:
    """Pipeline alternatif : composantes connexes des pixels libres apres
    exclusion du chromakey et du trait noir.

    Etapes :
        1. Detection chromakey (distance LAB).
        2. Detection trait noir (reutilise _detect_ink_mask).
        3. Optionnel : dilate trait (bouche gaps fins avant flood).
        4. available_mask = NOT (chromakey OR trait_dilate)
        5. cv2.connectedComponentsWithStats(available_mask) = chaque composante
           = une region (equivalent a 1 flood-fill iteratif depuis chaque seed).
        6. Pour chaque region : couleur moyenne BGR + ajout au label_img.
        7. Ajoute le fond chromakey comme un label dedie (pour rendu + lock_bg).
        8. Vectorise le trait via VTracer (independant, comme le pipeline standard).
        9. Compose le PaletteResult standard.
    """
    t0 = time.perf_counter()
    img_bgr = cv2.imread(str(png_path), cv2.IMREAD_COLOR)
    if img_bgr is None:
        raise ValueError(f"Lecture impossible : {png_path}")
    h, w = img_bgr.shape[:2]

    # 0. Pre-extraction et injection du trait (strategie adoptee 2026-06-01)
    # Avant de detecter le ink_mask normal, on extrait le trait avec un filtre
    # HSV STRICT pur (V<ink_max_value AND S<ink_max_saturation, sans Otsu OR
    # ni geodesic) et on peint du noir pur (0,0,0) dans l'image source aux
    # pixels du trait. Le pipeline normal voit ensuite un noir parfait au lieu
    # d'un trait teinte/satureé, donc les couleurs vives sombres (ex royal
    # blue luma 78) restent intactes dans les regions.
    if params.preextract_ink_inject:
        from dataclasses import replace as _dc_replace
        params_strict = _dc_replace(
            params,
            use_otsu_grayscale=False,
            ink_geodesic_enabled=False,
            ink_dilate=0,
            close_radius=0,
        )
        pre_mask = _detect_ink_mask(img_bgr, params_strict)
        if (pre_mask > 0).any():
            img_bgr = img_bgr.copy()
            img_bgr[pre_mask > 0] = (0, 0, 0)

    # 1. Masque chromakey
    chromakey_mask = _detect_chromakey_mask(
        img_bgr, params.chromakey_rgb, params.chromakey_delta_e,
    )

    # 2. Masque trait noir (reutilise le detecteur standard)
    if params.ink_pipeline == "skeleton":
        ink_mask = _detect_ink_mask_skeleton(img_bgr, params)
    else:
        ink_mask = _detect_ink_mask(img_bgr, params)

    # 3. Trait renforce (pour flood : bouche gaps fins eventuels)
    ink_mask_for_flood = ink_mask
    if params.flood_pre_dilate > 0:
        r = params.flood_pre_dilate
        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r + 1, 2 * r + 1))
        ink_mask_for_flood = cv2.dilate(ink_mask, k, iterations=1)

    # 4. Pixels disponibles pour les regions interieures
    barriers = (ink_mask_for_flood == 255) | (chromakey_mask == 255)
    available_mask = (~barriers).astype(np.uint8)

    # 5. Composantes connexes = regions
    n_comp, comp_labels, stats, _ = cv2.connectedComponentsWithStats(
        available_mask, connectivity=4,
    )

    # 6. Construction label_img + palette
    min_basin = max(1, int(params.flood_min_region_area_px))
    label_img = np.full((h, w), -1, dtype=np.int32)
    palette_list: list = []
    next_label = 0

    # Tri des composantes par aire decroissante (rendu coherent).
    candidates = sorted(
        ((i, int(stats[i, cv2.CC_STAT_AREA])) for i in range(1, n_comp)),
        key=lambda x: -x[1],
    )
    for comp_id, area in candidates:
        if area < min_basin:
            continue
        mask = (comp_labels == comp_id)

        # Split heterogene optionnel : k-means LAB local si composante
        # chromatiquement heterogene (fusion par connectivite avec trait
        # noir discontinu entre regions adjacentes).
        if params.floodfill_split_heterogeneous:
            sub_regions = _split_heterogeneous_component(
                img_bgr, mask, int(area),
                std_threshold=params.floodfill_split_std_threshold,
                k=params.floodfill_split_k,
                min_subcluster_pct=params.floodfill_split_min_subcluster_pct,
                min_basin=min_basin,
            )
            if sub_regions is not None:
                for sub_mask, sub_bgr in sub_regions:
                    label_img[sub_mask] = next_label
                    palette_list.append(sub_bgr.copy())
                    next_label += 1
                continue  # composante traitee par split

        # Pas de split (homogene OU feature desactivee) : traitement normal
        mean_color_bgr = img_bgr[mask].mean(axis=0).astype(np.uint8)
        label_img[mask] = next_label
        palette_list.append(mean_color_bgr.copy())
        next_label += 1

    # 7. Fond chromakey comme dernier label
    if chromakey_mask.any():
        # On lui donne sa couleur reelle (chromakey green), pas la moyenne
        r_, g_, b_ = params.chromakey_rgb
        chromakey_bgr_uint = np.array([b_, g_, r_], dtype=np.uint8)
        label_img[chromakey_mask == 255] = next_label
        palette_list.append(chromakey_bgr_uint)
        next_label += 1

    palette_bgr_arr = (
        np.array(palette_list, dtype=np.uint8)
        if palette_list else np.zeros((0, 3), dtype=np.uint8)
    )

    # 8. Vectorise le trait noir (independant)
    ink_svg = _vtracer_ink_svg(ink_mask) if params.vectorize_ink else ""
    ink_mask_uri = _ndarray_to_data_uri(ink_mask)

    # 9. Extraction des contours par region (reutilise _regions_for_color)
    min_area_for_regions = max(50, int(params.min_region_area_ratio * h * w))
    all_regions: list[ColoredRegion] = []
    for color_id in range(len(palette_bgr_arr)):
        bgr = tuple(int(c) for c in palette_bgr_arr[color_id])
        all_regions.extend(_regions_for_color(
            label_img, color_id, bgr,
            min_area=min_area_for_regions,
            max_regions=params.max_regions_per_color,
            simplify_ratio=params.simplify_ratio,
        ))
    all_regions.sort(key=lambda r: -r.area)

    # 10. Composition PaletteResult standard
    ink_coverage = float((ink_mask == 255).sum()) / float(h * w)
    regions_coverage = float(sum(r.area for r in all_regions)) / float(h * w)
    palette_rgb = [(int(c[2]), int(c[1]), int(c[0])) for c in palette_bgr_arr]
    elapsed = (time.perf_counter() - t0) * 1000.0

    return PaletteResult(
        name=png_path.stem,
        width=w,
        height=h,
        palette=palette_rgb,
        regions=all_regions,
        ink_svg_inline=ink_svg,
        ink_mask_data_uri=ink_mask_uri,
        ink_coverage_ratio=ink_coverage,
        regions_coverage_ratio=regions_coverage,
        elapsed_ms=elapsed,
        region_stroke_width=int(params.region_stroke_width),
    )


def extract_palette(png_path: Path, params: ExtractPaletteParams | None = None) -> PaletteResult:
    params = params or ExtractPaletteParams()
    png_path = Path(png_path)

    # Dispatch : pipeline floodfill chromakey (alternative) ou pipeline k-means standard.
    if params.use_floodfill:
        return _extract_via_floodfill(png_path, params)

    t0 = time.perf_counter()

    img_bgr = cv2.imread(str(png_path), cv2.IMREAD_COLOR)
    if img_bgr is None:
        raise ValueError(f"Lecture impossible : {png_path}")
    h, w = img_bgr.shape[:2]

    # Strategie en 3 temps pour preserver le trait fin :
    #   1. Posterization (optionnel) : ecrase les micro-variations < step.
    #      Applique sur l'image utilisee pour le k-means uniquement.
    #   2. ink_mask sur image ORIGINALE -> contour intact au pixel pres
    #      (bilateral/meanshift ecrasent le trait, on ne veut pas).
    #   3. k-means sur image posterizee + simplifiee -> moins de regions,
    #      plus pertinentes semantiquement.
    img_for_kmeans = _posterize(img_bgr, params.posterize_levels)
    img_for_kmeans = _simplify_colors(img_for_kmeans, params)

    # === Contour : extraction sur image ORIGINALE, immutable ===========
    # Le ink_mask qui sert au RENDU FINAL est calcule une fois et n'est jamais
    # epaissi pour les besoins du k-means. C'est la garantie d'un trait stable
    # quel que soit le preset de zones.
    if params.ink_pipeline == "skeleton":
        ink_mask = _detect_ink_mask_skeleton(img_bgr, params)
    else:
        ink_mask = _detect_ink_mask(img_bgr, params)

    # === Regions : on dilate eventuellement le mask juste pour le k-means ====
    # Cette dilatation supplementaire exclut l'anti-aliasing du trait des
    # clusters couleur, SANS toucher au ink_mask qui sert au rendu.
    if params.ink_kmeans_dilate > 0:
        r = params.ink_kmeans_dilate
        kk = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r + 1, 2 * r + 1))
        ink_mask_for_kmeans = cv2.dilate(ink_mask, kk, iterations=1)
    else:
        ink_mask_for_kmeans = ink_mask

    # Choix : palette IMPOSEE (forced) vs k-means classique.
    if params.forced_palette_rgb:
        label_img, palette_bgr = _quantize_palette_forced(
            img_for_kmeans, ink_mask_for_kmeans, params.forced_palette_rgb,
        )
    else:
        label_img, palette_bgr = _quantize_palette(
            img_for_kmeans, ink_mask_for_kmeans,
            params.n_colors, params.kmeans_attempts,
            color_space=params.kmeans_color_space,
        )

    # Fusion des clusters trop proches (delta-E LAB) : reduit le nombre de
    # couleurs effectives a celles visuellement distinctes.
    # IMPORTANT : skip si palette imposee (les couleurs sont volontaires).
    if (not params.forced_palette_rgb and params.merge_similar_delta_e > 0
            and len(palette_bgr) > 1):
        label_img, palette_bgr = _merge_similar_clusters(
            label_img, palette_bgr, params.merge_similar_delta_e
        )

    # Isolation du vrai fond : detache les fragments interieurs (faussement
    # classes en background a cause des gaps dans le trait) et les reattribue
    # a la region voisine non-fond la plus proche.
    if params.isolate_background:
        label_img = _isolate_true_background(label_img)

    # Isolation STRICTE via trait epaissi virtuel : capture les fragments
    # encore connectes au fond via des gaps fins (les "ponts" dans le trait).
    if params.isolate_background_thick_radius > 0:
        label_img = _isolate_background_strict(
            label_img, img_bgr, params.isolate_background_thick_radius,
        )

    # Isolation par DETECTION COULEUR du fond : approche semantique
    # (independante de la connectivite et du trait).
    if params.bg_color_detection_delta_e > 0:
        label_img = _isolate_background_by_color(
            label_img,
            img_bgr,
            params.bg_color_detection_delta_e,
            params.bg_color_corner_size,
        )

    # NOTE : silhouette_split est applique EN DERNIER (apres merge_small et
    # expand_to_ink) pour qu'aucun traitement ne puisse le defaire.
    # Voir plus bas, juste avant la composition des regions.

    # Fusion semantique des petites regions : reduit le nombre de clics.
    if params.merge_small_regions_px > 0:
        label_img = _merge_small_regions(
            label_img,
            params.merge_small_regions_px,
            params.merge_small_max_passes,
        )
        # 2e passe d'isolation : la fusion a pu re-attacher des fragments au
        # background label en cascade. On verifie a nouveau.
        if params.isolate_background:
            label_img = _isolate_true_background(label_img)
        if params.isolate_background_thick_radius > 0:
            label_img = _isolate_background_strict(
                label_img, img_bgr, params.isolate_background_thick_radius,
            )
        if params.bg_color_detection_delta_e > 0:
            label_img = _isolate_background_by_color(
                label_img, img_bgr,
                params.bg_color_detection_delta_e,
                params.bg_color_corner_size,
            )

    # Morpho cleanup intra-label : elimine speckles internes, comble micro-trous.
    if params.morpho_cleanup_radius > 0:
        label_img = _morpho_cleanup_labels(label_img, params.morpho_cleanup_radius)

    # Extension Voronoi : les regions remontent jusqu'aux pixels du trait.
    # Le trait visible reste calque par-dessus (vue 'full'), mais en mode
    # 'regions only' on n'a plus de halo blanc au contour.
    if params.expand_to_ink:
        label_img = _expand_regions_to_ink(label_img, params.expand_max_distance)

    # ANOMALY DETECTION + LOCAL SPLIT : detecte les composantes anormalement
    # grandes et tente un re-k-means k=2 LAB local pour les splitter.
    # Approche auto-correctif : ne touche QUE les zones suspectes.
    if params.anomaly_detection_enabled:
        label_img, palette_bgr = _detect_and_split_anomalies(
            label_img,
            palette_bgr,
            img_bgr,
            size_pct_threshold=params.anomaly_size_pct_threshold,
            min_delta_e=params.anomaly_min_delta_e,
            max_passes=params.anomaly_max_passes,
        )

    # SILHOUETTE SPLIT en DERNIER : apres tout (merge_small + expand_to_ink).
    # Garantie : aucun traitement ne peut plus annuler le split.
    if params.use_silhouette_split:
        silhouette_mask = _detect_silhouette_mask(
            img_bgr,
            params.silhouette_corner_size,
            params.silhouette_close_radius,
            method=params.silhouette_method,
            ink_mask=ink_mask,
        )
        label_img, palette_bgr = _split_regions_by_silhouette(
            label_img,
            palette_bgr,
            img_bgr,
            silhouette_mask,
            params.silhouette_split_min_overlap,
        )

    min_area = max(50, int(params.min_region_area_ratio * h * w))
    all_regions: list[ColoredRegion] = []
    for color_id in range(len(palette_bgr)):
        bgr = tuple(int(c) for c in palette_bgr[color_id])
        all_regions.extend(_regions_for_color(
            label_img, color_id, bgr,
            min_area=min_area,
            max_regions=params.max_regions_per_color,
            simplify_ratio=params.simplify_ratio,
        ))

    # Tri par aire decroissante (pour rendu coherent : grandes regions au fond).
    all_regions.sort(key=lambda r: -r.area)

    ink_svg = _vtracer_ink_svg(ink_mask) if params.vectorize_ink else ""
    ink_mask_uri = _ndarray_to_data_uri(ink_mask)

    ink_coverage = float((ink_mask == 255).sum()) / float(h * w)
    regions_coverage = float(sum(r.area for r in all_regions)) / float(h * w)
    palette_rgb = [
        (int(c[2]), int(c[1]), int(c[0])) for c in palette_bgr
    ]
    elapsed = (time.perf_counter() - t0) * 1000.0

    return PaletteResult(
        name=png_path.stem,
        width=w,
        height=h,
        palette=palette_rgb,
        regions=all_regions,
        ink_svg_inline=ink_svg,
        ink_mask_data_uri=ink_mask_uri,
        ink_coverage_ratio=ink_coverage,
        regions_coverage_ratio=regions_coverage,
        elapsed_ms=elapsed,
        region_stroke_width=int(params.region_stroke_width),
    )


def _ndarray_to_data_uri(arr: np.ndarray) -> str:
    success, buf = cv2.imencode(".png", arr)
    if not success:
        return ""
    return f"data:image/png;base64,{base64.b64encode(buf.tobytes()).decode('ascii')}"


# === Rendu SVG ===============================================================
def _points_to_path_d(points: list[tuple[int, int]]) -> str:
    if not points:
        return ""
    parts = [f"M{points[0][0]} {points[0][1]}"]
    for x, y in points[1:]:
        parts.append(f"L{x} {y}")
    parts.append("Z")
    return " ".join(parts)


def _generate_auto_palette(n_colors: int, scheme: str = "rainbow") -> list[tuple[int, int, int]]:
    """Genere une palette auto-coheente en HSL equidistante.

    Schemes :
      - 'rainbow' : 360 / n couleurs vives saturees, full spectrum
      - 'pastel'  : rotation HSL mais saturation basse + luminosite haute
      - 'vibrant' : sat haute, lum medium-haute
      - 'soft'    : sat medium, lum haute
    """
    if n_colors <= 0:
        return []
    palettes = []
    for i in range(n_colors):
        hue = int((i * 180) / max(1, n_colors)) % 180  # HSV en cv2 : H sur [0, 180]
        if scheme == "rainbow":
            s, v = 200, 230
        elif scheme == "pastel":
            s, v = 80, 240
        elif scheme == "vibrant":
            s, v = 220, 200
        elif scheme == "soft":
            s, v = 120, 220
        else:
            s, v = 200, 230
        hsv = np.array([[[hue, s, v]]], dtype=np.uint8)
        bgr = cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)[0, 0]
        palettes.append((int(bgr[2]), int(bgr[1]), int(bgr[0])))
    return palettes


def render_svg(
    res: PaletteResult,
    mode: str = "full",
    auto_palette_scheme: str = "rainbow",
    blank_stroke_color: str = "#999",
    blank_stroke_width: float = 0.8,
) -> str:
    """Genere le SVG decompose.

    Modes :
      - 'full'              : background + regions colorees + trait noir
      - 'line_only'         : background blanc + trait noir (line-art reconstitue)
      - 'regions'           : background + regions colorees, SANS trait
      - 'regions_with_ink'  : 'regions' + trait noir en overlay (= 'full' avec
                              focus visuel sur l'alignement regions/contour)
      - 'colorable'         : alias de 'line_only'
      - 'blank_outlined'    : toutes regions en BLANC + stroke fin gris par
                              region (visualise les frontieres internes) +
                              trait noir principal. Cible : coloriage a remplir.
      - 'auto_palette'      : regions remplies par palette HSL equidistante
                              auto-generee, IGNORE la palette ERNIE. Cible :
                              coloriage libre automatique sans contrainte.
                              ``auto_palette_scheme`` = 'rainbow'|'pastel'|
                              'vibrant'|'soft'.
    """
    parts: list[str] = []
    parts.append(f'<rect x="0" y="0" width="{res.width}" height="{res.height}" fill="#ffffff"/>')

    # === Mode 'blank_outlined' : toutes formes en blanc avec contour fin =====
    if mode == "blank_outlined":
        region_paths = []
        for r in res.regions:
            d = _points_to_path_d(r.points)
            region_paths.append(
                f'<path d="{d}" fill="#ffffff" '
                f'stroke="{blank_stroke_color}" stroke-width="{blank_stroke_width}" '
                f'stroke-linejoin="round" stroke-linecap="round" '
                f'class="region region-blank" data-color-id="{r.color_id}" data-area="{r.area}"/>'
            )
        parts.append(f'<g class="regions">{"".join(region_paths)}</g>')
        # Trait noir principal au-dessus.
        if res.ink_svg_inline:
            inner = _extract_svg_inner(res.ink_svg_inline)
            parts.append(f'<g class="ink-layer" style="pointer-events:none;">{inner}</g>')
        elif res.ink_mask_data_uri:
            parts.append(
                f'<image x="0" y="0" width="{res.width}" height="{res.height}" '
                f'href="{res.ink_mask_data_uri}" '
                f'style="pointer-events:none;mix-blend-mode:multiply;"/>'
            )
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {res.width} {res.height}" '
            f'preserveAspectRatio="xMidYMid meet">\n'
            f'  {"".join(parts)}\n'
            f'</svg>'
        )

    # === Mode 'auto_palette' : regions colorees par palette auto HSL ========
    if mode == "auto_palette":
        # On collecte les color_ids uniques pour mapper chaque cluster a une couleur auto.
        unique_ids = sorted({r.color_id for r in res.regions})
        auto_pal = _generate_auto_palette(len(unique_ids), auto_palette_scheme)
        color_map = {cid: auto_pal[i] for i, cid in enumerate(unique_ids)}
        sw = max(0, int(res.region_stroke_width))
        stroke_attrs = (
            f'stroke-width="{sw}" stroke-linejoin="round" stroke-linecap="round"'
            if sw > 0 else ""
        )
        region_paths = []
        for r in res.regions:
            d = _points_to_path_d(r.points)
            r8, g8, b8 = color_map.get(r.color_id, (200, 200, 200))
            color = f"rgb({r8},{g8},{b8})"
            if sw > 0:
                region_paths.append(
                    f'<path d="{d}" fill="{color}" stroke="{color}" {stroke_attrs} '
                    f'class="region" data-color-id="{r.color_id}" data-area="{r.area}"/>'
                )
            else:
                region_paths.append(
                    f'<path d="{d}" fill="{color}" stroke="none" '
                    f'class="region" data-color-id="{r.color_id}" data-area="{r.area}"/>'
                )
        parts.append(f'<g class="regions">{"".join(region_paths)}</g>')
        # Trait noir au-dessus.
        if res.ink_svg_inline:
            inner = _extract_svg_inner(res.ink_svg_inline)
            parts.append(f'<g class="ink-layer" style="pointer-events:none;">{inner}</g>')
        elif res.ink_mask_data_uri:
            parts.append(
                f'<image x="0" y="0" width="{res.width}" height="{res.height}" '
                f'href="{res.ink_mask_data_uri}" '
                f'style="pointer-events:none;mix-blend-mode:multiply;"/>'
            )
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {res.width} {res.height}" '
            f'preserveAspectRatio="xMidYMid meet">\n'
            f'  {"".join(parts)}\n'
            f'</svg>'
        )

    if mode in ("full", "regions", "regions_with_ink"):
        sw = max(0, int(res.region_stroke_width))
        # Le stroke meme couleur est applique en TOUS modes :
        #   - mode 'regions'           : comble les halos blancs aux contours
        #   - mode 'full'/'regions_with_ink' : comble les micro-gaps trait/regions
        #     (le debord externe est cache sous le trait noir vectorise)
        stroke_attrs = (
            f'stroke-width="{sw}" stroke-linejoin="round" stroke-linecap="round"'
            if sw > 0 else ""
        )
        region_paths = []
        for r in res.regions:
            d = _points_to_path_d(r.points)
            r8, g8, b8 = r.color_rgb
            color = f"rgb({r8},{g8},{b8})"
            if sw > 0:
                region_paths.append(
                    f'<path d="{d}" fill="{color}" stroke="{color}" {stroke_attrs} '
                    f'class="region" data-color-id="{r.color_id}" data-area="{r.area}"/>'
                )
            else:
                region_paths.append(
                    f'<path d="{d}" fill="{color}" stroke="none" '
                    f'class="region" data-color-id="{r.color_id}" data-area="{r.area}"/>'
                )
        parts.append(f'<g class="regions">{"".join(region_paths)}</g>')

    if mode in ("full", "line_only", "colorable", "regions_with_ink"):
        if res.ink_svg_inline:
            inner = _extract_svg_inner(res.ink_svg_inline)
            parts.append(f'<g class="ink-layer" style="pointer-events:none;">{inner}</g>')
        elif res.ink_mask_data_uri:
            parts.append(
                f'<image x="0" y="0" width="{res.width}" height="{res.height}" '
                f'href="{res.ink_mask_data_uri}" '
                f'style="pointer-events:none;mix-blend-mode:multiply;"/>'
            )

    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {res.width} {res.height}" '
        f'preserveAspectRatio="xMidYMid meet">\n'
        f'  {"".join(parts)}\n'
        f'</svg>'
    )


# === Rendu HTML demo =========================================================
def _palette_strip(palette: list[tuple[int, int, int]]) -> str:
    swatches = []
    for i, (r, g, b) in enumerate(palette):
        swatches.append(
            f'<span class="swatch" title="couleur {i} : rgb({r},{g},{b})" '
            f'style="background:rgb({r},{g},{b});"></span>'
        )
    return f'<div class="palette">{"".join(swatches)}</div>'


def render_html(results: list[tuple[PaletteResult, Path]], title: str) -> str:
    cards = []
    for res, src in results:
        src_uri = f"data:image/png;base64,{base64.b64encode(src.read_bytes()).decode('ascii')}"
        svg_full = render_svg(res, "full")
        svg_line = render_svg(res, "line_only")
        svg_reg = render_svg(res, "regions")
        meta = (
            f"{len(res.palette)} couleurs | {len(res.regions)} regions | "
            f"trait : {res.ink_coverage_ratio * 100:.1f}% du canvas | "
            f"regions : {res.regions_coverage_ratio * 100:.1f}% du canvas | "
            f"{res.elapsed_ms:.0f} ms"
        )

        cards.append(f"""
        <article class="card">
          <h2>{html.escape(res.name)}</h2>
          <div class="meta">{meta}</div>
          {_palette_strip(res.palette)}
          <div class="grid">
            <figure><figcaption>1. original (ERNIE)</figcaption><img src="{src_uri}"/></figure>
            <figure><figcaption>2. trait noir isole (vector)</figcaption><div class="svg-wrap">{svg_line}</div></figure>
            <figure><figcaption>3. regions colorees (sans trait)</figcaption><div class="svg-wrap">{svg_reg}</div></figure>
            <figure><figcaption>4. superposition SVG (= reconstitution)</figcaption><div class="svg-wrap">{svg_full}</div></figure>
          </div>
        </article>
        """)

    style = """
    body{font-family:system-ui,sans-serif;background:#f3f4f6;color:#222;margin:1rem;}
    h1{margin:0 0 .25rem 0;}
    header{margin-bottom:1rem;background:#fff;border:1px solid #ddd;border-radius:.5rem;
           padding:.75rem 1rem;}
    .card{background:#fff;border:1px solid #ddd;border-radius:.5rem;
          padding:.75rem 1rem;margin-bottom:1.5rem;}
    .card h2{margin:0 0 .25rem 0;font-size:1rem;font-family:ui-monospace,Menlo,Consolas,monospace;}
    .meta{color:#555;font-size:.78rem;margin:.15rem 0 .5rem 0;
          font-family:ui-monospace,Menlo,Consolas,monospace;}
    .palette{display:flex;gap:.25rem;margin-bottom:.75rem;}
    .swatch{width:24px;height:24px;border-radius:.2rem;border:1px solid #ddd;display:inline-block;}
    .grid{display:grid;grid-template-columns:repeat(4,1fr);gap:.5rem;}
    figure{margin:0;display:flex;flex-direction:column;gap:.25rem;min-width:0;}
    figcaption{font-size:.7rem;color:#666;text-transform:uppercase;letter-spacing:.04em;}
    figure img,.svg-wrap{width:100%;height:auto;background:#fff;
                          border:1px solid #eee;border-radius:.25rem;display:block;}
    .svg-wrap svg{width:100%;height:auto;display:block;}
    """
    return f"""<!doctype html>
<html lang="fr">
<head><meta charset="utf-8"/><title>{html.escape(title)}</title><style>{style}</style></head>
<body>
<header>
  <h1>{html.escape(title)}</h1>
  <p style="color:#666;">Decomposition d'un PNG colorie : palette extraite (k-means HSV), regions par couleur (composantes connexes), trait noir isole (HSV thresholds + VTracer bw_polygon).</p>
</header>
{"".join(cards)}
</body></html>
"""


# === CLI =====================================================================
def _params_from_args(args: argparse.Namespace) -> "ExtractPaletteParams":
    """Construit les params depuis un preset CLI + overrides explicites."""
    overrides: dict = {
        "n_colors": int(args.n_colors),
        "min_region_area_ratio": float(args.min_region_ratio),
        "ink_max_value": int(args.ink_max_value),
        "ink_max_saturation": int(args.ink_max_sat),
        "use_otsu_grayscale": not args.no_otsu,
        "otsu_max_threshold": int(args.otsu_max),
        "ink_dilate": int(args.ink_dilate),
        "close_radius": int(args.close_radius),
        "vectorize_ink": not args.no_vectorize_ink,
        "expand_to_ink": not args.no_expand if getattr(args, "no_expand", False) else None,
        "expand_max_distance": int(args.expand_max),
    }
    # Si --no-expand n'est PAS passe, on garde la valeur du preset.
    if not getattr(args, "no_expand", False):
        overrides.pop("expand_to_ink")
    else:
        overrides["expand_to_ink"] = False

    preset = getattr(args, "preset", None)
    return make_params(preset, **{k: v for k, v in overrides.items() if v is not None})


def _cmd_single(args: argparse.Namespace) -> int:
    src = Path(args.png).resolve()
    if not src.is_file():
        print(f"FAIL: PNG introuvable : {src}", file=sys.stderr)
        return 2
    params = _params_from_args(args)
    print(f"  preset = {args.preset or 'defaults'} | expand_to_ink={params.expand_to_ink}")
    res = extract_palette(src, params)
    print(f"== {src.name} ==")
    print(f"  palette       : {len(res.palette)} couleurs")
    print(f"  regions       : {len(res.regions)}")
    print(f"  trait         : {res.ink_coverage_ratio * 100:.1f}% du canvas")
    print(f"  regions cover : {res.regions_coverage_ratio * 100:.1f}%")
    print(f"  temps         : {res.elapsed_ms:.0f} ms")
    if args.out:
        out = Path(args.out).resolve()
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(render_html([(res, src)], title=src.name), encoding="utf-8")
        print(f"  -> HTML : {out} ({out.stat().st_size // 1024} KB)")
    if args.json:
        jpath = Path(args.json).resolve()
        jpath.write_text(json.dumps({
            "name": res.name,
            "width": res.width,
            "height": res.height,
            "palette": res.palette,
            "n_regions": len(res.regions),
            "ink_coverage_pct": round(res.ink_coverage_ratio * 100, 2),
            "regions_coverage_pct": round(res.regions_coverage_ratio * 100, 2),
            "elapsed_ms": round(res.elapsed_ms, 1),
        }, indent=2), encoding="utf-8")
        print(f"  -> JSON : {jpath}")
    return 0


def _cmd_bench(args: argparse.Namespace) -> int:
    out = Path(args.out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    params = _params_from_args(args)

    print(f"== extract-palette bench : {len(BENCH_CASES)} cas (preset={args.preset or 'defaults'}) ==")
    results: list[tuple[PaletteResult, Path]] = []
    for case_name in BENCH_CASES:
        src = COLORED_FILL_DIR / case_name
        if not src.is_file():
            print(f"  [SKIP] {case_name} (lance d'abord _lab/colored-fill-test/run.py)")
            continue
        try:
            res = extract_palette(src, params)
        except Exception as e:  # noqa: BLE001
            print(f"  [FAIL] {case_name}: {e}")
            continue
        print(
            f"  [OK ] {res.name:<22}  palette={len(res.palette):<3}  "
            f"regions={len(res.regions):<4}  ink={res.ink_coverage_ratio * 100:5.1f}%  "
            f"reg_cov={res.regions_coverage_ratio * 100:5.1f}%  {res.elapsed_ms:6.0f} ms"
        )
        results.append((res, src))

    if not results:
        print("FAIL: aucun cas exploitable", file=sys.stderr)
        return 2

    out.write_text(render_html(results, title="extract-palette - bench"), encoding="utf-8")
    print(f"\n-> demo HTML : {out} ({out.stat().st_size // 1024} KB)")
    return 0


def _cmd_bench_presets(args: argparse.Namespace) -> int:
    """Compare N presets cote-a-cote sur les memes images. Aucun param ecrase."""
    out = Path(args.out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)

    selected_presets = args.presets or list(PRESETS.keys())
    unknown = [p for p in selected_presets if p not in PRESETS]
    if unknown:
        print(f"FAIL: presets inconnus : {unknown}. Dispos : {list(PRESETS)}", file=sys.stderr)
        return 2

    selected_cases = args.cases or BENCH_CASES
    print(f"== bench-presets : {len(selected_cases)} cas x {len(selected_presets)} presets ==")

    # Pour chaque cas, on stocke la liste des resultats par preset.
    grid: list[tuple[Path, dict[str, PaletteResult]]] = []
    for case_name in selected_cases:
        src = COLORED_FILL_DIR / case_name if not Path(case_name).is_absolute() else Path(case_name)
        if not src.is_file():
            print(f"  [SKIP] {case_name}")
            continue
        print(f"\n[case] {src.name}")
        per_preset: dict[str, PaletteResult] = {}
        for preset_name in selected_presets:
            overrides = {}
            if args.n_colors is not None:
                overrides["n_colors"] = int(args.n_colors)
            params = make_params(preset_name, **overrides)
            try:
                res = extract_palette(src, params)
            except Exception as e:  # noqa: BLE001
                print(f"  [{preset_name}] FAIL {e}")
                continue
            per_preset[preset_name] = res
            print(
                f"  [{preset_name:<14}] regions={len(res.regions):<4}  "
                f"ink={res.ink_coverage_ratio * 100:5.1f}%  "
                f"reg_cov={res.regions_coverage_ratio * 100:5.1f}%  "
                f"{res.elapsed_ms:6.0f} ms"
            )
        if per_preset:
            grid.append((src, per_preset))

    if not grid:
        print("FAIL: aucun cas exploitable", file=sys.stderr)
        return 2

    html_out = _render_bench_presets_html(grid, selected_presets, args.focus)
    out.write_text(html_out, encoding="utf-8")
    print(f"\n-> demo HTML : {out} ({out.stat().st_size // 1024} KB)")
    return 0


def _render_bench_presets_html(
    grid: list[tuple[Path, dict[str, PaletteResult]]],
    preset_order: list[str],
    focus_mode: str = "regions",
) -> str:
    """Genere un HTML avec N presets cote-a-cote pour chaque cas.

    ``focus_mode`` controle la vue prioritaire affichee :
        - 'regions' : SVG regions only (sans trait) -- la vue critique
        - 'full'    : SVG superposition
        - 'line'    : SVG trait isole
        - 'all'     : 3 vues empilees par preset
    """
    cards = []
    for src, per_preset in grid:
        cols = []
        # Col 1 = original (raster)
        raster_uri = f"data:image/png;base64,{base64.b64encode(src.read_bytes()).decode('ascii')}"
        cols.append(f"""
        <div class="col original">
          <h3>original</h3>
          <div class="frame"><img src="{raster_uri}" alt="original"/></div>
          <div class="meta">{src.name}</div>
        </div>
        """)
        # Cols 2..N = un preset chacune
        for preset_name in preset_order:
            res = per_preset.get(preset_name)
            if res is None:
                cols.append(f"""
                <div class="col miss">
                  <h3>{html.escape(preset_name)}</h3>
                  <div class="frame error">FAIL</div>
                </div>
                """)
                continue

            views = []
            if focus_mode in ("regions", "all"):
                views.append(("regions only", render_svg(res, "regions")))
            if focus_mode in ("regions_with_ink", "all"):
                views.append(("regions + trait overlay", render_svg(res, "regions_with_ink")))
            if focus_mode in ("full", "all"):
                views.append(("superposition", render_svg(res, "full")))
            if focus_mode in ("line", "all"):
                views.append(("trait isolé", render_svg(res, "line_only")))
            if not views:
                views.append(("regions + trait overlay", render_svg(res, "regions_with_ink")))

            view_blocks = "".join(
                f'<figure><figcaption>{html.escape(c)}</figcaption><div class="svg-wrap">{s}</div></figure>'
                for c, s in views
            )

            cols.append(f"""
            <div class="col preset">
              <h3>{html.escape(preset_name)}</h3>
              <div class="metrics">{len(res.regions)} reg | ink {res.ink_coverage_ratio*100:.1f}% | cov {res.regions_coverage_ratio*100:.1f}% | {res.elapsed_ms:.0f} ms</div>
              {view_blocks}
            </div>
            """)
        cards.append(f"""
        <article class="case">
          <h2>{html.escape(src.name)}</h2>
          <div class="grid">{"".join(cols)}</div>
        </article>
        """)

    # Tableau resume (couverture par preset).
    summary_rows = []
    for src, per_preset in grid:
        cells = [f"<td>{html.escape(src.name)}</td>"]
        for preset_name in preset_order:
            res = per_preset.get(preset_name)
            if res is None:
                cells.append("<td class='num miss'>—</td>")
            else:
                cells.append(
                    f"<td class='num'>{res.regions_coverage_ratio*100:.1f}% | "
                    f"{len(res.regions)} reg | ink {res.ink_coverage_ratio*100:.1f}%</td>"
                )
        summary_rows.append(f"<tr>{''.join(cells)}</tr>")
    preset_header = "".join(f"<th>{html.escape(p)}</th>" for p in preset_order)

    style = """
    body{font-family:system-ui,sans-serif;background:#f3f4f6;color:#222;margin:1rem;}
    h1{margin:0 0 .25rem 0;}
    header{margin-bottom:1rem;background:#fff;border:1px solid #ddd;border-radius:.5rem;
           padding:.75rem 1rem;}
    .summary{margin-bottom:1rem;background:#fff;border:1px solid #ddd;border-radius:.5rem;
             padding:.5rem 1rem;}
    .summary table{width:100%;border-collapse:collapse;font-size:.85rem;}
    .summary th,.summary td{padding:.25rem .5rem;text-align:left;border-bottom:1px solid #f0f0f0;}
    .summary th{color:#666;font-weight:500;}
    .summary td.num{font-family:ui-monospace,Menlo,Consolas,monospace;}
    .case{background:#fff;border:1px solid #ddd;border-radius:.5rem;
          padding:.75rem 1rem;margin-bottom:1.5rem;}
    .case h2{margin:0 0 .5rem 0;font-size:1rem;
             font-family:ui-monospace,Menlo,Consolas,monospace;}
    .grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:.75rem;}
    .col{display:flex;flex-direction:column;gap:.4rem;min-width:0;}
    .col h3{margin:0;font-size:.75rem;text-transform:uppercase;letter-spacing:.04em;color:#666;
            font-family:ui-monospace,Menlo,Consolas,monospace;}
    .col .frame{background:#fff;border:1px solid #eee;border-radius:.25rem;overflow:hidden;
                aspect-ratio:1/1;}
    .col .frame img{width:100%;height:100%;object-fit:contain;display:block;}
    figure{margin:0;display:flex;flex-direction:column;gap:.2rem;}
    figcaption{font-size:.65rem;color:#888;text-transform:uppercase;letter-spacing:.04em;}
    .svg-wrap{background:#fff;border:1px solid #eee;border-radius:.25rem;
              aspect-ratio:1/1;overflow:hidden;}
    .svg-wrap svg{width:100%;height:100%;display:block;}
    .metrics{font-family:ui-monospace,Menlo,Consolas,monospace;font-size:.7rem;color:#444;}
    .col.miss .frame.error{display:flex;align-items:center;justify-content:center;color:#dc2626;}
    .col.miss{opacity:.6;}
    """

    return f"""<!doctype html>
<html lang="fr">
<head><meta charset="utf-8"/><title>extract-palette - bench presets</title><style>{style}</style></head>
<body>
<header>
  <h1>extract-palette — comparaison presets</h1>
  <p style="color:#666;">{len(grid)} image(s) x {len(preset_order)} preset(s). Aucun preset n'ecrase un autre : chaque colonne est une version distincte et persistante du parametrage.</p>
</header>

<section class="summary">
  <table>
    <thead><tr><th>cas</th>{preset_header}</tr></thead>
    <tbody>{"".join(summary_rows)}</tbody>
  </table>
</section>

{"".join(cards)}
</body></html>
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Decompose un PNG colorie en palette + regions + trait noir.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    def _add_common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--preset", choices=list(PRESETS.keys()), default=None,
                       help=f"Preset de base (def : balanced_v3). Dispos : {', '.join(PRESETS)}.")
        p.add_argument("--n-colors", default=12, help="Nombre de couleurs k-means (def 12).")
        p.add_argument("--min-region-ratio", default=0.001, help="Surface min region (frac canvas, def 0.001).")
        p.add_argument("--ink-max-value", default=80, help="V max HSV pour trait noir (def 80).")
        p.add_argument("--ink-max-sat", default=60, help="S max HSV pour trait noir (def 60).")
        p.add_argument("--no-otsu", action="store_true", help="Desactive le OR avec Otsu grayscale.")
        p.add_argument("--otsu-max", type=int, default=90,
                       help="Plafond dur sur Otsu (def 90) : evite que Otsu mange les couleurs sombres.")
        p.add_argument("--ink-dilate", type=int, default=1, help="Dilatation trait apres masquage (def 1 px).")
        p.add_argument("--close-radius", type=int, default=3, help="CLOSE morpho final (def 3 px).")
        p.add_argument("--no-vectorize-ink", action="store_true", help="Garde le trait en bitmap au lieu de VTracer.")
        p.add_argument("--no-expand", action="store_true",
                       help="Force la desactivation de l'expansion vers le trait (override preset).")
        p.add_argument("--expand-max", type=int, default=0,
                       help="Distance max (px) d'expansion d'une region (def 0 = pas de limite).")

    p_single = sub.add_parser("single", help="Decompose un PNG.")
    p_single.add_argument("png")
    p_single.add_argument("--out", default=None, help="HTML de sortie.")
    p_single.add_argument("--json", default=None, help="Metriques JSON.")
    _add_common(p_single)
    p_single.set_defaults(func=_cmd_single)

    p_bench = sub.add_parser("bench", help="Bench mono-preset sur outputs/ du colored-fill-test.")
    p_bench.add_argument("--out", default=str(Path(__file__).parent / "demo.html"))
    _add_common(p_bench)
    p_bench.set_defaults(func=_cmd_bench)

    p_bp = sub.add_parser("bench-presets",
                          help="Compare N presets cote-a-cote (aucun parametrage n'ecrase un autre).")
    p_bp.add_argument("--out", default=str(Path(__file__).parent / "compare_presets.html"))
    p_bp.add_argument("--presets", nargs="+", default=None,
                      help=f"Liste de presets a comparer (def = tous : {list(PRESETS)}).")
    p_bp.add_argument("--cases", nargs="+", default=None,
                      help="Liste de PNG ou noms relatifs a outputs/ (def = BENCH_CASES).")
    p_bp.add_argument(
        "--focus",
        choices=["regions", "regions_with_ink", "full", "line", "all"],
        default="regions_with_ink",
        help="Vue prioritaire affichee (def : regions + trait overlay -- alignement visible).",
    )
    p_bp.add_argument("--n-colors", type=int, default=None,
                      help="N couleurs k-means (def : utilise la valeur du preset, ex 12 pour strict_v1, 24 pour quality_v2_n24).")
    p_bp.set_defaults(func=_cmd_bench_presets)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
