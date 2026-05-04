# Contrat d'échange — Pipeline de production → Plateforme de publication

> **Destinataires** : équipe plateforme de publication (site web SEO + application coloriage).  
> **Auteur** : équipe pipeline de production (ce dépôt).  
> **Statut** : document de référence vivant — à mettre à jour à chaque évolution de format ou de périmètre.

---

## 1. Vue d'ensemble du pipeline de production

Le pipeline produit des **pages de coloriage** destinées à être publiées sur un site web orienté SEO.
Chaque page correspond à une **image line art noir et blanc** (coloriage imprimable ou interactif)
accompagnée de **métadonnées éditoriales multilingues** structurées, organisées selon une **taxonomie de thèmes**.

### Cas d'usage finaux (côté plateforme)

- **Application web / mobile de coloriage interactif** : l'utilisateur colorie l'image directement dans le navigateur.
- **Impression d'ebooks de coloriage** : pages A4 regroupées par thème, exportées en PDF.
- **Navigation SEO par catégorie** : arborescence de pages indexables (animaux > chats > chat en bibliothèque).
- **Moteur de recherche interne** : recherche par titre, mots-clés, tags taxonomiques.

---

## 2. Ce que le pipeline met à disposition

### 2.1 Les images

#### Format technique

| Propriété | Valeur |
|---|---|
| Format fichier | **PNG** |
| Dimensions | **1024 × 1024 pixels** (carré) |
| Mode couleur | Noir et blanc (line art) |
| Style | Contours noirs épais sur fond blanc pur, pas de dégradés, pas de remplissage de couleur |
| Fond | Blanc pur (`#FFFFFF`) |
| Modèle de génération | Z-Image-Turbo BF16 (via ComfyUI) |
| Usage | Impression A4 / coloriage interactif web ou mobile |

> **Note importante** : les images sont des line art "coloring book page" — fond blanc pur, contours noirs nets, sans ombres ni dégradés. Elles sont prêtes à colorier telles quelles.

#### Dénomination des fichiers

```
outputs/{image_id}_{job_id}.png
```

Exemple : `outputs/animaux_chat_collier_job_gen_1773359380880.png`

Le `image_id` est un identifiant stable, en snake_case, qui correspond au concept d'image
(ex. `animaux_chat_bibliothque`). Il est également utilisé comme clé de liaison avec toutes les métadonnées.

#### Ce que le pipeline ne fournit PAS (à charge de la plateforme)

- **Thumbnail / aperçu réduit** : la plateforme doit générer ses propres variantes (WebP, AVIF, résolutions
  adaptatives) à partir du PNG source. Le pipeline ne produit qu'un seul fichier par image.
- **PDF compilé** : la plateforme est responsable de l'assemblage des PDFs d'ebooks.
- **Versions colorées** : le pipeline ne produit que des versions noir et blanc.

---

### 2.2 Les métadonnées par image

Chaque image est accompagnée d'un ensemble structuré de champs, listés ci-dessous.

#### Champs identité

| Champ | Type | Description |
|---|---|---|
| `id` | `string` | Identifiant unique stable du concept, snake_case (ex. `animaux_chat_bibliothque`) |
| `title` | `string` | Titre court de l'image en français (ex. "Chat en bibliothèque") |
| `status` | `enum` | Statut pipeline (voir §3) |
| `origin_term_id` | `string` | ID du terme taxonomique source |
| `origin_taxonomy_id` | `string` | ID de la taxonomie source |

#### Champs de génération

| Champ | Type | Description |
|---|---|---|
| `prompt` | `string` | Prompt positif utilisé pour la génération (en anglais) |
| `negative_prompt` | `string` | Prompt négatif utilisé (en anglais) |
| `model_name` | `string` | Modèle de génération : `z_image_turbo_bf16` ou `ernie-image-turbo-q8-api` |

#### Champs fichier (output sélectionné)

| Champ | Type | Description |
|---|---|---|
| `file_path` | `string` | Chemin relatif au PNG (ex. `outputs/animaux_chat_collier_job_gen_....png`) |
| `file_format` | `string` | Toujours `png` |
| `width` | `integer` | Toujours `1024` |
| `height` | `integer` | Toujours `1024` |
| `quality_score` | `float\|null` | Score qualité automatique (non systématiquement rempli) |

