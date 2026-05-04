-- =============================================================================
-- Migration v5 — Suppression des index sur image (workaround bug DuckDB FK)
-- À appliquer UNE SEULE FOIS sur artiste_coloriage.duckdb
-- Commande : python scripts/run_migration_v5.py
-- =============================================================================
--
-- Contexte : DuckDB a un bug connu (issue #20246) : un UPDATE sur une colonne
-- indexée déclenche une fausse violation FK "still referenced" quand la table
-- est référencée (image_output, job, etc.). Workaround : supprimer les index
-- sur les colonnes non-PK de la table image.
--
-- Index supprimés : idx_image_status, idx_image_batch, idx_image_term, idx_image_job
--

DROP INDEX IF EXISTS idx_image_status;
DROP INDEX IF EXISTS idx_image_batch;
DROP INDEX IF EXISTS idx_image_term;
DROP INDEX IF EXISTS idx_image_job;
