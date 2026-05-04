"""Client HTTP pour l'API ComfyUI.

URL configurable via COMFY_URL (défaut http://127.0.0.1:8188).
Pattern 3-phases : ne garde pas de connexion persistante, compatible worker DuckDB.
"""
from __future__ import annotations

import copy
import json
import logging
import os
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)

COMFY_URL = os.environ.get("COMFY_URL", "http://127.0.0.1:8188")
COMFY_POLL_INTERVAL = float(os.environ.get("COMFY_POLL_INTERVAL", "2.0"))
COMFY_TIMEOUT = int(os.environ.get("COMFY_TIMEOUT", "300"))
WORKFLOW_CONTRACT_VERSION = "workflow_contract_v1"
WORKFLOW_CAPABILITY_VALUES = ("required", "optional", "ignored", "unsupported")

# Template ComfyUI par défaut si `job.config` ne contient pas `workflow_template`
# (fichier : data/workflows/{DEFAULT_WORKFLOW_TEMPLATE}.json).
DEFAULT_WORKFLOW_TEMPLATE = "ernie-image-turbo-q8-api"

# Clés logiques injectées par `ImageWorker` → `apply_overrides` (les clés absentes du mapping sont ignorées).
WORKFLOW_OVERRIDE_KEYS: tuple[str, ...] = (
    "positive_prompt",
    "negative_prompt",
    "seed",
    "steps",
    "cfg",
    "width",
    "height",
    "batch_size",
    "sampler_name",
    "scheduler",
    "denoise",
    "shift",
)


def _as_mapping_dict(value: Any, *, label: str) -> dict[str, list[Any]]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"{label} invalide : attendu un objet JSON.")
    out: dict[str, list[Any]] = {}
    for key, item in value.items():
        if not isinstance(item, list) or len(item) != 2:
            raise ValueError(
                f"{label} invalide : la clé {key!r} doit être une liste [node_id, input_name]."
            )
        out[str(key)] = list(item)
    return out


def _default_capabilities_from_inputs(
    input_map: dict[str, list[Any]],
    negative_prompt_policy: dict[str, Any] | None = None,
) -> dict[str, str]:
    neg_mode = str((negative_prompt_policy or {}).get("mode") or "").strip()
    out: dict[str, str] = {}
    for key in WORKFLOW_OVERRIDE_KEYS:
        if key == "positive_prompt":
            out[key] = "required" if key in input_map else "unsupported"
        elif key == "negative_prompt":
            if key not in input_map or neg_mode == "ignore":
                out[key] = "unsupported"
            else:
                out[key] = "optional"
        else:
            out[key] = "optional" if key in input_map else "unsupported"
    return out


def _merge_capabilities(
    derived: dict[str, str],
    explicit: dict[str, Any] | None,
) -> dict[str, str]:
    merged = dict(derived)
    if not isinstance(explicit, dict):
        return merged
    for key, raw in explicit.items():
        val = str(raw or "").strip()
        if val in WORKFLOW_CAPABILITY_VALUES:
            merged[str(key)] = val
    return merged


def project_root_dir() -> Path:
    """Racine du dépôt (parent de `src/`)."""
    return Path(__file__).resolve().parents[2]


def workflows_json_dir() -> Path:
    """Dossier des templates API ComfyUI (`data/workflows/`)."""
    return project_root_dir() / "data" / "workflows"


def list_workflow_template_names(workflows_dir: Path) -> list[str]:
    """Noms de templates (fichiers `*.json` sans extension), triés.

    Exclut les sidecars `*.overrides.json` (même racine de nom que le template).
    """
    if not workflows_dir.is_dir():
        return []
    names: list[str] = []
    for p in workflows_dir.glob("*.json"):
        if p.name.endswith(".overrides.json"):
            continue
        names.append(p.stem)
    return sorted(names)


def workflow_template_json_path(workflows_dir: Path, name: str) -> Path:
    return workflows_dir / f"{name}.json"


def workflow_template_exists(workflows_dir: Path, name: str) -> bool:
    return workflow_template_json_path(workflows_dir, name).is_file()


class ComfyError(RuntimeError):
    """Erreur générique ComfyUI."""


