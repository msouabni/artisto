# Taxonomie universelle v0 – Structure et axes principaux

## Fichier et format

- Fichier principal : `data/taxonomy_universal_v0.json` (éditeur : `data/taxonomy_editor.html`, voir [Template éditeur admin](admin-editor-template.md))
- Langues supportées : `fr`, `en`, `ar`
- Schéma logique :
  - `taxonomy_id`: identifiant global de la taxonomie (`universal_v0`)
  - `label`: libellé humain de la taxonomie
  - `languages`: liste des langues supportées (ex. `[fr, en, ar]`)
  - `vocabularies[]` :
    - `id`
    - `label_fr`, `label_en`, `label_ar`
    - `terms[]` (arbre hiérarchique)

Chaque `term` a la forme :

- `id`: identifiant stable interne (snake_case, sans espaces)
- `slug`: identifiant URL-friendly (kebab-case)
- `name_fr`, `name_en`, `name_ar`: libellés par langue
- `description_fr`, `description_en`, `description_ar` (optionnelles)
- `weight`: entier pour l’ordre d’affichage au sein d’un même niveau
- `keywords[]`: liste de mots-clés (facultative)
- `children[]`: sous-termes (même structure)

## Vocabulaire `themes`

Le vocabulaire `themes` regroupe les grands axes de la taxonomie universelle v0.

### 1. Animaux (`animaux`)

- **Racine** : `animaux` (`animals` / `الحيوانات`)
- **Sous-branches** :
  - `animaux_domestiques` : animaux de compagnie (chiens, chats, lapins…)
  - `animaux_sauvages` : animaux de la jungle, savane, forêt…
  - `animaux_marins` : poissons, dauphins, requins, etc.
  - `animaux_ferme` : vaches, poules, cochons, etc.
  - `dinosaures` : dinosaures variés.

### 2. Mandalas & motifs (`mandalas`)

- **Racine** : `mandalas`
- **Sous-branches** :
  - `mandalas_faciles` : mandalas simples pour les plus jeunes
  - `mandalas_complexes` : mandalas détaillés pour ados/adultes
  - `mandalas_animaux` : mandalas intégrant des formes d’animaux
  - `mandalas_fleurs` : mandalas floraux

### 3. Véhicules (`vehicules`)

- **Racine** : `vehicules`
- **Sous-branches** :
  - `voitures` : voitures de tous types
  - `camions` : camions, véhicules de chantier…
  - `motos` : motos, scooters…
  - `avions` : avions, hélicoptères…
  - `bateaux` : bateaux, navires…
  - `trains` : trains, métros…

### 4. Personnages (`personnages`)

- **Racine** : `personnages`
- **Sous-branches** :
  - `metiers` : docteur, pompier, astronaute, etc.
  - `super_heros_originaux` : super-héros sans licence
  - `fantasy` : chevaliers, dragons, magiciens…
  - `vie_quotidienne` : famille, école, sport…

### 5. Saisons & événements (`saisons_evenements`)

- **Racine** : `saisons_evenements`
- **Sous-branches** :
  - `saisons` : `printemps`, `ete`, `automne`, `hiver`
  - `fetes` : `noel`, `halloween`, `paques`, `anniversaire`, `aid`

### 6. Éducatif (`educatif`)

- **Racine** : `educatif`
- **Sous-branches** :
  - `lettres` : alphabet, lettres à colorier
  - `chiffres` : nombres pour apprendre à compter
  - `formes` : formes géométriques
  - `cartes` : cartes du monde, pays…
  - `science` : espace, corps humain simplifié, etc.

### 7. Divers (`divers`)

- **Racine** : `divers`
- Sert de catégorie d’extension pour ajouter d’autres thèmes (nourriture, bâtiments, motifs spécifiques…) au fur et à mesure.

## Utilisation prévue

- **Interne (base images)** : chaque image sera rattachée à un ou plusieurs `term_id` de cette taxonomie universelle (via `{taxonomy_id, term_id}`), ce qui permettra :
  - de générer des concepts et prompts cohérents par thème,
  - de filtrer/rechercher les images par branche.
- **Taxonomies de sortie** : les sites de coloriage dériveront des taxonomies plus simples à partir de cette structure (sélection de branches, réduction de profondeur, une seule langue).

