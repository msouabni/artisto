-- Requêtes utiles pour explorer les données seed via MCP DuckDB
-- Base : data/artiste_coloriage.duckdb
-- MCP config : .cursor/mcp.json (mcp-server-duckdb)

-- Vue d'ensemble des images avec statut
SELECT id, title, status, origin_term_id, origin_type, origin_batch_id
FROM image
ORDER BY status, created_at DESC;

-- Jobs par type et statut
SELECT id, type, status, started_at, finished_at, error_message
FROM job
ORDER BY type, created_at DESC;

-- Sites actifs
SELECT id, base_url, default_locale, country, audience
FROM site
WHERE active = 1;

-- Batches de génération
SELECT gb.id, gb.name, gb.status, gb.scope_type, gb.prompt_strategy,
       COUNT(gbt.term_id) AS nb_terms
FROM generation_batch gb
LEFT JOIN generation_batch_term gbt ON gbt.batch_id = gb.id
GROUP BY gb.id, gb.name, gb.status, gb.scope_type, gb.prompt_strategy;

-- Images avec leurs outputs et job associé
SELECT i.id, i.title, i.status, io.id AS output_id, io.file_path, j.type AS job_type, j.status AS job_status
FROM image i
LEFT JOIN image_output io ON io.image_id = i.id
LEFT JOIN job j ON j.id = io.job_id
ORDER BY i.id, io.created_at DESC;