class ComfyTimeoutError(ComfyError):
    """Polling dépassé le timeout."""


class ComfyClient:
    """Client HTTP léger pour ComfyUI (pas de WebSocket, pas de dépendances tierces)."""

    def __init__(self, base_url: str | None = None) -> None:
        self.base_url = (base_url or COMFY_URL).rstrip("/")

    def _get(self, path: str) -> Any:
        url = f"{self.base_url}{path}"
        try:
            with urllib.request.urlopen(url, timeout=10) as r:
                return json.loads(r.read())
        except Exception as e:
            raise ComfyError(f"GET {url} : {e}") from e

    def _post_json(self, path: str, data: dict) -> Any:
        url = f"{self.base_url}{path}"
        body = json.dumps(data).encode("utf-8")
        req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            try:
                err_body = e.read().decode("utf-8", errors="replace")
                err_json = json.loads(err_body) if err_body.strip().startswith("{") else {}
                msg = err_json.get("error", {}).get("message", err_json.get("message", err_body[:500]))
            except Exception:
                msg = str(e)
            raise ComfyError(f"POST {url} HTTP {e.code}: {msg}") from e
        except Exception as e:
            raise ComfyError(f"POST {url} : {e}") from e

    def is_available(self) -> bool:
        """Vérifie si ComfyUI est disponible."""
        try:
            self._get("/system_stats")
            return True
        except Exception:
            return False

    def submit_prompt(self, workflow: dict, prompt_id: str | None = None) -> str:
        """Soumet un workflow à ComfyUI.

        Retourne le prompt_id utilisé (utile pour stocker dans job.external_ref_id).
        Le workflow ne doit pas contenir __meta__.
        """
        if prompt_id is None:
            prompt_id = str(uuid.uuid4())
        payload = {"prompt": workflow, "client_id": str(uuid.uuid4()), "prompt_id": prompt_id}
        result = self._post_json("/prompt", payload)
        if "error" in result:
            raise ComfyError(f"ComfyUI a rejeté le workflow : {result['error']}")
        returned_id = result.get("prompt_id", prompt_id)
        logger.info("Workflow soumis à ComfyUI : prompt_id=%s", returned_id)
        return returned_id

    def get_history(self, prompt_id: str) -> dict | None:
        """Retourne l'entrée d'historique pour prompt_id, ou None si pas encore terminé."""
        try:
            history = self._get(f"/history/{urllib.parse.quote(prompt_id)}")
        except ComfyError:
            return None
        return history.get(prompt_id)

    def poll_until_done(
        self,
        prompt_id: str,
        timeout: int = COMFY_TIMEOUT,
        interval: float = COMFY_POLL_INTERVAL,
        progress_callback: Callable[[int, str], None] | None = None,
    ) -> dict:
        """Attend la fin de l'exécution en pollinisant /history/{prompt_id}.

        Lève ComfyTimeoutError si timeout dépassé.
        progress_callback(percent: int, message: str) est appelé périodiquement (fire-and-forget).
        """
        deadline = time.monotonic() + timeout
        iteration = 0
        while time.monotonic() < deadline:
            entry = self.get_history(prompt_id)
            if entry is not None:
                outputs = entry.get("outputs", {})
                if outputs:
                    logger.info("ComfyUI terminé : prompt_id=%s, %d nœuds outputs", prompt_id, len(outputs))
                    return entry
                status = entry.get("status", {})
                if status.get("status_str") in ("error", "cancelled"):
                    messages = status.get("messages", [])
                    raise ComfyError(f"ComfyUI erreur : {messages}")
            if progress_callback and iteration % 5 == 0:
                elapsed = int((time.monotonic() - (deadline - timeout)) / timeout * 80)
                try:
                    progress_callback(min(elapsed, 80), "Génération en cours…")
                except Exception:
                    pass
            iteration += 1
            time.sleep(interval)
        raise ComfyTimeoutError(f"ComfyUI timeout après {timeout}s pour prompt_id={prompt_id}")

    def download_image(self, filename: str, dest: Path, subfolder: str = "", folder_type: str = "output") -> Path:
        """Télécharge une image depuis ComfyUI /view et la sauvegarde dans dest."""
        params = urllib.parse.urlencode({
            "filename": filename,
            "subfolder": subfolder,
            "type": folder_type,
        })
        url = f"{self.base_url}/view?{params}"
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                dest.write_bytes(r.read())
        except Exception as e:
            raise ComfyError(f"Téléchargement image {filename} : {e}") from e
        logger.info("Image téléchargée : %s → %s", filename, dest)
        return dest

    def extract_output_images(self, history_entry: dict) -> list[dict]:
        """Extrait les images générées depuis une entrée d'historique.

        Retourne une liste de dicts {filename, subfolder, type}.
        """
        images = []
        for node_id, node_output in history_entry.get("outputs", {}).items():
            for img in node_output.get("images", []):
                images.append({
                    "filename": img.get("filename", ""),
                    "subfolder": img.get("subfolder", ""),
                    "type": img.get("type", "output"),
                    "node_id": node_id,
                })
        return images


