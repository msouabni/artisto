"""Modèles SQLAlchemy du cockpit git-autoritaire (Phase 1 — incrément 1).

Cap non négociable (cf. ``alwanbooks-docs/DIRECTION-PHASE-2026-06-22.md`` +
ADR ``2026-06-22_DOSSIER-cockpit-plan-controle-git-verite.md``) :

    git = vérité du contenu. Le cockpit ne stocke JAMAIS le contenu de façon
    autoritaire. Les tables ci-dessous portent :
      - l'**orchestration** (``work_item``) ;
      - un **cache lecture** de git + un **content_hash** (``git_index``).
    Aucune page n'est servie depuis la base. Tout écart cache↔git = drift =
    alarme, jamais une seconde vérité tolérée.

Ces modèles réutilisent la même ``Base`` déclarative que le reste de l'app
(``api.models.Base``) afin d'être créés par le même ``create_all`` / ``init_db``.

PostgreSQL unique. SQLite est interdit, y compris pour les tests (le dialecte
diverge → faux verts). Les tests tournent sur une Postgres éphémère
(cf. ``tests/cockpit/conftest.py``). On utilise donc librement ``JSONB``.

TODO (tâches suivantes du plan vivant, HORS de cet incrément) :
  - ``index_status`` : cache Search Console / Bing (couverture/indexation par
    URL) — alimente l'état dérivé ``indexe``.
  - ``perf_metric`` : cache GSC Search Analytics (impressions/clics/position),
    tendance par cluster.
  - ``schedule`` : miroir ``publishDate`` + ``last_build_at`` + ``rebuild_due``
    dérivé (alerte « rebuild dû »).
"""
from __future__ import annotations

from sqlalchemy import JSON, Boolean, Date, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from api.models import Base

# Type JSON portable : JSONB en Postgres (prod + tests cockpit), JSON ailleurs.
# Le runtime est PostgreSQL UNIQUE (le buffer staging est exploité en JSONB).
# Cette variante n'existe que pour ne PAS casser le ``create_all`` du conftest
# SQLite global existant (qui balaie toute Base.metadata) — les tables cockpit
# n'y sont jamais utilisées, mais doivent rester compilables. Les tests cockpit
# tournent, eux, sur Postgres éphémère (cf. tests/cockpit/conftest.py).
_JSONB = JSON().with_variant(JSONB(), "postgresql")

# États d'orchestration du work_item (machine à états du pilotage éditorial).
# DISTINCT des états dérivés de git (ecrit/programme/publie/indexe) qui ne sont
# JAMAIS stockés — voir api.services? non : src/services/git_states.py.
WORK_ITEM_STATES = ("candidat", "valide", "construction", "mesure", "verdict")

# État du buffer de staging (contenu transitoire, jamais autoritaire, jamais servi).
STAGING_STATES = ("none", "draft", "pending_commit")


class WorkItem(Base):
    """Référence une page git par ``(repo, locale, slug)`` + état d'orchestration.

    PAS de colonne contenu autoritaire. Les colonnes ``staging_*`` sont un
    **buffer transitoire** (pré-commit) purgé après commit ; elles ne sont
    jamais servies ni considérées comme vérité.
    """

    __tablename__ = "work_item"
    __table_args__ = (
        UniqueConstraint("repo", "locale", "slug", name="uq_work_item_repo_locale_slug"),
        Index("idx_work_item_state", "state"),
        Index("idx_work_item_repo_locale", "repo", "locale"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)

    # Référence à la page git (clé de jointure avec git_index).
    repo: Mapped[str] = mapped_column(String, nullable=False)
    locale: Mapped[str] = mapped_column(String, nullable=False)
    slug: Mapped[str] = mapped_column(String, nullable=False)

    # État d'orchestration (pilotage éditorial), distinct de l'état dérivé de git.
    state: Mapped[str] = mapped_column(String, nullable=False, default="candidat")

    # Liens score / opportunité (import alawseo — tâche ultérieure). FK nullable :
    # la table cible n'existe pas dans cet incrément, on garde une simple
    # référence souple (id texte) sans contrainte FK matérielle pour ne pas
    # coupler à un schéma absent. Documenté comme « lien score/opportunité ».
    opportunity_id: Mapped[str | None] = mapped_column(String, nullable=True)

    # Buffer de staging (TRANSITOIRE, jamais autoritaire, jamais servi).
    staging_frontmatter: Mapped[dict | None] = mapped_column(_JSONB, nullable=True)
    staging_body: Mapped[str | None] = mapped_column(Text, nullable=True)
    staging_state: Mapped[str] = mapped_column(String, nullable=False, default="none")

    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)


class GitIndex(Base):
    """Cache lecture de git (miroir du dépôt). Autorité = git, jamais cette table.

    Reconstruit par l'indexeur (``src/services/git_indexer.py``) à chaque scan.
    Tout écart ``content_hash`` cache↔git lève une alarme de drift (tâche
    ultérieure : détection drift) — cette table ne « gagne » jamais contre git.
    """

    __tablename__ = "git_index"
    __table_args__ = (
        UniqueConstraint("repo", "locale", "slug", name="uq_git_index_repo_locale_slug"),
        Index("idx_git_index_repo_locale", "repo", "locale"),
        Index("idx_git_index_publish_date", "publish_date"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)

    repo: Mapped[str] = mapped_column(String, nullable=False)
    locale: Mapped[str] = mapped_column(String, nullable=False)
    slug: Mapped[str] = mapped_column(String, nullable=False)

    # exists : la page est-elle présente dans git au dernier scan.
    exists: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # publish_date : la seule vérité de planification (frontmatter ``publishDate``).
    publish_date: Mapped[object | None] = mapped_column(Date, nullable=True)

    # frontmatter_digest : hash du frontmatter seul (détection d'édition méta).
    frontmatter_digest: Mapped[str | None] = mapped_column(String, nullable=True)

    # content_hash : hash (frontmatter + corps) — pierre angulaire de la
    # détection de drift et de l'idempotence de l'indexeur.
    content_hash: Mapped[str] = mapped_column(String, nullable=False)

    # Chemin relatif du fichier dans le repo (debug / traçabilité, non clé).
    rel_path: Mapped[str | None] = mapped_column(String, nullable=True)

    last_indexed_at: Mapped[str] = mapped_column(Text, nullable=False)
