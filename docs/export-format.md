# Format `data/export/` — contrat de sortie pipeline → alwanbooks-pipeline

Date : 2026-05-12
Version : v0 (MEP)

## Structure

```
data/export/
├── manifest.json
├── images/<r2_slug>.png       (best-effort : peut être manquant si master pas en repo)
└── posts/
    ├── fr/<post_slug>.json
    ├── en/<post_slug>.json
    └── ar/<post_slug>.json
```

Un export = N leaves taxonomiques × 3 locales = 3N fichiers Post + N PNG max.

## Schéma `manifest.json`

```jsonc
{
  "schema_version": "v0",
  "generated_at": "2026-05-12T18:00:00Z",
  "total_leaves_exported": 135,
  "total_publications": 405,
  "leaves": [
    {
      "image_id": "benchmark:poc-scale-benchmark/lion_in_savanna_1024.png",
      "leaf_id": "lion_in_savanna",
      "r2_slug": "lion-in-savanna",
      "post_slugs": {
        "fr": "lion-dans-la-savane",
        "en": "lion-in-savanna",
        "ar": "asad-fi-al-ghaba"
      },
      "status": "ready_for_export",
      "master_present": true
    }
  ]
}
```

- `image_id` : identifiant stable côté pipeline (préfixe `benchmark:` pour les images issues du corpus benchmark POC).
- `r2_slug` : identifiant canonique du master image dans le bucket R2.
  Mêmes 4 URLs `png/webp/thumbs/pdf` pour les 3 locales (cf. contrat §3).
- `post_slugs.<locale>` : slug du Post par locale (peut différer entre locales,
  surtout AR translittéré).
- `status` : toujours `"ready_for_export"` à ce stade (post `mark_image_ready_for_export`).
- `master_present` : `true` si le PNG est dans `data/export/images/`, `false`
  sinon. Si `false`, alwanbooks-pipeline doit récupérer le master depuis sa
  source (ComfyUI bucket d'origine ou autre).

## Schéma Post `posts/<locale>/<post_slug>.json`

Frontmatter conforme contrat Alwan v2.4 (cf. `docs/xchange/PIPELINE-CONTRACT.md` §4).

```jsonc
{
  "schema_version": "v2.4",
  "locale": "fr",
  "slug": "lion-dans-la-savane",
  "r2_slug": "lion-in-savanna",
  "title": "Lion Majestueux : Coloriage pour enfants",
  "title_card": "Lion Majestueux",
  "description": "Colorie ce lion magnifique sous le soleil africain avec des acacias en arrière-plan dans la savane.",
  "keywords": ["lion", "savane", "afrique", "animaux"],
  "categoryId": "",
  "themeIds": [],
  "status": "approved",
  "image_id": "benchmark:poc-scale-benchmark/lion_in_savanna_1024.png",
  "imageSource": "https://assets.alwanbooks.com/coloriages/png/lion-in-savanna.png",
  "imageWeb":    "https://assets.alwanbooks.com/coloriages/webp/lion-in-savanna.webp",
  "imageThumb":  "https://assets.alwanbooks.com/coloriages/thumbs/lion-in-savanna.webp",
  "imagePdf":    "https://assets.alwanbooks.com/coloriages/pdf/lion-in-savanna.pdf",
  "datePublication": "2026-05-12",
  "featured": false,
  "_pipeline": {
    "leaf_id": "lion_in_savanna",
    "name_en": "Lion in Savanna",
    "name_fr": "Lion dans la Savane",
    "name_ar": "أسد في السافانا",
    "i18n_status": "ok",
    "generated_at": "2026-05-12T18:00:00Z"
  }
}
```

### Bornes contractuelles (HARD caps Zod)

Source : contrat plateforme Alwan §4.

| Champ | Min | Max | Sweet spot EN/FR | Sweet spot AR |
|---|---:|---:|---:|---:|
| `title` | 5 | 100 | 40-60 | 25-55 |
| `title_card` | 5 | 40 | ≤30 | ≤25 |
| `description` | 20 | 200 | 80-130 | 40-115 |
| `keywords` | 1 item | 8 items | 3-5 items | 3-5 items |
| `slug` | — | 50 | 15-25 | 15-25 |

Le pipeline garantit **HARD caps strict** sur tous les exports. Tout leaf qui
viole les HARD caps est bloqué (rapport phase liste les coupables).

### Convention métier (i18n)

- **Chiffres en lettres** : les `name_*` source (et donc les `title`/`description`)
  ne doivent contenir aucun chiffre — convention validée 2026-05-12. Le slug
  utilisateur lève `ValueError` sur tout `name_en` commençant par un chiffre.
  Exemple : pas `"3 pommes"` mais `"trois pommes"`.
- **Slugs AR pré-translittérés** : aucun caractère non-ASCII en URL côté Astro.
  La pipeline produit des slugs latins (ex. `"أسد في الغابة"` → `"asad-fi-al-ghaba"`).
- **R2 slug unique cross-locale** : les 3 Posts d'un même leaf référencent
  les MÊMES URLs `image*` (un seul `r2_slug` pour les 4 variants R2).

## Comment alwanbooks-pipeline consomme

1. Cloner ou pull périodique du repo `artiste-coloriage`.
2. Lire `data/export/manifest.json` pour obtenir la liste des leaves.
3. Pour chaque leaf :
   - Récupérer le master (depuis `data/export/images/<r2_slug>.png` si présent,
     sinon depuis la source d'origine pipeline ComfyUI).
   - Produire les 4 variants R2 (PNG / WebP / Thumb / PDF) — cf. contrat §3.
   - Upload atomique vers Cloudflare R2.
4. Pour chaque locale présente :
   - Lire `data/export/posts/<locale>/<post_slug>.json`.
   - Générer le fichier MD Astro `src/content/posts/<locale>/<post_slug>.md`
     dans le repo `rimalab-v2`.
   - Push sur `rimalab-v2/main` (HTTPS via PAT ou SSH key).

## Idempotence

Le script `scripts/export_mep_v0.py` est idempotent :

- Rerun = UPSERT pur côté DB (`image`, `image_publication`).
- Fichiers Post écrasés sur place (pas de doublon avec suffixe).
- Manifest réécrit avec le nouveau timestamp `generated_at`.

Voir `docs/reports/2026-05-12_phase-mep-v0-C-export-data.md` pour le rapport
de la phase MEP v0/C.