def apply_overrides(workflow: dict, overrides_map: dict, values: dict) -> dict:
    """Applique les overrides de job.config sur le workflow API.

    overrides_map : {clé_logique: [node_id, input_key]}
    values : {clé_logique: valeur} (ex. {"positive_prompt": "...", "seed": 42})
    Retourne une copie du workflow avec les valeurs injectées.
    """
    wf = copy.deepcopy(workflow)
    for key, value in values.items():
        if key not in overrides_map:
            continue
        node_id, input_key = overrides_map[key]
        node = wf.get(str(node_id))
        if node is None:
            logger.warning("Override '%s' : nœud '%s' introuvable dans le workflow", key, node_id)
            continue
        node.setdefault("inputs", {})[input_key] = value
        logger.debug("Override appliqué : [%s][%s] = %r", node_id, input_key, value)
    return wf


def resolve_negative_prompt_for_workflow(
    raw_from_job: str,
    overrides_map: dict[str, Any],
    policy: dict[str, Any] | None = None,
) -> tuple[str, bool]:
    """Résout le texte négatif et indique s'il doit être injecté dans Comfy via ``overrides``.

    ``raw_from_job`` : valeur canonique issue de ``job.config`` / image (déjà strip côté appelant si besoin).

    Politique (``negative_prompt_policy`` dans ``__meta__`` ou sidecar) :
    - ``mode`` : ``use_if_present`` | ``always_fallback`` | ``ignore``
    - ``default_text`` : repli métier si le job est vide (souvent Ernie / anatomie).

    Si ``mode`` est absent : ``ignore`` lorsqu'aucun mapping ``negative_prompt`` n'existe dans le graphe,
    sinon ``use_if_present`` (repli métier uniquement via ``default_text`` si renseigné).

    Retourne ``(texte_pour_métadonnées, injecter_dans_apply_overrides)``.
    L'injection n'a lieu que si le mapping technique ``negative_prompt`` existe **et** que le texte résolu est non vide.
    """
    policy = dict(policy or {})
    stripped_job = (raw_from_job or "").strip()
    mode_raw = policy.get("mode")
    mode = str(mode_raw).strip() if mode_raw is not None else ""
    has_neg_mapping = "negative_prompt" in overrides_map
    default_text = str(policy.get("default_text", "") or "").strip()

    if not mode:
        mode = "ignore" if not has_neg_mapping else "use_if_present"
    if mode not in ("use_if_present", "always_fallback", "ignore"):
        mode = "ignore" if not has_neg_mapping else "use_if_present"

    if mode == "ignore":
        return stripped_job, False

    if mode == "always_fallback":
        resolved = default_text
    else:
        resolved = stripped_job or default_text

    inject = has_neg_mapping and bool(resolved)
    return resolved, inject


def sanitize_public_workflow_inputs(
    values: dict[str, Any],
    contract: dict[str, Any],
) -> dict[str, Any]:
    """Filtre les valeurs candidates selon les `public_inputs` et `capabilities` du workflow."""
    public_inputs = contract.get("public_inputs") or {}
    capabilities = contract.get("capabilities") or {}
    out: dict[str, Any] = {}
    for key, value in values.items():
        if key not in public_inputs:
            continue
        capability = str(capabilities.get(key) or "unsupported")
        if capability in ("ignored", "unsupported"):
            continue
        if value is None:
            continue
        if isinstance(value, str):
            value = value.strip()
            if not value:
                continue
        out[key] = value
    return out


