-- Schéma DuckDB – Artiste Coloriage
-- Base : data/artiste_coloriage.duckdb

-- Locales (registre des langues supportées)
CREATE TABLE IF NOT EXISTS locale (
  code TEXT PRIMARY KEY,
  name TEXT,
  is_default INTEGER DEFAULT 0,
  sort_order INTEGER DEFAULT 0
);

INSERT OR IGNORE INTO locale (code, name, is_default, sort_order) VALUES
  ('fr', 'Français', 1, 0),
  ('en', 'English', 0, 1),
  ('ar', 'العربية', 0, 2);

-- Taxonomy (champs i18n en JSON)
CREATE TABLE IF NOT EXISTS taxonomy (
  taxonomy_id TEXT PRIMARY KEY,
  label_i18n TEXT,
  languages TEXT,
  created_at TEXT,
  updated_at TEXT
);

CREATE TABLE IF NOT EXISTS vocabulary (
  id TEXT PRIMARY KEY,
  taxonomy_id TEXT NOT NULL REFERENCES taxonomy(taxonomy_id),
  label_i18n TEXT,
  created_at TEXT,
  updated_at TEXT
);

CREATE TABLE IF NOT EXISTS term (
  id TEXT NOT NULL,
  vocabulary_id TEXT NOT NULL REFERENCES vocabulary(id),
  parent_id TEXT,
  slug TEXT NOT NULL,
  slug_i18n TEXT,
  name_i18n TEXT,
  description_i18n TEXT,
  weight INTEGER DEFAULT 0,
  keywords TEXT,
  created_at TEXT,
  updated_at TEXT,
  PRIMARY KEY (id, vocabulary_id),
  FOREIGN KEY (vocabulary_id) REFERENCES vocabulary(id)
);

CREATE INDEX IF NOT EXISTS idx_term_vocab_parent ON term(vocabulary_id, parent_id);
CREATE INDEX IF NOT EXISTS idx_term_vocab_weight ON term(vocabulary_id, weight);

-- Sites
CREATE TABLE IF NOT EXISTS site (
  id TEXT PRIMARY KEY,
  name_i18n TEXT,
  base_url TEXT,
  default_locale TEXT,
  country TEXT,
  audience TEXT,
  taxonomy_config_path TEXT,
  active INTEGER DEFAULT 1,
  created_at TEXT,
  updated_at TEXT
);

CREATE TABLE IF NOT EXISTS site_taxonomy (
  site_id TEXT PRIMARY KEY REFERENCES site(id),
  source_taxonomy_id TEXT REFERENCES taxonomy(taxonomy_id),
  config_path TEXT,
  created_at TEXT,
  updated_at TEXT
);