#### Tags taxonomiques

Chaque image porte un ou plusieurs tags taxonomiques sous forme de paires `(taxonomy_id, term_id)`.
Ces tags permettent la navigation par catégorie et le filtrage.

```json
{
  "tags": [
    { "taxonomy_id": "coloriage", "term_id": "animaux_domestiques_chats" }
  ]
}
```

---

### 2.3 La taxonomie

La taxonomie est une **arborescence de thèmes** multilingue (français, anglais, arabe).
Elle structure la navigation du site et les pages de catégories.

#### Structure

```
Taxonomie
 └── Vocabulaire "themes"
      ├── Terme racine (ex. "Animaux")
      │    ├── Terme enfant (ex. "Chats")
      │    │    ├── ...
      │    └── Terme enfant (ex. "Chiens")
      └── Terme racine (ex. "Véhicules")
```

#### Champs par terme

| Champ | Type | Description |
|---|---|---|
| `id` | `string` | Identifiant stable, snake_case (ex. `animaux_domestiques_chats`) |
| `slug` | `string` | URL slug (ex. `chats-domestiques`) |
| `slug_i18n` | `JSON` | Slugs par locale : `{"fr": "...", "en": "...", "ar": "..."}` |
| `name_i18n` | `JSON` | Nom par locale : `{"fr": "Chats", "en": "Cats", "ar": "قطط"}` |
| `description_i18n` | `JSON` | Description SEO par locale (15-25 mots) |
| `keywords` | `JSON array` | Mots-clés SEO associés au terme (multilingues) |
| `parent_id` | `string\|null` | ID du terme parent (null = racine) |
| `weight` | `integer` | Ordre d'affichage |

> **Volume actuel** : 49 termes dans le vocabulaire `themes` (1 taxonomie, 1 vocabulaire).

#### Utilisation côté plateforme

- **Page de catégorie** : une URL par terme (`/themes/animaux/chats/`)
- **Breadcrumb** : reconstitué via la chaîne `parent_id`
- **Méta-title / méta-description** : générés depuis `name_i18n` et `description_i18n`
- **Navigation** : pondérée par `weight`

---

### 2.4 Les collections (futur)

Les images pourront être regroupées en **collections** (ex. "Pack de Noël", "Les animaux de la ferme").
Chaque collection aura un `slug`, un nom multilingue, et une liste ordonnée d'images.
Ce mécanisme est prévu dans le schéma mais pas encore utilisé en production.

---

## 3. Statuts du cycle de vie d'une image

Le pipeline gère un cycle de vie interne. Seules les images avec certains statuts doivent être publiées.

| Statut | Signification | Action plateforme |
|---|---|---|
| `draft` | Idée initiale, pas de prompt | Ignorer |
| `prompt_ready` | Prompt validé, pas encore généré | Ignorer |
| `scheduled` | Job de génération créé | Ignorer |
| `generating` | Génération en cours | Ignorer |
| `generated` | Image générée, en attente de validation humaine | Ignorer (ou pré-visualisation admin) |
| `approved` | Validé éditorialement, prêt à publier | **Publier** |
| `rejected` | Rejeté | Ignorer |
| `published` | Marqué comme publié | Maintenir en ligne |

> **Règle de publication** : la plateforme ne doit exposer au public que les images dont le statut est `approved` ou `published`. Le passage à `published` est géré via l'API du pipeline (module à développer).

---

## 4. Format d'échange API (module de publication — en cours de conception)

> Ce module n'est pas encore développé. La section ci-dessous définit le **contrat cible** entre les deux équipes.

### 4.1 Principes généraux

- La plateforme expose une API REST (HTTPS).
- Le pipeline publie le contenu via cette API — il ne fait pas de push de fichiers par FTP ou autre.
- Le pipeline gère l'état de publication dans sa propre base (`site_publication`, `site_sync`).
- Les échanges sont versionnés : toute évolution de format doit être négociée entre les deux équipes et documentée ici.

### 4.2 Ressources à exposer par la plateforme

#### `POST /api/publish/images`