def load_workflow_template(workflows_dir: Path, name: str) -> tuple[dict, dict, dict[str, Any]]:
    """Charge un template de workflow depuis workflows_dir/{name}.json.

    Retourne ``(workflow_api, public_inputs_map, contract)`` où ``workflow_api`` est le dict sans ``__meta__``.

    **Contrat v1** : un sidecar peut exposer ``contract_version``, ``public_inputs`` et ``capabilities``.
    Le backend ne connaît alors que les points d'entrée publics du workflow.

    **Rétrocompatibilité** : si le sidecar reste au format legacy ``overrides``, ce mapping est encore
    accepté et utilisé comme ``public_inputs``. La politique négative legacy continue d'être chargée
    dans ``contract['negative_prompt_policy']``.
    """
    path = workflows_dir / f"{name}.json"
    if not path.exists():
        raise FileNotFoundError(f"Template workflow introuvable : {path}")
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    meta = data.pop("__meta__", {})
    embedded_overrides = _as_mapping_dict(meta.get("overrides"), label=f"__meta__.overrides ({path.name})")
    embedded_public_inputs = _as_mapping_dict(
        meta.get("public_inputs"),
        label=f"__meta__.public_inputs ({path.name})",
    )
    embedded_capabilities = meta.get("capabilities") if isinstance(meta.get("capabilities"), dict) else {}
    contract_version = str(meta.get("contract_version") or "").strip()

    neg_policy: dict[str, Any] = {}
    meta_pol = meta.get("negative_prompt_policy")
    if isinstance(meta_pol, dict):
        neg_policy.update(meta_pol)

    selected_inputs: dict[str, list[Any]] = dict(embedded_public_inputs or embedded_overrides)

    sidecar = workflows_dir / f"{name}.overrides.json"
    if sidecar.is_file():
        raw = json.loads(sidecar.read_text(encoding="utf-8-sig"))
        if not isinstance(raw, dict):
            raise ValueError(f"Sidecar invalide ({sidecar}) : attendu un objet JSON à la racine.")

        side_contract_version = str(raw.get("contract_version") or "").strip()
        if side_contract_version:
            contract_version = side_contract_version

        side_pol = raw.get("negative_prompt_policy")
        if isinstance(side_pol, dict):
            neg_policy.update(side_pol)

        if "public_inputs" in raw:
            selected_inputs = _as_mapping_dict(raw.get("public_inputs"), label=f"public_inputs ({sidecar.name})")
        elif "overrides" in raw:
            selected_inputs = _as_mapping_dict(raw.get("overrides"), label=f"overrides ({sidecar.name})")
        else:
            # Rétrocompat : ancien sidecar sans clé « overrides » = racine = mapping (hors champs métadonnées).
            meta_keys = {
                "description",
                "notes",
                "negative_prompt_policy",
                "contract_version",
                "public_inputs",
                "capabilities",
            }
            legacy = {k: v for k, v in raw.items() if k not in meta_keys}
            if legacy:
                selected_inputs = _as_mapping_dict(legacy, label=f"legacy overrides ({sidecar.name})")

        explicit_capabilities = raw.get("capabilities")
        if isinstance(explicit_capabilities, dict):
            embedded_capabilities = _merge_capabilities(embedded_capabilities, explicit_capabilities)

    if not contract_version:
        contract_version = (
            WORKFLOW_CONTRACT_VERSION
            if embedded_public_inputs or "public_inputs" in (raw if sidecar.is_file() else {})
            else "legacy_overrides"
        )

    derived_capabilities = _default_capabilities_from_inputs(selected_inputs, neg_policy)
    capabilities = _merge_capabilities(derived_capabilities, embedded_capabilities)
    contract = {
        "contract_version": contract_version,
        "public_inputs": dict(selected_inputs),
        "capabilities": capabilities,
        "negative_prompt_policy": dict(neg_policy),
    }
    return data, selected_inputs, contract
