-- =============================================================================
-- Migration v6 — Suppression des index sur job (workaround bug DuckDB FK)
-- À appliquer UNE SEULE FOIS sur artiste_coloriage.duckdb
-- Commande : python scripts/run_migration_v6.py
-- =============================================================================
--
-- Même bug #20246 : UPDATE sur job.status déclenche fausse violation FK
-- car image_output référence job. Workaround : supprimer les index sur job.
--

DROP INDEX IF EXISTS idx_job_status;
DROP INDEX IF EXISTS idx_job_type;
DROP INDEX IF EXISTS idx_job_image;