Créer ou mettre à jour une image publiée.

**Corps de la requête :**

```json
{
  "id": "animaux_chat_bibliothque",
  "title": "Chat en bibliothèque",
  "status": "approved",
  "file_url": "https://cdn.pipeline.example.com/outputs/animaux_chat_bibliothque_job_gen_xxx.png",
  "file_format": "png",
  "width": 1024,
  "height": 1024,
  "model_name": "z_image_turbo_bf16",
  "prompt": "...",
  "tags": [
    { "taxonomy_id": "coloriage", "term_id": "animaux_domestiques_chats" }
  ],
  "origin_term_id": "animaux_domestiques_chats",
  "origin_taxonomy_id": "coloriage"
}
```

**Réponse attendue :**

```json
{
  "id": "animaux_chat_bibliothque",
  "published_url": "https://www.plateforme.example.com/coloriage/animaux/chats/chat-en-bibliotheque/",
  "status": "published"
}
```

#### `POST /api/publish/taxonomy`

Synchroniser (remplacer ou mettre à jour) un terme taxonomique.

**Corps de la requête :**

```json
{
  "taxonomy_id": "coloriage",
  "vocabulary_id": "themes",
  "term": {
    "id": "animaux_domestiques_chats",
    "slug_i18n": { "fr": "chats-domestiques", "en": "domestic-cats", "ar": "قطط-منزلية" },
    "name_i18n": { "fr": "Chats domestiques", "en": "Domestic Cats", "ar": "قطط منزلية" },
    "description_i18n": {
      "fr": "Coloriage de chats domestiques pour enfants, idéal pour s'initier au coloriage.",
      "en": "Domestic cats coloring pages for kids, perfect for beginners.",
      "ar": "..."
    },
    "keywords": ["chat à colorier", "cat coloring page", "coloriage chat"],
    "parent_id": "animaux",
    "weight": 1
  }
}
```

#### `DELETE /api/publish/images/{image_id}`

Dépublier une image (sur rejet éditorial ou suppression dans le pipeline).

#### `GET /api/publish/images/{image_id}`

Vérifier l'état de publication d'une image (URL publiée, date, statut).

---

## 5. Capacité de production — état actuel

### 5.1 Configuration matérielle et logicielle

| Composant | Détail |
|---|---|
| Génération d'images | ComfyUI local (GPU dédié) |
| Modèles image | Z-Image-Turbo BF16 (principal) · ERNIE-Image-Turbo Q8 API |
| LLM taxonomie / prompts | Ollama distant (qwen2.5:7b / qwen3:8b) sur `100.65.24.35:11434` |
| Base de données | PostgreSQL 16 (Docker local, port 5432) |
| API interne | FastAPI (Python) |
| Workers | Asynchrones (1 worker image ComfyUI, 1 worker texte Ollama) |

### 5.2 Mesures de production réelles (PostgreSQL au 24/04/2026)

#### Jobs de génération d'images (`image_generation`)

Basé sur **77 jobs** enregistrés :

| Statut | Nombre | Signification |
|---|---|---|
| `completed` | 60 | Générés avec succès |
| `applied` | 8 | Validés et sélectionnés comme output principal |
| `rejected` | 7 | Générés mais rejetés manuellement |
| `cancelled` | 2 | Annulés |
| **Total images produites** | **68** | 60 PNG Z-Image-Turbo + 8 PNG ERNIE-Image-Turbo |

Toutes les images produites sont en **PNG 1024×1024**.

#### Durées de génération — analyse détaillée

Les données brutes révèlent **deux populations très distinctes** :

**Régime normal (modèle ComfyUI chaud) — 60 jobs `completed`** :

| Métrique | Valeur |
|---|---|
| Durée min | **13 secondes** |
| Durée max | **53 secondes** |
| Durée médiane | **~16–17 secondes** |
| Durée typique | **16–20 secondes** (majorité des jobs) |

**Régime perturbé (jobs bloqués / queue en attente) — 8 jobs `applied` / `rejected` récents** :

