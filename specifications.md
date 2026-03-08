# Spécifications du Projet : Générateur de Collections pour Coloriage (Line Art)

## 1. Objectif Principal

Créer un pipeline automatisé permettant de générer des collections d'images sous forme de "line art" (dessin au trait, contours noirs sur fond blanc), destinées à un site de coloriage. Le processus doit être optimisé pour :

- **Minimiser les coûts financiers** (privilégier les modèles open-source ou des API très abordables).
- **Minimiser l'intervention humaine** (automatisation maximale du processus de bout en bout).

## 2. Cas d'Usage

0. **Créer une taxonomie universelle :** qui permettra de structurer la base des images pour un fonctionnement multilingue, multi-pays, une navigation hiérarchique, la possibilité d'avoir des mots-clés transverses qui permettent de gérer les tendances, les préférences et le cross des thèmes.
1. **Saisie du thème :** L'utilisateur fournit un thème général (ex. : "Animaux de la forêt", "Mandalas complexes", "Voitures de sport").
2. **Génération des concepts :** Le système génère automatiquement une liste de sous-thèmes ou d'idées liés au thème principal. Ces concepts doivent être synchronisés avec la taxonomie universelle. Si besoin la taxonomie peut être mise à jour mais il faut que cela reste exceptionnel pour garder sa stabilité.
3. **Génération des prompts :** Le système transforme ces idées en prompts optimisés pour la génération de line art clair et sans ombrage.
4. **Génération des images :** Le système utilise en priorité un modèle local (Stable Diffusion / SDXL / Flux + LoRA line art) pour générer les images, avec la possibilité d'utiliser des API externes en alternative.
5. **Post-traitement :** Le système traite les images reçues pour s'assurer qu'elles sont parfaitement adaptées au coloriage (suppression des niveaux de gris, renforcement des contrastes, binarisation noir/blanc, upscaling).
6. **Exportation :** Le système regroupe les images générées dans une "collection" prête à être publiée sur un ou plusieurs sites de coloriage.
7. **Monitoring et pilotage :** Le système suit l'état des générations, de la qualité des images et des publications par site, avec à terme la possibilité d'être piloté par un agent.

## 3. Contraintes Techniques et Qualitatives

### 3.1 Qualité du Line Art

- Les lignes doivent être nettes et continues.
- Absence d'ombrages, de dégradés et de demi-teintes (uniquement du noir et du blanc pur).
- Résolution suffisante pour l'impression (300 DPI idéalement, ou upscaling).

### 3.2 Choix Technologiques (à préciser par phase)

- **Taxonomie initiale v0** : définie dans le projet, stockée en JSON (ex. `data/taxonomy_universal_v0.json`), avec éditeur visuel (`data/taxonomy_editor.html`) et projection possible dans une base SQLite pour les requêtes.
- **Génération de concepts/prompts :** LLM local (ex. Ollama + Llama 3) privilégié, avec possibilité d'utiliser un LLM externe (gpt-4o-mini, etc.) en alternative.
- **Génération d'images :** 
  - Génération locale via Stable Diffusion XL / Flux + LoRA "Coloring Book / Line Art" (prioritaire pour limiter les coûts).
  - En option, utilisation d'API abordables (Together AI, Replicate, DALL·E 3…) si nécessaire.
- **Post-traitement :** Scripts Python (Pillow, OpenCV) pour le nettoyage des images.
- **Stockage** : fichiers images sur disque (`outputs/`), métadonnées et liens avec les taxonomies dans une base SQLite.
- **Orchestration :** Script Python principal (`pipeline.py`) pour gérer le flux de travail, conçu pour pouvoir être piloté plus tard par un agent.

## 4. Livrables Attendus

- Un document d'architecture technique (choix des API/modèles définitifs).
- Les scripts d'automatisation (pipeline complet).
- Une documentation d'utilisation pour lancer la génération d'une collection.

