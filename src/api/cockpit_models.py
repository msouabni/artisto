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

Incrément « rebuild » (Phase 1, prio 3 — décision 4 DIRECTION-2026-06-22) :
  - ``schedule`` : miroir ``publishDate`` (depuis git_index) + ``last_build_at``
    (dernier build déployé). ``rebuild_due`` est **dérivé** (jamais stocké) par
    ``src/services/rebuild.py`` : une page programmée arrivée à échéance mais
    pas encore rebuildée → due. Le câblage Cloudflare réel = track Hamma ; ici
    le déclencheur est mocké/configurable (hook URL ou commande locale).

Incrément « indexation » (Phase 1, prio 4 — DIRECTION-2026-06-22) :
  - ``index_status`` : **cache lecture** de la couverture moteur de recherche
    (Google Search Console URL Inspection + Bing Webmaster) par URL. Alimente
    l'état dérivé ``indexe`` (jamais stocké). Comme ``git_index``, c'est un
    miroir : la vérité reste l'API moteur ; le cache n'est qu'un instantané
    horodaté (``fetched_at``). Le provider réel est **gated sur creds** (env
    ``GSC_*`` / ``BING_WEBMASTER_API_KEY``) ; sans creds, un ``MockIndexProvider``
    déterministe alimente le cache (aucun appel réseau). Câblage des creds =
    track Hamma.

TODO (tâches suivantes du plan vivant, HORS de cet incrément) :
  - ``perf_metric`` : cache GSC Search Analytics (impressions/clics/position),
    tendance par cluster — Phase 2.