-- Jobs
CREATE TABLE IF NOT EXISTS job (
  id TEXT PRIMARY KEY,
  type TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending',
  config TEXT,
  started_at TEXT,
  finished_at TEXT,
  error_message TEXT,
  created_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_job_type ON job(type);
CREATE INDEX IF NOT EXISTS idx_job_status ON job(status);

-- Images
CREATE TABLE IF NOT EXISTS image (
  id TEXT PRIMARY KEY,
  file_path TEXT NOT NULL,
  file_format TEXT,
  width INTEGER,
  height INTEGER,
  status TEXT DEFAULT 'raw',
  quality_score REAL,
  prompt_used TEXT,
  negative_prompt TEXT,
  model_name TEXT,
  job_id TEXT REFERENCES job(id),
  created_at TEXT,
  updated_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_image_status ON image(status);
CREATE INDEX IF NOT EXISTS idx_image_job ON image(job_id);

CREATE TABLE IF NOT EXISTS image_taxonomy_tag (
  image_id TEXT NOT NULL REFERENCES image(id),
  taxonomy_id TEXT NOT NULL REFERENCES taxonomy(taxonomy_id),
  term_id TEXT NOT NULL,
  created_at TEXT,
  PRIMARY KEY (image_id, taxonomy_id, term_id)
);

-- Collections
CREATE TABLE IF NOT EXISTS collection (
  id TEXT PRIMARY KEY,
  slug TEXT NOT NULL UNIQUE,
  name_i18n TEXT,
  term_id TEXT,
  taxonomy_id TEXT REFERENCES taxonomy(taxonomy_id),
  created_at TEXT,
  updated_at TEXT
);

CREATE TABLE IF NOT EXISTS collection_image (
  collection_id TEXT NOT NULL REFERENCES collection(id),
  image_id TEXT NOT NULL REFERENCES image(id),
  sort_order INTEGER DEFAULT 0,
  created_at TEXT,
  PRIMARY KEY (collection_id, image_id)
);

-- Exports
CREATE TABLE IF NOT EXISTS export (
  id TEXT PRIMARY KEY,
  type TEXT NOT NULL,
  collection_id TEXT REFERENCES collection(id),
  site_id TEXT REFERENCES site(id),
  output_path TEXT,
  job_id TEXT REFERENCES job(id),
  status TEXT DEFAULT 'pending',
  error_message TEXT,
  created_at TEXT,
  completed_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_export_collection ON export(collection_id);
CREATE INDEX IF NOT EXISTS idx_export_site ON export(site_id);

-- Publications
CREATE TABLE IF NOT EXISTS site_publication (
  image_id TEXT NOT NULL REFERENCES image(id),
  site_id TEXT NOT NULL REFERENCES site(id),
  status TEXT DEFAULT 'pending',
  published_url TEXT,
  published_at TEXT,
  created_at TEXT,
  updated_at TEXT,
  PRIMARY KEY (image_id, site_id)
);

-- Phase 2: Concepts et prompts
CREATE TABLE IF NOT EXISTS concept_batch (
  id TEXT PRIMARY KEY,
  job_id TEXT REFERENCES job(id),
  term_id TEXT,
  theme_input TEXT,
  concepts TEXT,
  prompts TEXT,
  llm_provider TEXT,
  llm_model TEXT,
  created_at TEXT
);

CREATE TABLE IF NOT EXISTS prompt_template (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  template TEXT NOT NULL,
  description TEXT,
  active INTEGER DEFAULT 1,
  created_at TEXT,
  updated_at TEXT
);

-- Phase 3: Config génération
CREATE TABLE IF NOT EXISTS generation_config (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  model_name TEXT,
  lora_path TEXT,
  params TEXT,
  active INTEGER DEFAULT 1,
  created_at TEXT,
  updated_at TEXT
);

-- Phase 4: Pipeline et post-traitement
CREATE TABLE IF NOT EXISTS pipeline_run (
  id TEXT PRIMARY KEY,
  theme_input TEXT,
  term_id TEXT,
  concept_job_id TEXT REFERENCES job(id),
  generation_job_id TEXT REFERENCES job(id),
  postprocess_job_id TEXT REFERENCES job(id),
  export_job_id TEXT REFERENCES job(id),
  status TEXT DEFAULT 'pending',
  created_at TEXT,
  completed_at TEXT
);

CREATE TABLE IF NOT EXISTS image_postprocess (
  image_id TEXT PRIMARY KEY REFERENCES image(id),
  job_id TEXT REFERENCES job(id),
  params TEXT,
  input_path TEXT,
  output_path TEXT,
  created_at TEXT
);

CREATE TABLE IF NOT EXISTS coverage_stats (
  term_id TEXT NOT NULL,
  taxonomy_id TEXT NOT NULL REFERENCES taxonomy(taxonomy_id),
  image_count INTEGER DEFAULT 0,
  collection_count INTEGER DEFAULT 0,
  computed_at TEXT,
  PRIMARY KEY (term_id, taxonomy_id)
);

-- Phase 5: Sync sites
CREATE TABLE IF NOT EXISTS site_sync (
  id TEXT PRIMARY KEY,
  site_id TEXT NOT NULL REFERENCES site(id),
  job_id TEXT REFERENCES job(id),
  sync_type TEXT,
  collections_synced TEXT,
  images_synced INTEGER,
  status TEXT DEFAULT 'pending',
  error_message TEXT,
  started_at TEXT,
  completed_at TEXT
);

CREATE TABLE IF NOT EXISTS site_deployment (
  site_id TEXT PRIMARY KEY REFERENCES site(id),
  deploy_type TEXT,
  config TEXT,
  last_sync_at TEXT,
  updated_at TEXT
);

-- Phase 6: Agent
CREATE TABLE IF NOT EXISTS agent_run (
  id TEXT PRIMARY KEY,
  status TEXT DEFAULT 'running',
  goal TEXT,
  started_at TEXT,
  completed_at TEXT,
  created_at TEXT
);

CREATE TABLE IF NOT EXISTS agent_action (
  id TEXT PRIMARY KEY,
  agent_run_id TEXT NOT NULL REFERENCES agent_run(id),
  tool_name TEXT NOT NULL,
  tool_input TEXT,
  tool_output TEXT,
  status TEXT DEFAULT 'pending',
  approved_by TEXT,
  approved_at TEXT,
  created_at TEXT
);

CREATE TABLE IF NOT EXISTS suggested_topic (
  id TEXT PRIMARY KEY,
  term_id TEXT NOT NULL,
  agent_run_id TEXT REFERENCES agent_run(id),
  reason TEXT,
  image_count INTEGER,
  target_count INTEGER,
  status TEXT DEFAULT 'pending',
  created_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_agent_action_run ON agent_action(agent_run_id);
CREATE INDEX IF NOT EXISTS idx_suggested_topic_run ON suggested_topic(agent_run_id);
CREATE INDEX IF NOT EXISTS idx_suggested_topic_status ON suggested_topic(status);
