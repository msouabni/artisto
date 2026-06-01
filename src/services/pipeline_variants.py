"""Registre des variantes de coloriage + service de chargement (C1.1).

Foundation pour la generation multi-variantes par leaf_id (decision
architecturale 2026-06-01). Ce module n'integre PAS encore le pipeline
(creation de jobs, worker) : il fournit uniquement la lecture du
registre JSON et sa validation.

Le registre prod vit dans ``data/pipeline_variants.json``. Voir
``alwanbooks-docs/adr/2026-06-01_multi-variantes-coloriage.md`` pour
l'ADR et ``alwanbooks-docs/architecture/workflow-generation-pipeline.md``
pour le workflow revise.

API publique :
    >>> from services.pipeline_variants import get_active_variants, get_variant
    >>> variants = get_active_variants()
    >>> v = get_variant("pastel_chromakey")
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_REGISTRY_PATH: Path = PROJECT_ROOT / "data" / "pipeline_variants.json"

# Whitelist hardcodee pour eviter un import circulaire avec prompt_generator.
# Reflet de ``STYLE_CONFIGS`` dans ``src/services/prompt_generator.py``.
# Si un nouveau style est ajoute la-bas, l'ajouter ici aussi.
_VALID_PROMPT_STYLES: frozenset[str] = frozenset(
    {"pastel", "flat_cartoon", "lineart", "watercolor", "crayon", "kawaii"}
)

_VALID_OUTPUT_KINDS: frozenset[str] = frozenset({"online_coloring", "print"})

_REQUIRED_VARIANT_FIELDS: tuple[str, ...] = (
    "prompt_style",
    "force_chromakey",
    "chromakey_rgb",
    "extract_preset",
    "output_kind",
    "label",
)


@dataclass(frozen=True)
class Variant:
    name: str
    prompt_style: str
    force_chromakey: bool
    chromakey_rgb: tuple[int, int, int] | None
    extract_preset: str | None
    output_kind: str
    label: str


def _resolve_path(path: Path | None) -> Path:
    return path if path is not None else DEFAULT_REGISTRY_PATH


def _load_raw(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        raise ValueError(f"Registry {path} must be a JSON object at top level")
    return data


def _to_variant(name: str, raw: dict[str, Any]) -> Variant:
    rgb_raw = raw.get("chromakey_rgb")
    rgb: tuple[int, int, int] | None
    if rgb_raw is None:
        rgb = None
    else:
        rgb = (int(rgb_raw[0]), int(rgb_raw[1]), int(rgb_raw[2]))
    return Variant(
        name=name,
        prompt_style=raw["prompt_style"],
        force_chromakey=bool(raw["force_chromakey"]),
        chromakey_rgb=rgb,
        extract_preset=raw["extract_preset"],
        output_kind=raw["output_kind"],
        label=raw["label"],
    )


@lru_cache(maxsize=8)
def _load_cached(path_str: str) -> tuple[dict[str, Variant], dict[str, Any]]:
    path = Path(path_str)
    data = _load_raw(path)
    errors = validate_registry(data)
    if errors:
        raise ValueError(
            f"Invalid pipeline variants registry {path}:\n  - "
            + "\n  - ".join(errors)
        )
    variants_raw = data["variants"]
    variants = {
        name: _to_variant(name, raw)
        for name, raw in variants_raw.items()
    }
    return variants, data


def load_variants(path: Path | None = None) -> dict[str, Variant]:
    resolved = _resolve_path(path).resolve()
    variants, _ = _load_cached(str(resolved))
    return dict(variants)


def get_active_variants(
    category_id: str | None = None,
    path: Path | None = None,
) -> list[Variant]:
    resolved = _resolve_path(path).resolve()
    variants, data = _load_cached(str(resolved))
    overrides = data.get("per_category_override") or {}
    active_names: list[str]
    if category_id is not None and category_id in overrides:
        active_names = list(overrides[category_id])
    else:
        active_names = list(data.get("default_active") or [])
    return [variants[name] for name in active_names if name in variants]


def get_variant(name: str, path: Path | None = None) -> Variant | None:
    resolved = _resolve_path(path).resolve()
    variants, _ = _load_cached(str(resolved))
    return variants.get(name)


def _validate_rgb(value: Any) -> str | None:
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        return "chromakey_rgb must be a list/tuple of 3 integers"
    for component in value:
        if not isinstance(component, int) or isinstance(component, bool):
            return "chromakey_rgb components must be integers"
        if component < 0 or component > 255:
            return "chromakey_rgb components must be in [0, 255]"
    return None


def validate_registry(data: dict) -> list[str]:
    errors: list[str] = []

    if not isinstance(data, dict):
        return ["registry must be a JSON object"]

    if data.get("version") != 1:
        errors.append("version must equal 1")

    variants = data.get("variants")
    if not isinstance(variants, dict) or not variants:
        errors.append("variants must be a non-empty object")
        # On ne peut pas continuer sans variants valides.
        return errors

    # Lazy import pour eviter le cout d'import de cv2/numpy/etc si on ne
    # valide pas reellement, et la circularite eventuelle.
    try:
        from services.extract_palette import PRESETS as _EXTRACT_PRESETS
    except Exception:  # pragma: no cover - defensive
        _EXTRACT_PRESETS = {}

    for name, variant in variants.items():
        if not isinstance(variant, dict):
            errors.append(f"variants['{name}'] must be an object")
            continue
        missing = [f for f in _REQUIRED_VARIANT_FIELDS if f not in variant]
        if missing:
            errors.append(
                f"variants['{name}'] missing fields: {', '.join(missing)}"
            )
            continue

        prompt_style = variant["prompt_style"]
        if prompt_style not in _VALID_PROMPT_STYLES:
            errors.append(
                f"variants['{name}'].prompt_style='{prompt_style}' not in "
                f"{sorted(_VALID_PROMPT_STYLES)}"
            )

        output_kind = variant["output_kind"]
        if output_kind not in _VALID_OUTPUT_KINDS:
            errors.append(
                f"variants['{name}'].output_kind='{output_kind}' not in "
                f"{sorted(_VALID_OUTPUT_KINDS)}"
            )

        force_ck = variant["force_chromakey"]
        if not isinstance(force_ck, bool):
            errors.append(
                f"variants['{name}'].force_chromakey must be a boolean"
            )
        rgb_value = variant["chromakey_rgb"]
        if force_ck:
            if rgb_value is None:
                errors.append(
                    f"variants['{name}'] has force_chromakey=true but "
                    "chromakey_rgb is null"
                )
            else:
                rgb_err = _validate_rgb(rgb_value)
                if rgb_err:
                    errors.append(f"variants['{name}']: {rgb_err}")
        else:
            if rgb_value is not None:
                rgb_err = _validate_rgb(rgb_value)
                if rgb_err:
                    errors.append(f"variants['{name}']: {rgb_err}")

        extract_preset = variant["extract_preset"]
        if extract_preset is not None:
            if not isinstance(extract_preset, str):
                errors.append(
                    f"variants['{name}'].extract_preset must be a string or null"
                )
            elif extract_preset not in _EXTRACT_PRESETS:
                errors.append(
                    f"variants['{name}'].extract_preset='{extract_preset}' "
                    f"not in extract_palette.PRESETS"
                )

        label = variant["label"]
        if not isinstance(label, str) or not label.strip():
            errors.append(f"variants['{name}'].label must be a non-empty string")

    default_active = data.get("default_active")
    if not isinstance(default_active, list):
        errors.append("default_active must be a list")
    else:
        for entry in default_active:
            if not isinstance(entry, str):
                errors.append("default_active entries must be strings")
            elif entry not in variants:
                errors.append(
                    f"default_active references unknown variant '{entry}'"
                )

    per_category = data.get("per_category_override", {})
    if not isinstance(per_category, dict):
        errors.append("per_category_override must be an object")
    else:
        for cat_id, names in per_category.items():
            if not isinstance(cat_id, str):
                errors.append("per_category_override keys must be strings")
                continue
            if not isinstance(names, list):
                errors.append(
                    f"per_category_override['{cat_id}'] must be a list"
                )
                continue
            for n in names:
                if not isinstance(n, str):
                    errors.append(
                        f"per_category_override['{cat_id}'] entries must be strings"
                    )
                elif n not in variants:
                    errors.append(
                        f"per_category_override['{cat_id}'] references unknown "
                        f"variant '{n}'"
                    )

    return errors


def _clear_cache() -> None:
    """Vide le cache module-level (utile pour les tests)."""
    _load_cached.cache_clear()


# Expose le cache_clear pour API publique des tests.
load_variants.cache_clear = _clear_cache  # type: ignore[attr-defined]
get_active_variants.cache_clear = _clear_cache  # type: ignore[attr-defined]
get_variant.cache_clear = _clear_cache  # type: ignore[attr-defined]
