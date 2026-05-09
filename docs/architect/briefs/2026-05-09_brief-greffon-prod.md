# Brief — Greffon prod (P4)

Date : 2026-05-09
Auteur : architecte / PMO
Destinataire : claude-code dev
Prérequis : brief Annotateur v2 livré (P3 schéma annotation acté)

## Objectif

Brancher l'annotateur (livré en v2) sur les **images générées par la pipeline production**, pour permettre l'annotation humaine sur les `image_output` issus des jobs `image_generation`.

**Contraintes de design** (actées par utilisateur) :
- Le **modèle de données de l'annotateur ne change pas** — on réutilise schéma P3 (score 1-6, image_tags, prompt_tags, custom_tags, flags).
- **Pas d'intégration profonde** dans la pipeline — on **greffe** par mapping, sans remplacer le flow `awaiting_validation` → `apply/reject` existant.
- **Pas de boutons apply/reject** dans l'annotateur — le `jobs_editor.html` continue de gérer la validation effective des jobs.
- **Évolutions pipeline = mineures** — on s'autorise quelques ajouts de champs sur `image_output` ou helpers de jointure si vraiment nécessaire pour exposer ce qu'il faut à l'annotateur.

## Architecture cible

### Table `annotation` polymorphe

Une seule table qui peut s'attacher à n'importe quel objet de la pipeline (`image_output` en cible principale, mais extensible à `image`, `term`, etc.).

```sql
CREATE TABLE annotation (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  target_type   TEXT NOT NULL,            -- 'image_output' (cible prod par défaut)
  target_id     TEXT NOT NULL,
  score         INTEGER,                  -- 1-6
  image_tags    JSON,
  prompt_tags   JSON,
  custom_tags   JSON,
  pattern       BOOLEAN DEFAULT FALSE,
  pattern_note  TEXT,
  sample        BOOLEAN DEFAULT FALSE,
  publishable   BOOLEAN DEFAULT FALSE,
  created_at    TIMESTAMP NOT NULL,
  updated_at    TIMESTAMP NOT NULL,
  UNIQUE (target_type, target_id)
);

CREATE INDEX idx_annotation_target ON annotation(target_type, target_id);
CREATE INDEX idx_annotation_updated ON annotation(updated_at);
```

**Contraintes** :
- Pas de FK explicite (polymorphe) — intégrité gérée applicativement
- `target_type` validé par whitelist côté API (initialement : `image_output`, plus tard `image`, `term`, …)
- JSON fields : `TEXT` côté SQLite, `JSONB` côté Postgres (cf. CLAUDE.md "Tests doivent rester SQLite-portables") — sérialiser/désérialiser explicitement dans le code, ne pas s'appuyer sur opérateurs JSON Postgres

Migration Alembic : `alembic/versions/0006_annotation_polymorphic.py`

### Mapping (couche adaptateur côté API)

L'annotateur (front) travaille avec un **objet abstrait** :

```typescript
type AnnotatorItem = {
  filename: string;          // basename pour l'affichage
  image_url: string;         // URL servie par l'API
  prompt: string;
  negative: string;
  metrics?: {                // QC machine si dispo
    histogram?: any;
    vision_qc?: any;
  };
  workflow_class?: string;
  technique?: string;
  pipeline?: string;
  confidence?: string;
  pitfalls?: string[];
  // ── identifiants pour la persistance polymorphe ──
  target_type: string;       // 'image_output' en prod, 'benchmark_file' en POC
  target_id: string;         // image_output.id en prod
  annotation?: AnnotationV2; // schéma P3
};
```

Adaptateurs côté back :

| Source | Adaptateur (back) |
|---|---|
| Benchmark `data/<dir>/` | Existant : `src/api/routes/benchmark.py` (`/api/benchmark/images`) — inchangé. Renvoie `target_type='benchmark_file'`, `target_id=dir+filename` (à brancher si on veut unifier le persist, sinon reste sur fichier `annotations.json`) |
| Production `image_output` | **NOUVEAU** : `src/api/routes/review.py` (`/api/review/queue`) — joint `image_output → image → job` et expose le contrat `AnnotatorItem` |

