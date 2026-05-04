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
  image_id TEXT,                    -- FK logique → image(id), déprécié : préférer entity_type/entity_id
  config TEXT,
  started_at TEXT,
  finished_at TEXT,
  error_message TEXT,
  created_at TEXT,
  priority INTEGER DEFAULT 5,
  retry_count INTEGER DEFAULT 0,
  max_retries INTEGER DEFAULT 3,
  scheduled_at TEXT,
  entity_type TEXT,
  entity_id TEXT,
  result TEXT,
  external_ref_id TEXT,
  progress INTEGER DEFAULT 0,
  progress_message TEXT,
  worker_id TEXT,
  last_heartbeat_at TEXT,
  batch_ref TEXT
);

CREATE TABLE IF NOT EXISTS job_type_config (
  type TEXT PRIMARY KEY,
  label TEXT,
  enabled INTEGER DEFAULT 0,
  max_concurrent INTEGER DEFAULT 1,
  description TEXT,
  category TEXT,
  updated_at TEXT
);

-- Index désactivés : DuckDB bug #20246 (même que image)
-- CREATE INDEX IF NOT EXISTS idx_job_type ON job(type);
-- CREATE INDEX IF NOT EXISTS idx_job_status ON job(status);
-- CREATE INDEX IF NOT EXISTS idx_job_image ON job(image_id);

-- Images
-- La table image représente le concept/idée d'image (indépendant du fichier généré).
-- Les fichiers générés sont stockés dans image_output.
-- Les colonnes fichier (file_path, etc.) sont conservées pour compatibilité descendante.
CREATE TABLE IF NOT EXISTS image (
  id TEXT PRIMARY KEY,
  -- Concept
  title TEXT,
  prompt TEXT,
  negative_prompt TEXT,
  -- Status pipeline: draft | prompt_ready | scheduled | generating | generated | approved | rejected | published
  status TEXT DEFAULT 'draft',
  -- Output sélectionné (validé)
  selected_output_id TEXT,      -- FK → image_output (résolu après creation de image_output)
  current_job_id TEXT,          -- job dont on affiche l'output ; si NULL = dernier créé
  -- Traçabilité origine
  origin_type TEXT DEFAULT 'manual',    -- 'manual' | 'batch'
  origin_batch_id TEXT,                 -- FK → generation_batch
  origin_term_id TEXT,                  -- terme taxonomie source
  origin_taxonomy_id TEXT,              -- taxonomie source
  -- Colonnes legacy (conservées pour compatibilité, données migrées vers image_output)
  file_path TEXT,
  file_format TEXT,
  width INTEGER,
  height INTEGER,
  quality_score REAL,
  prompt_used TEXT,
  model_name TEXT,
  job_id TEXT,                      -- déprécié : utiliser job.image_id
  created_at TEXT,
  updated_at TEXT
);

-- Index désactivés : DuckDB bug #20246 — UPDATE sur colonne indexée déclenche
-- fausse violation FK "still referenced". Utiliser migration_v5 pour bases existantes.
-- CREATE INDEX IF NOT EXISTS idx_image_status ON image(status);
-- CREATE INDEX IF NOT EXISTS idx_image_batch ON image(origin_batch_id);
-- CREATE INDEX IF NOT EXISTS idx_image_term ON image(origin_term_id);

-- Outputs de génération : chaque tentative de job produit un output rattaché au concept
-- file_path et/ou text_content (au moins un pour job completed)
CREATE TABLE IF NOT EXISTS image_output (
  id TEXT PRIMARY KEY,
  image_id TEXT NOT NULL REFERENCES image(id),
  job_id TEXT REFERENCES job(id),
  file_path TEXT NOT NULL,           -- '' si output texte-only
  text_content TEXT,                -- contenu texte (log, erreur, etc.)
  file_format TEXT,
  width INTEGER,
  height INTEGER,
  quality_score REAL,
  model_name TEXT,
  model_config TEXT,   -- JSON snapshot des paramètres du job au moment de la génération
  created_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_image_output_image ON image_output(image_id);
CREATE INDEX IF NOT EXISTS idx_image_output_job ON image_output(job_id);

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

-- Batch de génération : campagne couvrant N termes taxonomiques
CREATE TABLE IF NOT EXISTS generation_batch (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  scope_type TEXT DEFAULT 'terms',          -- 'terms' | 'subtree'
  prompt_strategy TEXT DEFAULT 'ai_ollama', -- 'manual' | 'ai_ollama' | 'template'
  images_per_term INTEGER DEFAULT 5,
  auto_approve_threshold REAL,              -- NULL = validation manuelle, ex 7.5 = auto si score >= 7.5
  status TEXT DEFAULT 'pending',            -- pending | prompts_ready | scheduled | running | done
  created_at TEXT,
  updated_at TEXT
);

CREATE TABLE IF NOT EXISTS generation_batch_term (
  batch_id TEXT NOT NULL REFERENCES generation_batch(id),
  term_id TEXT NOT NULL,
  taxonomy_id TEXT NOT NULL REFERENCES taxonomy(taxonomy_id),
  include_subtree INTEGER DEFAULT 0,        -- 0 = terme seul, 1 = terme + tous ses enfants
  PRIMARY KEY (batch_id, term_id, taxonomy_id)
);

CREATE INDEX IF NOT EXISTS idx_gen_batch_status ON generation_batch(status);

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

-- Prompts IA Ollama (surcharge DuckDB > fallback taxonomy_prompts.yaml)
CREATE TABLE IF NOT EXISTS ai_prompt_template (
  key TEXT PRIMARY KEY,      -- enrich_term | suggest_children | generate_vocabulary | enrich_keywords
  system_text TEXT NOT NULL,
  user_text TEXT NOT NULL,
  model TEXT,
  temperature REAL,
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