| Job | Durée observée | Cause probable |
|---|---|---|
| 7 jobs `rejected` (23/04) | 7 783 – 10 952 secondes (~2-3h) | Jobs en file d'attente pendant que le worker traitait d'autres jobs séquentiellement |
| 3 jobs `applied` (23/04) | 2 917 – 3 088 secondes (~50min) | Même cause : attente en queue |
| 1 job `applied` (22-23/04) | 54 809 secondes (~15h) | Job resté en attente toute une nuit (worker arrêté) |

> **Interprétation** : les durées longues ne reflètent pas le temps de génération GPU, mais le temps d'attente en file de queue. Le **temps de traitement effectif par image est de 13 à 53 secondes**, avec une médiane de **~17 secondes**.

#### Jobs de contenu texte / IA (`image_generate_concepts`)

| Statut | Nombre | Durée observée |
|---|---|---|
| `applied` | 1 | 63 secondes |
| `cancelled` | 1 | 265 secondes (annulé manuellement) |

> Seuls 2 jobs de génération de concepts ont été exécutés via le système de jobs. La plupart des opérations IA (enrichissement taxonomie, création de prompts) sont encore déclenchées directement via les endpoints API synchrones depuis les éditeurs HTML, sans passer par la queue — ce qui signifie qu'elles ne sont pas encore mesurées dans les jobs.

#### Types de jobs IA configurés (non encore utilisés en masse)

| Type | Label | Catégorie |
|---|---|---|
| `image_generate_concepts` | Concepts image (themes / sous-themes) | text |
| `image_prompt_create` | Prompt image : creation (planner+writer) | text |
| `image_prompt_improve` | Prompt image : amelioration | text |
| `image_prompt_validate` | Prompt image : validation score | text |
| `taxonomy_enrich_keywords` | Taxonomie : mots-cles | text |
| `taxonomy_enrich_term` | Taxonomie : enrichir un terme | text |
| `taxonomy_enrich_terms_batch` | Taxonomie : enrichir plusieurs termes | text |
| `taxonomy_generate_vocabulary` | Taxonomie : generer un vocabulaire | text |
| `taxonomy_suggest_children` | Taxonomie : suggerer des enfants | text |

Ces types sont configurés et activés mais n'ont pas encore de jobs exécutés enregistrés en base (en dehors des concepts). Ils sont actuellement appelés de manière synchrone depuis l'interface.

### 5.3 Estimation de débit — génération d'images

En prenant la durée médiane réelle de **17 secondes/image** (modèle chaud, régime normal) :

| Scénario | Débit | Délai pour 1 000 images |
|---|---|---|
| 1 GPU, modèle chaud, en continu | ~210 images/heure | ~4h45 |
| 1 GPU avec pauses opérateur (nuit, redémarrages) | ~100–120 images/heure | ~8–10h |
| 2 GPUs en parallèle (futur, 2 workers) | ~400 images/heure | ~2h30 |

> **Condition clé** : le débit de 210 images/heure suppose le worker actif en continu avec le modèle ComfyUI chargé en VRAM. Dès qu'un arrêt intervient, les jobs s'accumulent en queue mais ne perdent pas leur prompt — ils redémarrent dès la remise en route du worker.

### 5.4 Estimation de débit — production de contenu complet

Pour une image "prête à publier" (statut `approved`), le pipeline enchaîne :

| Étape | Outil | Durée estimée |
|---|---|---|
| Génération de concepts (10 concepts/appel) | Ollama qwen3:8b | ~60–120 secondes |
| Création de prompt par image (planner + writer) | Ollama qwen3:8b | ~30–60 secondes/image |
| Génération d'image | ComfyUI Z-Image-Turbo | ~17 secondes/image |
| Validation / sélection manuelle | Humain | Variable |
| **Total pipeline automatique** | | **~50–180 secondes/image** |

En régime semi-automatique (validation humaine rapide) : **30 à 50 images/heure** de bout en bout (concept → image validée).

### 5.5 Volume de contenu actuel

| Ressource | Nombre |
|---|---|
| Images générées (tous statuts) | 64 (statut `generated`) |
| Outputs PNG produits | 68 (1024×1024) |
| Termes taxonomiques | 88 (vocabulaire `themes`) |
| Taxonomies | 1 (`coloriage`) |
| Vocabulaires | 1 (`themes`) |

