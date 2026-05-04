# Workflows ComfyUI

Ce dossier contient les templates de workflows ComfyUI pour la génération d’images (`job.config.workflow_template`).

## Fichiers par template

| Fichier | Rôle |
|--------|------|
| `{nom}.json` | Graphe exporté depuis ComfyUI (**Save API Format**). Tu peux le **remplacer entièrement** à chaque mise à jour du graphe. |
| `{nom}.overrides.json` | **Optionnel mais recommandé** : contrat public du workflow (version, points d’entrée publics, capacités). **Non écrasé** quand tu ré-exportes seulement le `.json`. |

Sans sidecar `.overrides.json`, le mapping legacy peut rester dans `__meta__.overrides` à l’intérieur du `{nom}.json` (comme pour `z_image_turbo_v1.json`). Ce mode reste supporté pour compatibilité, mais la cible est désormais le **contrat public**.

## Contrat canonique (`workflow contract v1`)

Le backend et le worker manipulent désormais un **contexte canonique**. Un workflow déclare ensuite quels champs il expose réellement comme `public_inputs`.

`positive_prompt`, `negative_prompt`, `seed`, `steps`, `cfg`, `width`, `height`, `batch_size`, `sampler_name`, `scheduler`, `denoise`, `shift`

La liste canonique est dans le code : `WORKFLOW_OVERRIDE_KEYS` dans [`src/workers/comfy_client.py`](../../src/workers/comfy_client.py).

Règles :

- `positive_prompt` est le champ principal et doit être exposé par tout workflow image.
- un workflow peut **ignorer** ou **ne pas supporter** un champ (`negative_prompt`, `shift`, etc.).
- un champ vide côté app est traité comme **absent** ; on n’invente plus de fallback implicite dans le backend.
- l’adaptation d’un champ au graphe interne se fait dans le workflow lui-même, pas dans le backend.

## Format du sidecar minimal

Fichier `data/workflows/mon_template.overrides.json` :

```json
{
  "description": "Contrat public du workflow.",
  "contract_version": "workflow_contract_v1",
  "public_inputs": {
    "positive_prompt": ["12", "text"],
    "seed": ["4", "seed"],
    "steps": ["4", "steps"]
  },
  "capabilities": {
    "positive_prompt": "required",
    "negative_prompt": "unsupported",
    "seed": "optional",
    "steps": "optional"
  }
}
```

Chaque entrée de `public_inputs` est `[ "id_nœud_string", "nom_du_input" ]` tel que dans le JSON API ComfyUI.

### `capabilities`

Valeurs reconnues :

- `required`
- `optional`
- `ignored`
- `unsupported`

Un champ `unsupported` ou `ignored` ne sera pas injecté par le backend, même s’il existe côté image ou côté job.

### Compatibilité legacy

Le loader accepte encore :

- `overrides` dans le sidecar,
- `__meta__.overrides` dans le workflow,
- et l’ancienne politique `negative_prompt_policy`.

Mais ces formats sont considérés comme des formats de transition. La cible à moyen terme est `contract_version + public_inputs + capabilities`.

Le template **`ernie-image-turbo-q8-api`** est la **variante opérationnelle par défaut** du contrat v1 côté backend (`DEFAULT_WORKFLOW_TEMPLATE`) : il n’expose pas `negative_prompt` publiquement et utilise `ConditioningZeroOut` pour éviter un second CLIP négatif ; il peut rester lourd selon la machine. Le template **`z_image_turbo_v1`** reste disponible en **opt-in** (même contrat public, `negative_prompt` en `unsupported`, `shift` optionnel).

## Structure recommandée d’un workflow

Pour chaque workflow, séparer visuellement trois zones :

1. `PUBLIC INPUTS`
2. `ADAPTATION`
3. `ENGINE`

Exemple :

- `PUBLIC INPUTS` : nœuds texte/nombres stables, adressés par le sidecar
- `ADAPTATION` : `ConditioningZeroOut`, choix de sous-branche, valeurs par défaut locales
- `ENGINE` : loaders, sampler, decode, save

Cette séparation évite que le backend dépende des nœuds profonds du graphe.

## Après un nouvel export ComfyUI

1. Remplace `mon_template.json` par le nouvel export (tu peux supprimer tout `__meta__` du fichier exporté si tu utilises un sidecar).
2. Lance depuis la racine du dépôt :
   ```bash
   python scripts/inspect_workflow_for_mapping.py mon_template
   ```
   Tu obtiens la table des nœuds (`id`, `class_type`, noms d’`inputs`).
3. Mets à jour `mon_template.overrides.json` avec les **nouveaux** IDs de nœuds publics dans `public_inputs`.
4. Optionnel : vérifier la couverture des clés worker :
   ```bash
   python scripts/inspect_workflow_for_mapping.py mon_template --check
   ```

Exemple avec un fichier exporté ailleurs :

```bash
python scripts/inspect_workflow_for_mapping.py --file chemin/vers/export_api.json
```

## Exemple `job.config`

```json
{
  "workflow_template": "ernie-image-turbo-q8-api",
  "prompt": "...",
  "positive_prompt": "...",
  "seed": 42,
  "width": 1024,
  "height": 1024
}
```

## Mise à jour d’un workflow existant

Quand tu modifies un workflow déjà branché :

1. Ne change pas le contrat public sans raison.
2. Si tu dois casser le contrat, crée une **nouvelle variante** plutôt que modifier silencieusement l’ancienne.
3. Vérifie que les `public_inputs` pointent toujours vers les bons nœuds.
4. Vérifie les `capabilities` :
   - un champ devenu dangereux ou inutile doit passer à `unsupported` ou `ignored`,
   - un champ nouvellement supporté doit être ajouté explicitement.
5. Relance les tests backend liés aux workflows avant de réactiver le workflow.

## Ajout d’un nouveau workflow

Checklist minimale :

1. Exporter le graphe en **Save API Format** dans `data/workflows/{nom}.json`.
2. Créer une zone `PUBLIC INPUTS` dans le graphe.
3. Ajouter `data/workflows/{nom}.overrides.json` avec :
   - `contract_version`
   - `public_inputs`
   - `capabilities`
4. Décider explicitement quels champs sont `unsupported` ou `ignored`.
5. Vérifier le préflight API et les tests de régression.
6. N’utiliser le workflow comme défaut qu’après validation locale du comportement VRAM / Comfy.
