# Modèle `subject` — Alembic + SQLAlchemy + endpoints CRUD minimaux

## Contexte

Vision MEP v0 (cf. `docs/architect/2026-05-10_spec-mep-v0.md`) introduit une nouvelle entité **`subject`** comme enfant d'un `term` de taxonomie. Un term peut avoir N subjects. Chaque subject porte tags + note + status + enrichment + prompt. Le flow pipeline (annotation → enrichissement → prompt → image → QC → validation → publication) tourne autour de cette entité.

État actuel : aucune table `subject` ni `concept` n'existe en BD (vérifié `src/api/models.py`).

## Objectif

Créer la table `subject` + modèle SQLAlchemy + endpoints CRUD minimaux. Préparer la fondation data pour les briefs V1.3 (import skill v0), V1.4 (QC auto), Vague 2 (annotateur + jobs orchestration).

## Périmètre

### Migration Alembic

`alembic/versions/0007_subject_table.py` :

```python
CREATE TABLE subject (
    id TEXT PRIMARY KEY,
    term_id TEXT NOT NULL REFERENCES term(id),
    name TEXT NOT NULL,
    source TEXT NOT NULL,                  -- 'skill_v0' | 'manual' | 'llm_brainstorm' (futur)
    tags JSONB NOT NULL DEFAULT '[]',      -- list[str] : ambigu, simpliste, incomprehensible, creatif, parfait, complique, bug, blacklist
    note INTEGER NULL CHECK (note IS NULL OR (note >= 0 AND note <= 6)),
    status TEXT NOT NULL DEFAULT 'draft',  -- draft | annotated | validated | enriched | prompted | generated | qc_done | published | rejected
    enrichment JSONB NULL,                 -- {title_en, title_fr, title_ar, description_en/fr/ar, meta_seo, ...}
    prompt_positive TEXT NULL,             -- positive (negative figé côté workflow)
    metadata JSONB NULL,                   -- divers : source pointers, audit, override
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT subject_term_name_unique UNIQUE (term_id, name)
);

CREATE INDEX idx_subject_status ON subject(status);
CREATE INDEX idx_subject_term_id ON subject(term_id);
CREATE INDEX idx_subject_source ON subject(source);
```

**Postgres** uniquement (cf. CLAUDE.md — runtime Postgres). Tests SQLite via `conftest.py` doivent passer : utiliser `JSON` au lieu de `JSONB` dans le modèle SQLAlchemy (portable), Postgres traitera comme JSONB en runtime.

### Modèle SQLAlchemy

Dans `src/api/models.py`, ajouter classe `Subject(Base)` après `Term` :

```python
class Subject(Base):
    __tablename__ = "subject"
    id = Column(String, primary_key=True)
    term_id = Column(String, ForeignKey("term.id"), nullable=False)
    name = Column(String, nullable=False)
    source = Column(String, nullable=False)
    tags = Column(JSON, nullable=False, default=list)
    note = Column(Integer, nullable=True)
    status = Column(String, nullable=False, default="draft")
    enrichment = Column(JSON, nullable=True)
    prompt_positive = Column(Text, nullable=True)
    metadata_ = Column("metadata", JSON, nullable=True)  # 'metadata' réservé SQLAlchemy
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    term = relationship("Term", back_populates="subjects")
    __table_args__ = (UniqueConstraint("term_id", "name", name="subject_term_name_unique"),)
```

Ajouter sur `Term` :

```python
subjects = relationship("Subject", back_populates="term", cascade="all, delete-orphan")
```

### Endpoints CRUD minimaux

`src/api/routes/subjects.py` (nouveau router monté sur `/api/subjects` dans `src/api/main.py`) :

| Méthode | Path | Effet |
|---|---|---|
| `GET /api/subjects` | Liste paginée + filtres (`term_id`, `status`, `tags`, `source`) | Réutilise `get_db_read` |
| `GET /api/subjects/{id}` | Détail | — |
| `POST /api/subjects` | Création (utile pour `subject_import` et `manual`) | `get_db_write` |
| `PATCH /api/subjects/{id}` | Update partiel : tags, note, status, enrichment, prompt_positive | `get_db_write` |
| `DELETE /api/subjects/{id}` | Soft delete (mettre `status='rejected'` plutôt que DELETE physique) — au choix : voir critère acceptation | — |

**Validation Pydantic** : `SubjectCreate`, `SubjectUpdate`, `SubjectResponse` avec :
- `tags`: `list[Literal["ambigu", "simpliste", "incomprehensible", "creatif", "parfait", "complique", "bug", "blacklist"]]` — whitelist stricte
- `note`: `Optional[int]` avec `ge=0, le=6`
- `status`: `Literal["draft", "annotated", "validated", "enriched", "prompted", "generated", "qc_done", "published", "rejected"]`

### Tests

`tests/test_subjects_api.py` (nouveau) :

- CRUD heureux : create → get → patch → list filtrés → delete.
- Validation : tags hors whitelist rejetés (HTTP 422).
- Validation : note > 6 ou < 0 rejetés (HTTP 422).
- Validation : status hors enum rejeté.
- FK : create avec `term_id` inexistant → HTTP 404 ou 400.
- Unicité : create deux subjects avec même `(term_id, name)` → erreur conflit.
- Filtres : list par `term_id`, `status`, `tags` (contient au moins un tag listé), `source`.
- NULL-safe : `note IS NULL` géré (cf. CLAUDE.md NULL-safe convention).
- SQLite-portable : les tests passent en mémoire (vérifié via `conftest.py`).

## Critères d'acceptation

- Migration `0007_subject_table.py` applique en Postgres OK + downgrade OK.
- Modèle SQLAlchemy + relation bi-directionnelle `Term.subjects` ⇄ `Subject.term`.
- 5 endpoints CRUD fonctionnels.
- Validation Pydantic stricte sur tags / note / status.
- Tests pytest verts (≥ 15 nouveaux tests).
- Suite globale toujours verte hors dette legacy.
- Pas de breaking change sur la table `image` ou `image_output`.

## Hors scope

- Migration de données (aucune donnée à migrer — table neuve).
- Endpoint batch create (sera utile pour V1.3 import skill, mais peut passer par appels POST en boucle ou directement via `Session` dans le script).
- UI annotateur pour subjects (V2.1 dans la spec MEP v0).
- Workflow de transition de status automatique (gestion via jobs Vague 2).
- Audit log dédié (à voir post-MEP v0).

## Plan d'exécution suggéré (sous-agent unique)

```
Phase 1 — Migration Alembic (~30 min)
Phase 2 — Modèle SQLAlchemy + relation Term (~20 min)
Phase 3 — Endpoints CRUD + Pydantic (~45 min)
Phase 4 — Tests (~30 min)
Phase 5 — Vérification suite globale + applicabilité Postgres (~15 min)
```

## Reporting

`docs/reports/2026-05-10_modele-subject.md` — Contexte / Migration / Modèle / Endpoints / Tests / Décision (Go pour V1.3 import skill).

## Estimation

~1h30-2h dev + tests + rapport.
