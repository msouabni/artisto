"""Conventions de storage pour les variantes de coloriage (C2.1).

Centralise la construction des chemins fichier pour les variantes generees.

Convention : ``data/generated/{leaf_id}__{variant_name}.{ext}``
  - ``.png``           : raw ComfyUI output
  - ``.svg``           : vectorisation print
  - ``_coloriage.svg`` : SVG coloriage interactif (extract_palette)

Foundation pour C2.2 (job post-traitement) et C2.3 (pipeline publish).
Decisions actees 2026-06-01 (ADR multi-variantes).

API publique :
    >>> from services.coloring_storage import get_storage_paths
    >>> paths = get_storage_paths("lion_in_savanna", "pastel_chromakey")
    >>> paths.raw_png
    PosixPath('data/generated/lion_in_savanna__pastel_chromakey.png')
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from services.pipeline_variants import get_variant

# Chemin par defaut du dossier des variantes generees (relatif au CWD).
# En tests : utiliser ``base_dir=tmp_path``. En prod : passer un base_dir
# absolu si le CWD n'est pas la racine du projet.
DEFAULT_GENERATED_DIR = Path("data/generated")

# Whitelist leaf_id : lettres minuscules + chiffres + underscores. Verifie
# contre la taxonomie reelle (1376 feuilles dans
# ``data/prompt_generator/coloring_taxonomy_full.json``, 100% match).
_VALID_LEAF_ID_RE = re.compile(r"^[a-z][a-z0-9_]*$")

# Suffix special qui distingue le SVG coloriage interactif du SVG print.
_COLORING_SVG_SUFFIX = "_coloriage.svg"

# Types d'artefact (utilises par ``StoragePaths.kind_path``).
KIND_RAW_PNG = "raw_png"
KIND_VECTOR_SVG = "vector_svg"
KIND_COLORING_SVG = "coloring_svg"
_VALID_KINDS = frozenset({KIND_RAW_PNG, KIND_VECTOR_SVG, KIND_COLORING_SVG})


@dataclass(frozen=True)
class StoragePaths:
    """Chemins des 3 artefacts pour une variante d'un ``leaf_id``."""

    raw_png: Path
    vector_svg: Path
    coloring_svg: Path

    def kind_path(self, kind: str) -> Path:
        """Retourne le chemin associe au ``kind`` demande.

        Raises:
            ValueError: si ``kind`` n'est pas dans ``_VALID_KINDS``.
        """
        if kind == KIND_RAW_PNG:
            return self.raw_png
        if kind == KIND_VECTOR_SVG:
            return self.vector_svg
        if kind == KIND_COLORING_SVG:
            return self.coloring_svg
        raise ValueError(
            f"Unknown kind: {kind!r}. Valid kinds: {sorted(_VALID_KINDS)}"
        )


def validate_leaf_id(leaf_id: str) -> None:
    """Verifie qu'un ``leaf_id`` est syntaxiquement valide et sans traversal.

    Raises:
        ValueError: si invalide.
    """
    if not isinstance(leaf_id, str) or not leaf_id:
        raise ValueError(
            f"leaf_id must be non-empty string, got {leaf_id!r}"
        )
    if not _VALID_LEAF_ID_RE.match(leaf_id):
        raise ValueError(
            f"leaf_id {leaf_id!r} invalid "
            f"(must match {_VALID_LEAF_ID_RE.pattern})"
        )
    # Anti-traversal explicite (redondant avec le regex mais defensif).
    if ".." in leaf_id or "/" in leaf_id or "\\" in leaf_id:
        raise ValueError(
            f"leaf_id {leaf_id!r} contains path traversal characters"
        )


def validate_variant_name(variant_name: str) -> None:
    """Verifie qu'une ``variant_name`` est definie dans le registre.

    Raises:
        ValueError: si vide, non-string, ou inconnue du registre.
    """
    if not isinstance(variant_name, str) or not variant_name:
        raise ValueError(
            f"variant_name must be non-empty string, got {variant_name!r}"
        )
    if get_variant(variant_name) is None:
        raise ValueError(f"Variante inconnue : {variant_name!r}")


def get_storage_paths(
    leaf_id: str,
    variant_name: str,
    base_dir: Path | None = None,
) -> StoragePaths:
    """Construit les chemins de stockage pour une variante d'un ``leaf_id``.

    Convention : ``{base_dir}/{leaf_id}__{variant_name}.{ext}``.

    Args:
        leaf_id: identifiant feuille de la taxonomie (ex. ``lion_in_savanna``).
        variant_name: nom de variante connue du registre.
        base_dir: dossier racine (defaut ``DEFAULT_GENERATED_DIR``).

    Raises:
        ValueError: si ``leaf_id`` ou ``variant_name`` invalide.
    """
    validate_leaf_id(leaf_id)
    validate_variant_name(variant_name)
    base = base_dir if base_dir is not None else DEFAULT_GENERATED_DIR
    stem = f"{leaf_id}__{variant_name}"
    return StoragePaths(
        raw_png=base / f"{stem}.png",
        vector_svg=base / f"{stem}.svg",
        coloring_svg=base / f"{stem}{_COLORING_SVG_SUFFIX}",
    )


def has_variant(
    leaf_id: str,
    variant_name: str,
    kind: str = KIND_RAW_PNG,
    base_dir: Path | None = None,
) -> bool:
    """Test d'existence d'un fichier pour une variante.

    Par defaut, teste le ``raw_png`` (artefact pivot).
    """
    paths = get_storage_paths(leaf_id, variant_name, base_dir=base_dir)
    return paths.kind_path(kind).is_file()


def list_existing_variants(
    leaf_id: str,
    base_dir: Path | None = None,
) -> list[str]:
    """Liste les ``variant_name`` pour lesquels le ``raw_png`` existe.

    Scan le dossier pour les fichiers matchant ``{leaf_id}__*.png`` (en
    excluant le suffix special ``_coloriage.svg`` — qui ne devrait pas
    matcher ``.png`` de toute facon, mais defensif).

    Args:
        leaf_id: identifiant feuille (valide via ``validate_leaf_id``).
        base_dir: dossier racine (defaut ``DEFAULT_GENERATED_DIR``).

    Returns:
        Liste triee des variant_name existants. ``[]`` si dossier absent.
    """
    validate_leaf_id(leaf_id)
    base = base_dir if base_dir is not None else DEFAULT_GENERATED_DIR
    if not base.is_dir():
        return []
    prefix = f"{leaf_id}__"
    variants: list[str] = []
    for f in base.glob(f"{prefix}*.png"):
        stem = f.stem  # sans extension
        # On extrait juste la partie apres {leaf_id}__
        if not stem.startswith(prefix):
            continue
        name = stem[len(prefix):]
        # Filet de securite : un variant_name ne doit pas se terminer par
        # ``_coloriage`` (convention reservee au SVG coloriage interactif).
        if not name or name.endswith("_coloriage"):
            continue
        variants.append(name)
    return sorted(set(variants))
