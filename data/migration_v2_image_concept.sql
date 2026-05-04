-- =============================================================================
-- Migration v2 — Image Concept Pipeline
-- À appliquer UNE SEULE FOIS sur artiste_coloriage.duckdb
-- Commande : duckdb data/artiste_coloriage.duckdb < data/migration_v2_image_concept.sql
-- =============================================================================

-- 1. Nouvelles colonnes sur la table image (concept)
-- Note: DuckDB ne supporte pas ADD COLUMN IF NOT EXISTS ; ignorer les erreurs "already exists"
ALTER TABLE image ADD COLUMN title TEXT;
ALTER TABLE image ADD COLUMN prompt TEXT;
ALTER TABLE image ADD COLUMN selected_output_id TEXT;
ALTER TABLE image ADD COLUMN origin_type TEXT DEFAULT 'manual';
ALTER TABLE image ADD COLUMN origin_batch_id TEXT;
ALTER TABLE image ADD COLUMN origin_term_id TEXT;
ALTER TABLE image ADD COLUMN origin_taxonomy_id TEXT;

-- 2. Créer la table image_output si elle n'existe pas encore
CREATE TABLE IF NOT EXISTS image_output (
  id TEXT PRIMARY KEY,
  image_id TEXT NOT NULL REFERENCES image(id),
  job_id TEXT REFERENCES job(id),
  file_path TEXT NOT NULL,
  file_format TEXT,
  width INTEGER,
  height INTEGER,
  quality_score REAL,
  model_name TEXT,
  model_config TEXT,
  created_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_image_output_image ON image_output(image_id);
CREATE INDEX IF NOT EXISTS idx_image_output_job ON image_output(job_id);

-- 3. Créer les tables generation_batch si elles n'existent pas encore
CREATE TABLE IF NOT EXISTS generation_batch (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  scope_type TEXT DEFAULT 'terms',
  prompt_strategy TEXT DEFAULT 'ai_ollama',
  images_per_term INTEGER DEFAULT 5,
  auto_approve_threshold REAL,
  status TEXT DEFAULT 'pending',
  created_at TEXT,
  updated_at TEXT
);

CREATE TABLE IF NOT EXISTS generation_batch_term (
  batch_id TEXT NOT NULL REFERENCES generation_batch(id),
  term_id TEXT NOT NULL,
  taxonomy_id TEXT NOT NULL REFERENCES taxonomy(taxonomy_id),
  include_subtree INTEGER DEFAULT 0,
  PRIMARY KEY (batch_id, term_id, taxonomy_id)
);

-- 4. Migrer les images existantes avec file_path vers image_output
--    Seules les images ayant un file_path non vide sont migrées
INSERT INTO image_output (
  id, image_id, job_id, file_path, file_format,
  width, height, quality_score, model_name, created_at
)
SELECT
  'out_' || id,
  id,
  job_id,
  file_path,
  file_format,
  width,
  height,
  quality_score,
  model_name,
  COALESCE(created_at, strftime('%Y-%m-%dT%H:%M:%SZ', now()))
FROM image
WHERE file_path IS NOT NULL
  AND file_path != ''
  AND NOT EXISTS (
    SELECT 1 FROM image_output WHERE id = 'out_' || image.id
  );

-- 5. Mettre à jour les colonnes concept sur les images migrées
UPDATE image SET
  selected_output_id = CASE
    WHEN file_path IS NOT NULL AND file_path != ''
    THEN 'out_' || id
    ELSE NULL
  END,
  title = CASE
    WHEN title IS NULL OR title = ''
    THEN COALESCE(
      NULLIF(TRIM(prompt_used), ''),
      id
    )
    ELSE title
  END,
  prompt = CASE
    WHEN prompt IS NULL OR prompt = ''
    THEN prompt_used
    ELSE prompt
  END,
  status = CASE
    WHEN status = 'raw'      THEN 'generated'
    WHEN status = 'reviewed' THEN 'generated'
    WHEN status = 'approved' THEN 'approved'
    WHEN status = 'rejected' THEN 'rejected'
    ELSE COALESCE(status, 'draft')
  END,
  origin_type = COALESCE(origin_type, 'manual');

-- 6. Ajouter les index manquants (idempotents)
CREATE INDEX IF NOT EXISTS idx_image_batch ON image(origin_batch_id);
CREATE INDEX IF NOT EXISTS idx_image_term  ON image(origin_term_id);
CREATE INDEX IF NOT EXISTS idx_gen_batch_status ON generation_batch(status);

-- =============================================================================
-- Vérification post-migration (à exécuter pour contrôle)
-- SELECT COUNT(*) AS images_total   FROM image;
-- SELECT COUNT(*) AS outputs_migrés FROM image_output;
-- SELECT status, COUNT(*) FROM image GROUP BY status ORDER BY status;
-- =============================================================================
