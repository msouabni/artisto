#!/usr/bin/env python3
"""Script temporaire pour mettre à jour les use cases."""
path = "docs/use-cases/use_cases.yaml"
with open(path, "r", encoding="utf-8") as f:
    content = f.read()

# GEN_CONCEPTS_FROM_THEME: planned -> done
old1 = """      - id: GEN_CONCEPTS_FROM_THEME
        title: "Générer des concepts à partir d'un thème"
        phase: 2
        actors: ["admin_plateforme", "agent_systeme"]
        status: planned"""
new1 = """      - id: GEN_CONCEPTS_FROM_THEME
        title: "Générer des concepts à partir d'un thème"
        phase: 2
        actors: ["admin_plateforme", "agent_systeme"]
        status: done"""
content = content.replace(old1, new1)

# GEN_IMAGES_FROM_PROMPTS
old2 = """      - id: GEN_IMAGES_FROM_PROMPTS
        title: "Générer des images à partir de prompts"
        phase: 3
        actors: ["agent_systeme"]
        status: planned
        description: "Générer un lot d'images line art à partir de prompts, en local via Diffusers."
        related_files:
          - "src/image_generation.py"
          - "architecture.md" """
new2 = """      - id: GEN_IMAGES_FROM_PROMPTS
        title: "Générer des images à partir de prompts"
        phase: 3
        actors: ["agent_systeme"]
        status: in_progress
        description: "Générer un lot d'images line art à partir de prompts. Pipeline jobs/worker/outputs en place ; placeholder Pillow ; Diffusers à intégrer."
        related_files:
          - "src/image_generation.py"
          - "scripts/run_image_worker.py"
          - "data/images_editor.html"
          - "src/api/routes/images.py" """
content = content.replace(old2, new2)

# MON_TRACK_JOBS
old3 = """      - id: MON_TRACK_JOBS
        title: "Suivre les jobs de génération et post-traitement"
        phase: 4
        actors: ["admin_plateforme"]
        status: in_progress
        description: "Suivre l'état des jobs (en cours, réussi, en erreur) via les tables SQLite."
        related_files:
          - "architecture.md"
          - "data/schema.sql"
          - "data/images_editor.html"
          - "src/api/routes/images.py"
          - "scripts/run_migration_v3.py" """
new3 = """      - id: MON_TRACK_JOBS
        title: "Suivre les jobs de génération et post-traitement"
        phase: 4
        actors: ["admin_plateforme"]
        status: done
        description: "Suivre l'état des jobs (en cours, réussi, en erreur) via les tables DuckDB."
        related_files:
          - "data/schema.sql"
          - "data/images_editor.html"
          - "src/api/routes/images.py"
          - "scripts/run_image_worker.py" """
content = content.replace(old3, new3)

with open(path, "w", encoding="utf-8") as f:
    f.write(content)
print("use_cases.yaml mis à jour")