→ Le benchmark continue de persister dans `annotations.json` (statu quo). Le greffon prod persiste en table `annotation`.

### Endpoints REST (3 routes, pas de GraphQL)

#### `GET /api/review/queue`

```
Query params:
  status    : 'awaiting_validation' | 'generated' | 'approved' | 'all' (défaut: 'awaiting_validation')
  workflow_class : optional, filtre
  limit     : optional, défaut 50
  offset    : optional, défaut 0
```

Retour :
```json
{
  "count": 12,
  "items": [
    {
      "filename": "<basename(image_output.file_path)>",
      "image_url": "/api/review/file?image_output_id=<id>",
      "prompt": "<image.prompt>",
      "negative": "<image.negative_prompt>",
      "metrics": { "histogram": {...}, "vision_qc": {...} },
      "target_type": "image_output",
      "target_id": "<image_output.id>",
      "annotation": { "score": 4, "image_tags": [...], ... } | null,
      // métadonnées pipeline
      "image_id": "<image.id>",
      "job_id": "<job.id>",
      "image_status": "generating",
      "job_status": "awaiting_validation"
    },
    ...
  ]
}
```

Implémentation : LEFT JOIN entre `image_output`, `image`, `job`, `annotation` (où `target_type='image_output' AND target_id=image_output.id`).

#### `GET /api/review/file?image_output_id=<id>`

Sert le fichier image depuis `image_output.file_path` (chemin relatif → résolution sur `OUTPUTS_DIR.parent`).

Sécurité : valider que `image_output_id` existe en DB (sinon 404). Pas d'accès direct au filesystem.

#### `POST /api/annotation` (générique, polymorphe)

```json
Request:
{
  "target_type": "image_output",
  "target_id": "<id>",
  "score": 4,
  "image_tags": ["image_compo_bonne", ...],
  "prompt_tags": [...],
  "custom_tags": [...],
  "flags": {
    "pattern": true,
    "pattern_note": "...",
    "sample": false,
    "publishable": false
  }
}

Response 200:
{
  "annotation": { /* l'annotation persistée avec updated_at */ }
}
```

Comportement : **upsert** sur `(target_type, target_id)`. Si `target_type` n'est pas dans la whitelist (initialement `['image_output']`), retourner 400.

Validation :
- `score` ∈ [1, 6] ou null
- `image_tags`, `prompt_tags` : valeurs dans la whitelist du schéma P3 ; tags inconnus → 400
- `custom_tags` : libres
- `target_id` : doit exister (vérification light : existence ligne en DB pour le `target_type` donné)

#### (Hors scope P4) `GET /api/annotation?target_type=...&target_id=...`

Pas nécessaire : `/api/review/queue` joint déjà l'annotation. Endpoint à ajouter dans un cycle ultérieur si un usage isolé apparaît.

## UI annotateur — mode switch

Ajout d'un sélecteur de mode dans le header sticky :

```
Mode: ⦿ Benchmark    ○ Production
  ⦿ → dir [autocomplete]    [Charger]
  ○ → status [awaiting | generated | approved | all]
       count: 12 images   |  filtre: workflow_class=...
```

URL paramétrée :
- `?mode=benchmark&dir=poc-scale-bench-XXX` (défaut, rétrocompat)
- `?mode=production&status=awaiting_validation`

Le mode est persisté en localStorage pour la session suivante.

**Pas de boutons apply/reject** dans l'annotateur (la validation jobs reste dans `jobs_editor.html`).

Le reste de l'UI (grille P3, score, raccourcis P2, lightbox P1) est **identique entre les deux modes** — un seul code de rendu. Seule différence : la source des items + la cible de persistance.

### Indicateur visuel mode prod

- Badge "PROD" coloré dans le header (orange ou rouge léger) pour éviter toute confusion avec le mode benchmark
- Le filename affiché est le `basename` de `image_output.file_path` ; on peut afficher en sous-titre `image_id` + `job_id` pour la traçabilité

## Évolutions pipeline mineures (à valider à l'implémentation)

Possible ajout sur `image_output` si nécessaire pour l'affichage :

