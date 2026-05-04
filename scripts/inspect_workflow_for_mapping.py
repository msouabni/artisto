#!/usr/bin/env python3
"""Liste les nœuds d'un workflow API ComfyUI et rappelle les clés de mapping attendues.

Usage (depuis la racine du dépôt) ::
    python scripts/inspect_workflow_for_mapping.py ernie-image-turbo-q8-api
    python scripts/inspect_workflow_for_mapping.py --file data/workflows/mon_export.json
    python scripts/inspect_workflow_for_mapping.py ernie-image-turbo-q8-api --check

Aide à remplir ``data/workflows/<nom>.overrides.json`` après un nouvel export ComfyUI.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS_DIR = ROOT / "data" / "workflows"


def _ensure_src_path() -> None:
    src = ROOT / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))


def _load_workflow_graph(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    data.pop("__meta__", None)
    return data


def _print_nodes(wf: dict) -> None:
    rows: list[tuple[str, str, str]] = []
    for nid in sorted(wf.keys(), key=lambda x: (len(str(x)), str(x))):
        node = wf.get(nid)
        if not isinstance(node, dict) or "class_type" not in node:
            continue
        ct = str(node.get("class_type", ""))
        inputs = node.get("inputs", {})
        ins = inputs if isinstance(inputs, dict) else {}
        keys = ", ".join(sorted(ins.keys())[:12])
        if len(ins) > 12:
            keys += ", …"
        rows.append((str(nid), ct, keys))
    w = max(len(r[0]) for r in rows) if rows else 2
    print(f"{'id'.ljust(w)}  class_type{' ' * 18}  inputs (extraits)")
    print("-" * (w + 60))
    for nid, ct, keys in rows:
        print(f"{nid.ljust(w)}  {ct[:40].ljust(40)}  {keys}")


def _print_mapping_help(current: dict[str, list] | None) -> None:
    _ensure_src_path()
    from workers.comfy_client import WORKFLOW_OVERRIDE_KEYS  # noqa: PLC0415

    print("\nClés logiques injectées par le worker (fichier .overrides.json) :")
    for k in WORKFLOW_OVERRIDE_KEYS:
        if current is None:
            print(f"  - {k}")
        elif k in current:
            print(f"  - {k}  →  {current[k]!r}")
        else:
            print(f"  - {k}  (absente : valeur ignorée à l'exécution)")

    if current:
        extra = set(current) - set(WORKFLOW_OVERRIDE_KEYS)
        if extra:
            print("\nClés dans le mapping sans effet côté worker :")
            for k in sorted(extra):
                print(f"  - {k}")


def _stub_sidecar(name: str) -> str:
    return f"""{{
  "description": "Mapping pour {name} — remplir les [node_id, input] après inspection ci-dessus.",
  "overrides": {{
    "positive_prompt": ["NODE_ID_POSITIF", "text"],
    "negative_prompt": ["NODE_ID_NEGATIF", "text"],
    "seed": ["NODE_ID_SAMPLER", "seed"],
    "steps": ["NODE_ID_SAMPLER", "steps"],
    "cfg": ["NODE_ID_SAMPLER", "cfg"],
    "width": ["NODE_ID_LATENT_OU_EMPTY", "width"],
    "height": ["NODE_ID_LATENT_OU_EMPTY", "height"],
    "batch_size": ["NODE_ID_LATENT_OU_EMPTY", "batch_size"],
    "sampler_name": ["NODE_ID_SAMPLER", "sampler_name"],
    "scheduler": ["NODE_ID_SAMPLER", "scheduler"],
    "denoise": ["NODE_ID_SAMPLER", "denoise"],
    "shift": ["NODE_ID_AURA_SI_PRESENT", "shift"]
  }}
}}
"""


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspecter un workflow API pour construire .overrides.json")
    parser.add_argument(
        "template",
        nargs="?",
        help=f"Nom du template (fichier {{nom}}.json sous {WORKFLOWS_DIR})",
    )
    parser.add_argument("--file", type=Path, help="Chemin vers un JSON workflow API exporté depuis ComfyUI")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Avec un nom de template : comparer le sidecar .overrides.json aux clés du worker",
    )
    args = parser.parse_args()

    current_map: dict[str, list] | None = None
    template_name: str | None = None

    if args.file:
        path = args.file.resolve()
        if not path.is_file():
            print(f"Fichier introuvable : {path}", file=sys.stderr)
            return 1
        label = str(path)
        wf = _load_workflow_graph(path)
    elif args.template:
        template_name = args.template.strip()
        if not template_name:
            print("Nom de template vide.", file=sys.stderr)
            return 1
        path = WORKFLOWS_DIR / f"{template_name}.json"
        if not path.is_file():
            print(f"Template introuvable : {path}", file=sys.stderr)
            return 1
        label = template_name
        wf = _load_workflow_graph(path)
        sidecar = WORKFLOWS_DIR / f"{template_name}.overrides.json"
        if args.check:
            if sidecar.is_file():
                raw = json.loads(sidecar.read_text(encoding="utf-8"))
                cm = raw.get("overrides", raw)
                current_map = cm if isinstance(cm, dict) else None
            else:
                print(f"Aucun sidecar : {sidecar}\n", file=sys.stderr)
    else:
        parser.print_help()
        return 1

    print(f"Workflow : {label}\n")
    _print_nodes(wf)
    _print_mapping_help(current_map if args.check else None)

    if template_name and not args.file:
        sc = WORKFLOWS_DIR / f"{template_name}.overrides.json"
        print(f"\nFichier sidecar recommandé : {sc}")
        print("Squelette JSON (copier-coller puis ajuster les IDs) :\n")
        print(_stub_sidecar(template_name))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