La taxonomie couvre désormais 88 termes (vs 49 au moment de la migration DuckDB → PostgreSQL).

---

## 6. Recommandations pour la plateforme

### 6.1 Optimisation des images

Le pipeline livre des **PNG 1024×1024** en source unique. La plateforme est responsable de :

- **Conversion WebP / AVIF** pour le web (gain 30–60% sur le poids)
- **Thumbnails** multi-résolutions (ex. 256×256, 512×512) pour les listings et aperçus
- **Mise en cache CDN** : les images ne changent pas une fois publiées
- **Lazy loading** : les listings de catégories peuvent contenir des dizaines d'images

### 6.2 SEO et structure des pages

Chaque page image doit inclure :

| Élément | Source |
|---|---|
| `<title>` | `title` (image) + nom du terme (`name_i18n.fr`) |
| `<meta description>` | `description_i18n` du terme + contexte image |
| `<h1>` | `title` de l'image |
| Keywords | `keywords` du terme taxonomique associé |
| Balise `alt` | `title` de l'image |
| URL | `/{locale}/coloriage/{slug_i18n}/{image_slug}/` |
| Breadcrumb | Reconstitué via la chaîne `parent_id` de la taxonomie |

### 6.3 Application de coloriage interactive

Les images PNG line art (fond blanc, contours noirs) sont conçues pour être coloriées avec un algorithme de **flood fill** (remplissage par zone). Recommandations :

- Charger l'image PNG en canvas HTML5
- Détecter les contours noirs (seuil ~128 en niveaux de gris) comme frontières
- Proposer une palette de couleurs adaptée à l'âge (couleurs vives, simples)
- Permettre l'export de l'image coloriée en PNG ou JPG

> L'image source n'a **pas de calques** — c'est un PNG aplati. Pour l'application mobile, un prétraitement (vectorisation SVG) peut être envisagé pour améliorer le zoom et le rendu.

### 6.4 Langues supportées

Le pipeline produit du contenu en **3 langues** :

| Code | Langue | Sens d'écriture |
|---|---|---|
| `fr` | Français | LTR |
| `en` | Anglais | LTR |
| `ar` | Arabe (MSA/Fusha) | RTL |

La plateforme doit gérer la direction RTL pour l'arabe (`dir="rtl"` sur le HTML).

### 6.5 Gestion des URLs multilingues

Le pipeline fournit un `slug_i18n` par terme, permettant des URLs localisées :

```
/fr/coloriage/animaux/chats/
/en/coloring/animals/cats/
/ar/تلوين/حيوانات/قطط/
```

---

## 7. Points ouverts et décisions à prendre

| # | Question | Décision souhaitée |
|---|---|---|
| 1 | Format de transfert des fichiers PNG | CDN partagé ou API upload binaire ? |
| 2 | Authentification de l'API plateforme | Token Bearer / OAuth2 ? |
| 3 | Gestion des mises à jour d'images | Remplacement in-place ou nouvelle URL à chaque regénération ? |
| 4 | Dépublication | Suppression physique ou soft-delete ? |
| 5 | Batch de synchronisation | Push événementiel image par image ou batch quotidien ? |
| 6 | Score qualité | La plateforme utilise-t-elle `quality_score` pour ordonner les images ? |
| 7 | Collections / ebooks | Format de livraison des PDFs compilés ? |
| 8 | Application mobile | SVG ou PNG pour le coloriage natif ? |

---

## 8. Évolutions prévues dans le pipeline

| Fonctionnalité | Statut | Impact plateforme |
|---|---|---|
| Module de publication API (push vers plateforme) | **Roadmap** | Implémentera ce contrat |
| Score qualité automatique sur chaque output | Partiel (champ prévu, non peuplé systématiquement) | Permettra un tri qualité |
| Multi-sites (langue, audience) | Schéma en place | Permettra des taxonomies dérivées par site |
| Export PDF d'ebooks | Schéma en place (`export`) | Livraison directe de PDFs compilés |
| Agents autonomes de production | En développement | Augmentera le débit de production |

---

*Document mis à jour le 24/04/2026 — statistiques basées sur la base PostgreSQL de production (77 jobs image_generation, 68 outputs, 88 termes).*