- Aucune **évolution bloquante** identifiée : `image_output` a déjà `id, image_id, job_id, file_path, quality_score, model_name, model_config`. Le `prompt` et `negative_prompt` sont sur `image` (jointure simple).
- À considérer (optionnel) : exposer le QC machine du job dans `image_output.qc_summary` (denormalize JSON court) pour éviter de re-parser `job.result` à chaque appel `/api/review/queue`. **Pas requis pour cette première version.**

## Fichiers concernés

- `alembic/versions/0006_annotation_polymorphic.py` — **NEW**
- `src/api/models.py` — ajout du modèle `Annotation`
- `src/api/routes/review.py` — **NEW** routeur dédié
- `src/api/routes/__init__.py` ou `src/api/main.py` — montage du routeur
- `src/api/db.py` — éventuels helpers JSON sérialisation SQLite-compat
- `data/benchmark-annotator.html` — ajout du mode switch + branchement des nouveaux endpoints en mode prod
- `tests/test_review_routes.py` — **NEW** : queue, annotate (upsert), validation, sécurité
- `docs/workflow-pipeline.md` — section "Annotation humaine en mode prod"

## Critères d'acceptation

- [ ] Migration `0006_annotation_polymorphic.py` appliquée Postgres + tests in-memory SQLite verts
- [ ] `GET /api/review/queue` retourne bien les `image_output` joints avec leur annotation éventuelle
- [ ] `GET /api/review/file` sert correctement les fichiers, refuse les ids invalides
- [ ] `POST /api/annotation` upsert OK, validation tags/score, refus `target_type` hors whitelist
- [ ] UI mode switch fonctionnel (URL + persistance localStorage)
- [ ] Badge "PROD" visible dans le header en mode prod
- [ ] Grille P3, raccourcis P2, lightbox P1 fonctionnent identiquement dans les 2 modes
- [ ] **Aucune route `/api/jobs/*` modifiée** — pipeline existante intacte
- [ ] **Aucun test de `tests/test_jobs_routes.py` cassé**
- [ ] Tests `test_review_routes.py` couvrent : queue empty, queue with annotation, annotate upsert, validation 400, sécurité 404
- [ ] Doc `docs/workflow-pipeline.md` mise à jour
- [ ] Rapport `docs/reports/2026-05-XX_phase-greffon-prod.md` produit

## Hors-scope (notes pour cycles futurs)

- Annotation polymorphe sur `term`, `image` (entité), `job` — la table le permet, à activer quand un cas d'usage se présente.
- Auto-décision apply/reject basée sur tags/score — à évaluer après volume d'usage réel.
- Dashboard d'agrégation des annotations (par concept, workflow_class, défaut, score moyen).
- BFF / GraphQL — à reconsidérer quand plusieurs consommateurs (dashboard, annotateur, autre éditeur) auront besoin de la même donnée projetée différemment.
- Migration éventuelle des `data/<dir>/annotations.json` benchmark vers la table polymorphe (`target_type='benchmark_file'`) — non prioritaire, statu quo OK.

## Estimation dev

| Bloc | Estimation |
|---|---|
| Alembic migration `0006` + modèle SQLAlchemy + tests SQLite-compat | ~1.5h |
| Endpoints back (queue, file, annotation upsert) + helpers JSON | ~2h |
| UI mode switch + badge PROD + branchement endpoints | ~1.5h |
| Tests intégration | ~1h |
| Doc + rapport | ~30 min |
| **Total** | **~6.5h** |

## Points d'attention

- **Whitelist `target_type`** : initialement `['image_output']`. Toute extension future doit passer par une review explicite (un nouveau type = un nouvel adaptateur API et une UI éventuellement adaptée).
- **Annotation conservée même après apply/reject** : si un job est apply/reject par le `jobs_editor.html`, l'annotation sur `image_output` reste en table — c'est une trace audit.
- **Mode prod par défaut au chargement** : NON. Benchmark par défaut (rétrocompat URL/bookmarks). Le mode prod s'active explicitement via le toggle ou `?mode=production`.
- **Indicateur visuel PROD** : non négociable pour éviter qu'un annotateur ne croie travailler sur du benchmark alors qu'il modifie de la donnée prod.