"""
from __future__ import annotations

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    Float,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)  # noqa: F401  (Date/Integer conservés pour cohérence du module)
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

# ── Machine d'états HITL (supervision humaine — Phase 2, incrément 1) ──────────
#
# Le buffer de staging d'un work_item (``staging_frontmatter`` / ``staging_body``
# + plaque mock) traverse une machine d'états de validation humaine PENDANT que
# le work_item est en orchestration ``state='construction'``. Cap inchangé : le
# staging n'est JAMAIS servi ni autoritaire ; sa seule issue est un commit git
# (seule porte d'entrée). Les états :
#
#   none  ──generate──►  generating ──(plaque+méta mock prêtes)──►  review_image
#   review_image ──approve──► review_text ──approve──► approved ──commit──► (none)
#   review_image ──reject──► generating  (re-générer)  | ou drop → none
#   review_text  ──reject──► review_image (revoir l'image) | ou generating
#   approved     ──commit──► none  (buffer purgé, work_item avance ; git autoritaire)
#
# ``committed`` n'est PAS un état stocké : après commit, ``staging_state`` repasse
# à ``none`` (buffer purgé) et le work_item avance côté orchestration. La preuve
# du commit vit dans git (``git_index`` réindexé, ``last_synced_hash`` posé).
HITL_STATES = (
    "none",          # pas de génération en cours / buffer vide
    "generating",    # job de génération (mock) enfilé / en cours
    "review_image",  # plaque générée — en attente de validation humaine IMAGE
    "review_text",   # image approuvée — en attente de validation humaine TEXTE
    "approved",      # image + texte approuvés — autorisé à committer (git)
    "rejected",      # rejeté en fin de chaîne (drop explicite) — buffer purgeable
)

# ``editing`` (Phase 2, incrément 2) : buffer chargé DEPUIS git pour une édition
# légère d'une page déjà publiée (UPDATE gardé par hash). Distinct des états HITL
# de création — l'édition repart toujours de git (jamais d'un état parallèle).
#
# Compat : les anciens états ``draft`` / ``pending_commit`` (Phase 1) restent
# acceptés (des work_items Phase 1 peuvent les porter). Les nouveaux flux HITL
# utilisent ``HITL_STATES``. L'union est la contrainte applicative (pas de CHECK
# SQL : on garde le schéma souple, cf. cap « schéma libre d'évoluer »).
STAGING_STATES = ("none", "draft", "pending_commit", "editing", *HITL_STATES[1:])

# États de la plaque (image bicouche). MOCK en Phase 2 incrément 1 : la vraie
# génération (ComfyUI + décoloriage) est derrière le mock (track Hamma).
PLATE_STATES = ("none", "pending", "ready", "failed")

# Moteurs de recherche dont on cache la couverture (index_status.engine).
INDEX_ENGINES = ("gsc", "bing")

# États de couverture normalisés (index_status.coverage_state). Le mapping des
# états bruts spécifiques à chaque API (GSC verdict / Bing) vers ce vocabulaire
# commun est fait côté provider (src/services/index_providers.py).
COVERAGE_STATES = (
    "indexed",                # la page est indexée (visible dans l'index)
    "discovered",             # connue mais pas encore crawlée
    "crawled_not_indexed",    # crawlée mais non indexée (exclue ou en attente)
    "excluded",               # explicitement exclue (noindex, dupliquée, etc.)
    "unknown",                # état indéterminé (non-200 API, quota, jamais inspectée)
)


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

    # Liens score / opportunité (import alawseo). Référence souple (id texte)
    # vers ``opportunity.id`` — pas de contrainte FK matérielle pour rester
    # tolérant aux imports partiels (un work_item peut exister sans opportunité,
    # une opportunité peut arriver après le work_item). Le lien est posé par
    # slug à l'import (cf. services/opportunity_import.py::link_work_items).
    opportunity_id: Mapped[str | None] = mapped_column(String, nullable=True)

    # last_synced_hash : ``content_hash`` git constaté la dernière fois que le
    # cockpit s'est synchronisé sur cette page (commit émis ou accusé de lecture).
    # Sert UNIQUEMENT à la détection de drift « édition hors cockpit » : si le
    # ``git_index.content_hash`` courant diffère de cette valeur, la page a été
    # éditée dans git hors du cockpit → on SIGNALE (jamais on ne corrige git).
    # NULL = pas encore synchronisé (un work_item neuf sur une page existante
    # n'est PAS en drift hash tant qu'on n'a pas posé de référence).
    last_synced_hash: Mapped[str | None] = mapped_column(String, nullable=True)

    # Buffer de staging (TRANSITOIRE, jamais autoritaire, jamais servi).
    staging_frontmatter: Mapped[dict | None] = mapped_column(_JSONB, nullable=True)
    staging_body: Mapped[str | None] = mapped_column(Text, nullable=True)
    staging_state: Mapped[str] = mapped_column(String, nullable=False, default="none")

    # variantes (V5) : galerie de variantes de style du MÊME sujet portée par le
    # staging du work_item — liste de ``{style, image, alt?}`` (style = id de
    # collection ``styles`` côté front ; image = chemin servi ``/img/<slug>/<style>.png``).
    # ``classique`` est OBLIGATOIRE + en PREMIER (cf. convention d'assets
    # verrouillée). Le bot SCANNE ``{slug}/`` → produit cette liste (pas de table
    # de mapping). Au commit, ``cockpit_git_publish`` SÉRIALISE ce bloc dans le
    # frontmatter du ``.md`` (format lisible par le schéma front : ref→styles,
    # image, alt?) + place/copie les images à la convention. TRANSITOIRE comme le
    # reste du staging : la vérité passe à git au commit (jamais servi d'ici).
    # Absent/vide ⇒ la galerie front retombe sur l'image unique (back-compat).
    staging_variantes: Mapped[list | None] = mapped_column(_JSONB, nullable=True)

    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)


class PlateImage(Base):
    """Plaque (image bicouche) générée pour un ``work_item`` — MOCK en P2 inc.1.

    Cap : ce n'est PAS du contenu autoritaire. La plaque réelle (PNG/SVG
    décoloriage) vit sur R2 ; son URL part dans git au commit (frontmatter
    ``imageSource``/``imageSvg``…). Cette table porte l'**état de génération**
    (orchestration) + les références mock le temps de la revue. Purgée logiquement
    au commit (la vérité passe à git).

    En Phase 2 incrément 1, la génération est **mockée** : aucun appel ComfyUI /
    LLM. ``image_state`` passe ``pending → ready`` quand le générateur mock a
    produit une plaque factice (data-URI / chemin local mock). La vraie
    génération (ComfyUI + décoloriage + LLM métadonnées) est **derrière ce mock**
    (worker dédié = track Hamma) ; l'interface (``generate_plate``) est documentée
    dans ``src/services/generation_mock.py``.
    """

    __tablename__ = "plate_image"
    __table_args__ = (
        UniqueConstraint("work_item_id", name="uq_plate_image_work_item"),
        Index("idx_plate_image_state", "image_state"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)

    # Référence souple vers work_item.id (pas de FK matérielle — cf. opportunity).
    work_item_id: Mapped[str] = mapped_column(String, nullable=False)

    # image_state ∈ PLATE_STATES.
    image_state: Mapped[str] = mapped_column(String, nullable=False, default="none")

    # style_source : origine du style de génération (ex. 'decoloriage', 'mock').
    # Détermine quel générateur (réel/mock) produit la plaque. Mock par défaut.
    style_source: Mapped[str | None] = mapped_column(String, nullable=True)

    # Références mock (le temps de la revue). En réel : URLs R2 (frontmatter git).
    # preview : data-URI/URL d'aperçu de la plaque (affichée en zone Validation).
    preview_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    # mock_meta : métadonnées de génération mock (seed, prompt, dérivé opp…) JSONB.
    mock_meta: Mapped[dict | None] = mapped_column(_JSONB, nullable=True)

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


class Opportunity(Base):
    """Score de demande importé (mock ``alawseo`` — CSV cluster scoré).

    Lecture seule côté cockpit : reflète l'analyse de demande SEO (volume, KD,
    score) par mot-clé / sujet. Reliée aux ``work_item`` par ``slug`` à l'import
    (cf. services/opportunity_import.py). Pas la vérité du contenu (qui reste
    git) — juste le signal de priorisation éditoriale affiché sur les cartes.

    Le CSV source (``data/clusters/cluster-marin-sujets.csv``) ne porte PAS de
    colonne ``score`` brute : on dérive un **proxy** ``score`` depuis ``volume``
    (normalisé 0-100 sur le max du cluster). Documenté dans l'importeur.
    """

    __tablename__ = "opportunity"
    __table_args__ = (
        UniqueConstraint("source", "keyword", name="uq_opportunity_source_keyword"),
        Index("idx_opportunity_slug", "slug"),
        Index("idx_opportunity_cluster", "cluster"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)

    # keyword : requête SEO source (ex. "coloriage baleine").
    keyword: Mapped[str] = mapped_column(String, nullable=False)
    # sujet : libellé sujet normalisé (ex. "baleine").
    sujet: Mapped[str | None] = mapped_column(String, nullable=True)
    # slug : clé de jointure vers work_item.slug (ex. "baleine").
    slug: Mapped[str] = mapped_column(String, nullable=False)

    # volume : volume de recherche mensuel (signal brut).
    volume: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # kd : keyword difficulty (0-100) si fournie ; NULL sinon.
    kd: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # score : score de demande 0-100 (proxy dérivé du volume si pas de colonne
    # score dans la source — voir opportunity_import).
    score: Mapped[float | None] = mapped_column(Float, nullable=True)

    # cluster : regroupement thématique (ex. "animaux marins").
    cluster: Mapped[str | None] = mapped_column(String, nullable=True)
    # source : provenance de l'import (ex. "cluster-marin-sujets.csv").
    source: Mapped[str] = mapped_column(String, nullable=False)

    imported_at: Mapped[str] = mapped_column(Text, nullable=False)


class Schedule(Base):
    """Calendrier de publication d'une page + dernier build déployé.

    Cap : ``schedule`` ne porte AUCUNE vérité de contenu. ``publish_date`` est
    un **miroir** de ``git_index.publish_date`` (frontmatter ``publishDate``,
    seule vérité de planification). ``last_build_at`` est le **fait
    opérationnel** « un build a été déployé à cet instant » — la seule donnée
    propre à cette table (git ne sait rien des builds déployés).

    ``rebuild_due`` n'est JAMAIS stocké : il est dérivé à la lecture par
    ``src/services/rebuild.py::compute_rebuild_due`` :

        rebuild_due = (publish_date <= now)
                      ET (last_build_at IS NULL OU last_build_at < publish_date)

    c.-à-d. une page **programmée arrivée à échéance mais pas encore rebuildée**
    (site statique Astro→Cloudflare : une page à ``publishDate`` future ne
    devient live qu'après un build postérieur à la date).

    Reliée à ``work_item`` par ``work_item_id`` (référence souple, pas de FK
    matérielle — cohérent avec le reste du cockpit). ``last_build_at`` est posé
    par ``trigger_rebuild`` au succès d'un build (mocké tant que ni
    ``REBUILD_HOOK_URL`` ni ``REBUILD_CMD`` ne sont configurés).
    """

    __tablename__ = "schedule"
    __table_args__ = (
        UniqueConstraint("work_item_id", name="uq_schedule_work_item"),
        Index("idx_schedule_publish_date", "publish_date"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)

    # Référence souple vers work_item.id (pas de FK matérielle, cf. opportunity).
    work_item_id: Mapped[str] = mapped_column(String, nullable=False)

    # Miroir de git_index.publish_date (frontmatter publishDate). NULL = page
    # sans publishDate → publiée à la date de commit (jamais « due » au rebuild).
    publish_date: Mapped[object | None] = mapped_column(Date, nullable=True)

    # last_build_at : timestamp ISO (UTC) du dernier build *déployé* couvrant
    # cette page. NULL = jamais buildée depuis l'enregistrement → due dès que
    # publish_date est échue. Posé par trigger_rebuild au succès.
    last_build_at: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)


class IndexStatus(Base):
    """Cache lecture de la couverture moteur de recherche (GSC + Bing) par URL.

    Cap : c'est un **cache** (lecture), JAMAIS une vérité de contenu. La vérité
    de l'indexation appartient à l'API moteur (Google Search Console URL
    Inspection / Bing Webmaster) ; cette table n'est qu'un **instantané
    horodaté** (``fetched_at``). On l'interroge pour dériver l'état ``indexe``
    d'un work_item (jamais persisté côté git_states), sans rappeler l'API à
    chaque affichage (quota GSC ~2000 inspections/jour).

    Clé fonctionnelle : ``(engine, url)`` — une même URL a une couverture par
    moteur (``gsc`` et ``bing`` peuvent diverger). L'``url`` est dérivée du
    work_item (``{base}/{locale}/colorier/{slug}/``) par
    ``src/services/index_providers.py::work_item_url`` — pas de FK matérielle
    (cohérent avec le reste du cockpit : référence souple par URL).

    Alimentée par ``POST /api/cockpit/index-status/sync`` → provider
    (mock par défaut ; réel gated sur creds) → upsert. Aucune écriture moteur :
    on ne fait que **lire** la couverture (URL Inspection est en lecture seule
    ici ; on n'utilise pas l'API d'indexation/submit).
    """

    __tablename__ = "index_status"
    __table_args__ = (
        UniqueConstraint("engine", "url", name="uq_index_status_engine_url"),
        Index("idx_index_status_url", "url"),
        Index("idx_index_status_coverage", "coverage_state"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)

    # url : URL publique inspectée (clé de jointure souple avec le work_item via
    # work_item_url). Stockée canonique (avec slash final, cf. work_item_url).
    url: Mapped[str] = mapped_column(String, nullable=False)

    # engine : 'gsc' | 'bing' (cf. INDEX_ENGINES). Une URL = une ligne par moteur.
    engine: Mapped[str] = mapped_column(String, nullable=False)

    # coverage_state : état de couverture normalisé (cf. COVERAGE_STATES). Le
    # mapping API brute → ce vocabulaire est fait côté provider.
    coverage_state: Mapped[str] = mapped_column(String, nullable=False, default="unknown")

    # last_crawl : dernière date de crawl rapportée par le moteur (nullable :
    # une page 'discovered'/'unknown' n'a pas de dernier crawl). ISO str.
    last_crawl: Mapped[str | None] = mapped_column(Text, nullable=True)

    # fetched_at : instant où le cache a été rafraîchi depuis le moteur (ISO
    # UTC). Sert à juger la fraîcheur du cache (re-sync si trop ancien).
    fetched_at: Mapped[str] = mapped_column(Text, nullable=False)
