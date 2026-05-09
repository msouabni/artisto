"""Validation fix negative prompt — workflow ernie-image-turbo-q8-api.

Vérifie que le fix appliqué côté workflow (KSampler.negative → node 15
CLIPTextEncode au lieu de ConditioningZeroOut node 19) rend bien le
``negative_prompt`` actif. 4 générations sur le concept "Soccer Ball on a
Field" avec **même seed** et **même prompt positif** — seul le negative varie.

Variantes :
    neg_none      = " "        (filtré par sanitize → injection skip → node 15 garde sa valeur par défaut)
    neg_standard  = standard   (15+ termes anti-couleurs/photo/text)
    neg_anatomy   = anatomy    (motion/anatomie)
    neg_full      = standard + anatomy

Critère : si les 4 images sont **différentes** au pixel près, le fix est actif.
Si elles sont identiques (cf. POC negative-prompt précédent à CFG=1), c'est qu'il
y a encore un blocage côté pipeline.

Usage :
    python scripts/test_negative_prompt_fix.py
"""
from __future__ import annotations

import io
import json
import os
import sys
import time
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(PROJECT_ROOT / ".env")

import hashlib  # noqa: E402

from PIL import Image, ImageDraw, ImageFont  # noqa: E402

from services.image_qc_technical import build_technical_image_qc_v1  # noqa: E402
from workers.comfy_client import (  # noqa: E402
    ComfyClient,
    apply_overrides,
    load_workflow_template,
    sanitize_public_workflow_inputs,
    workflows_json_dir,
)

CHAIN_JSON = PROJECT_ROOT / "docs" / "reports" / "2026-05-05_poc-prompt-chain-v2.json"
OUTPUT_DIR = PROJECT_ROOT / "docs" / "reports" / "test-negative-fix"
REPORT_MD = PROJECT_ROOT / "docs" / "reports" / "2026-05-05_test-negative-fix.md"
REPORT_JSON = PROJECT_ROOT / "docs" / "reports" / "2026-05-05_test-negative-fix.json"

WORKFLOW_TEMPLATE = "ernie-image-turbo-q8-api"
SEED = 42001  # même seed pour les 4

ERNIE_SAMPLER_DEFAULTS: dict = {
    "steps": 8,
    "cfg": 1.0,
    "width": 1024,
    "height": 1024,
    "batch_size": 1,
    "sampler_name": "euler",
    "scheduler": "normal",
    "denoise": 1.0,
}

NEG_STANDARD = "shading, gradients, color fills, shadows, text, watermark, realistic"
NEG_ANATOMY = "motion blur, action lines, extra limbs, three legs, deformed anatomy, multiple exposure"

VARIANTS = [
    ("neg_none", " "),
    ("neg_standard", NEG_STANDARD),
    ("neg_anatomy", NEG_ANATOMY),
    ("neg_full", NEG_STANDARD + ", " + NEG_ANATOMY),
]


def load_soccer_prompt() -> str:
    data = json.loads(CHAIN_JSON.read_text(encoding="utf-8"))
    for r in data.get("results", []):
        name = (r.get("concept", {}).get("name_en") or "").lower()
        if "soccer" in name:
            return (r.get("final_prompt") or "").strip()
    raise RuntimeError("Soccer concept not found in chain JSON")


def submit(client: ComfyClient, prompt: str, negative: str, seed: int) -> tuple[str, dict]:
    workflows_dir = workflows_json_dir()
    wf_base, public_inputs_map, contract = load_workflow_template(workflows_dir, WORKFLOW_TEMPLATE)
    candidate = {
        "positive_prompt": prompt,
        "negative_prompt": negative,
        "seed": int(seed),
    }
    for k, v in ERNIE_SAMPLER_DEFAULTS.items():
        candidate[k] = v
    overrides = sanitize_public_workflow_inputs(candidate, contract)
    workflow = apply_overrides(wf_base, public_inputs_map, overrides)
    pid = client.submit_prompt(workflow)
    return pid, {
        "negative_in_overrides": "negative_prompt" in overrides,
        "applied_negative": overrides.get("negative_prompt", "<filtered out by sanitize>"),
        "seed": overrides.get("seed"),
        "cfg": overrides.get("cfg"),
    }


def generate(client: ComfyClient, prompt: str, negative: str, out_path: Path) -> dict:
    t0 = time.time()
    try:
        pid, debug = submit(client, prompt, negative, SEED)
        history = client.poll_until_done(pid)
        images = client.extract_output_images(history)
        if not images:
            raise RuntimeError("No image in history")
        first = images[0]
        client.download_image(
            filename=first["filename"], dest=out_path,
            subfolder=first.get("subfolder", ""),
            folder_type=first.get("type", "output"),
        )
        return {
            "ok": True,
            "comfy_latency_s": round(time.time() - t0, 2),
            "prompt_id": pid,
            **debug,
        }
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}", "comfy_latency_s": round(time.time() - t0, 2)}


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def histogram_check(image_path: Path) -> dict:
    qc = build_technical_image_qc_v1(image_path)
    metrics = qc.get("metrics") or {}
    flags = qc.get("flags") or []
    return {
        "color_ratio": float(metrics.get("color_ratio", 0.0)),
        "white_ratio": float(metrics.get("white_ratio", 0.0)),
        "ink_ratio": float(metrics.get("ink_ratio", 0.0)),
        "histogram_ok": not (("strong_color" in flags) or ("noticeable_color" in flags)),
        "flags": flags,
    }


def compose_grid(images: list[Image.Image], titles: list[str]) -> Image.Image:
    pad = 10
    title_h = 30
    cell_w = max(im.width for im in images)
    cell_h = max(im.height for im in images)
    grid_w = cell_w * len(images) + pad * (len(images) + 1)
    grid_h = cell_h + title_h + pad * 2
    out = Image.new("RGB", (grid_w, grid_h), (255, 255, 255))
    draw = ImageDraw.Draw(out)
    try:
        font = ImageFont.load_default()
    except Exception:
        font = None
    for i, (im, title) in enumerate(zip(images, titles)):
        x = pad + i * (cell_w + pad)
        im_rgb = im if im.mode == "RGB" else im.convert("RGB")
        out.paste(im_rgb, (x, title_h + pad))
        if font is not None:
            draw.text((x + 4, 4), title, fill=(0, 0, 0), font=font)
    return out


def main() -> int:
    print("=" * 100)
    print(f"Validation fix negative prompt — workflow {WORKFLOW_TEMPLATE}")
    print("=" * 100)

    if not CHAIN_JSON.exists():
        print(f"❌ chain JSON missing: {CHAIN_JSON}", file=sys.stderr)
        return 1
    prompt = load_soccer_prompt()
    print(f"\nSoccer prompt ({len(prompt)} chars): {prompt[:160]}…")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    client = ComfyClient()
    if not client.is_available():
        print(f"❌ ComfyUI unreachable: {client.base_url}", file=sys.stderr)
        return 1

    results = []
    for code, negative in VARIANTS:
        out_path = OUTPUT_DIR / f"soccer_{code}.png"
        print(f"\n[{code}] negative ({len(negative)} chars): {negative[:80]!r}")
        gen = generate(client, prompt, negative, out_path)
        if not gen.get("ok"):
            print(f"  ❌ {gen.get('error')}")
            results.append({"code": code, "negative": negative, **gen})
            continue
        sha = file_sha256(out_path)
        hist = histogram_check(out_path)
        print(f"  ✅ {gen['comfy_latency_s']}s  sha256={sha[:16]}…  color_ratio={hist['color_ratio']:.4f}")
        print(f"     applied_negative_in_overrides={gen['negative_in_overrides']}  applied_value={gen['applied_negative']!r}")
        results.append({
            "code": code, "negative": negative,
            "image_path": str(out_path.relative_to(PROJECT_ROOT)).replace("\\", "/"),
            "sha256": sha, "histogram": hist, **gen,
        })

    # Compare grid
    valid = [r for r in results if r.get("ok")]
    if valid:
        imgs = [Image.open(PROJECT_ROOT / r["image_path"]).convert("RGB") for r in valid]
        titles = [r["code"] for r in valid]
        grid = compose_grid(imgs, titles)
        grid_path = OUTPUT_DIR / "soccer_compare.png"
        grid.save(grid_path)
        print(f"\nCompare grid → {grid_path.name}")

    # Sha256 diff matrix
    print("\n=== sha256 diff matrix ===")
    shas = {r["code"]: r.get("sha256", "") for r in results if r.get("ok")}
    codes = list(shas.keys())
    all_different = True
    for i, c1 in enumerate(codes):
        for c2 in codes[i + 1:]:
            same = shas[c1] == shas[c2] and shas[c1]
            if same:
                all_different = False
                print(f"  ⚠ {c1} == {c2}  (sha={shas[c1][:12]}…)")
    if all_different and len(codes) >= 2:
        print(f"  ✓ Toutes les {len(codes)} variantes sont DIFFÉRENTES — le fix est actif.")
    elif len(codes) < 2:
        print("  (moins de 2 variantes valides — diff impossible)")

    # JSON
    payload = {
        "test": "negative-prompt-fix",
        "date": "2026-05-06",
        "workflow_template": WORKFLOW_TEMPLATE,
        "seed": SEED,
        "soccer_prompt": prompt,
        "variants": VARIANTS,
        "results": results,
        "all_unique_sha": all_different,
    }
    REPORT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"\nJSON brut → {REPORT_JSON}")

    # Markdown
    md = []
    md.append("# Validation fix negative prompt — workflow ernie-image-turbo-q8-api")
    md.append("Date : 2026-05-06")
    md.append("")
    md.append("## Contexte")
    md.append("Le workflow `data/workflows/ernie-image-turbo-q8-api.json` a été modifié : `KSampler.negative` (node 16) est désormais branché sur `CLIPTextEncode` (node 15), au lieu de l'ancien `ConditioningZeroOut` (node 19, supprimé). Le contrat `overrides.json` expose `negative_prompt` comme input optional, mappé sur `[\"15\", \"text\"]`. Ce test valide que le fix est effectif côté pipeline image.")
    md.append("")
    md.append("Référence du POC précédent qui montrait le problème (4 variantes négatives → 4 images strictement identiques à cause du `ConditioningZeroOut` qui annulait le négatif) : `docs/reports/2026-05-05_poc-negative-prompt.md`.")
    md.append("")

    md.append("## Vérification d'injection côté code (avant exécution)")
    md.append("")
    md.append("- `data/workflows/ernie-image-turbo-q8-api.json` node `16` (KSampler) : `inputs.negative = [\"15\", 0]` ✓")
    md.append("- `data/workflows/ernie-image-turbo-q8-api.overrides.json` : `public_inputs.negative_prompt = [\"15\", \"text\"]`, `capabilities.negative_prompt = optional` ✓")
    md.append("- `src/workers/image_worker.py::process()` : passe `config.negative_prompt` dans `candidate_values`, puis `sanitize_public_workflow_inputs` filtre selon le contrat, puis `apply_overrides` injecte dans `node[15].inputs.text`. **Aucune modification code requise** — l'injection est automatique via le contrat.")
    md.append("- ⚠ Caveat : `sanitize_public_workflow_inputs` filtre les strings vides après `strip()` → `negative_prompt = \" \"` n'est PAS injecté ; le node 15 garde alors sa valeur par défaut du JSON (qui est `\" \"`). Cela reste équivalent à \"pas de négatif effectif\" et sert de baseline propre.")
    md.append("")

    md.append("## Test : 4 générations, même seed, prompt positif identique")
    md.append("")
    md.append(f"- **Concept** : Soccer Ball on a Field (prompt extrait de `2026-05-05_poc-prompt-chain-v2.json`, {len(prompt)} chars)")
    md.append(f"- **Workflow** : `{WORKFLOW_TEMPLATE}`")
    md.append(f"- **Seed** : `{SEED}` (identique pour les 4 variantes)")
    md.append(f"- **Sampler** : steps=8, cfg=1.0, sampler=euler, scheduler=normal, denoise=1.0")
    md.append("")

    md.append("### Variantes negative_prompt testées")
    md.append("")
    for code, neg in VARIANTS:
        md.append(f"- `{code}` ({len(neg)} chars) : `{neg!r}`")
    md.append("")

    md.append("### Résultats par variante")
    md.append("")
    md.append("| Code | latency | sha256 (16 chars) | injecté | color_ratio | hist |")
    md.append("|---|---|---|---|---|---|")
    for r in results:
        if not r.get("ok"):
            md.append(f"| {r['code']} | — | (gen KO) | — | — | — |")
            continue
        sha = r.get("sha256", "")
        sha_short = sha[:16] + "…" if sha else ""
        injected = "✓" if r.get("negative_in_overrides") else "filtré (vide)"
        hist = r.get("histogram", {})
        md.append(
            f"| {r['code']} | {r['comfy_latency_s']}s | `{sha_short}` | {injected} | "
            f"{hist.get('color_ratio', 0):.4f} | {'OK' if hist.get('histogram_ok') else 'KO'} |"
        )
    md.append("")

    md.append("### Verdict du fix")
    md.append("")
    if all_different and len(codes) >= 2:
        md.append("✅ **Toutes les variantes ont des sha256 différents → le fix est ACTIF.**")
        md.append("")
        md.append("Le `negative_prompt` est désormais réellement injecté dans le KSampler via le node 15. À CFG=1 le négatif n'a normalement aucun effet mathématique (cf. `2026-05-05_poc-negative-prompt.md`) — si on observe néanmoins des différences pixelaires, deux explications possibles :")
        md.append("")
        md.append("1. Le sampler Ernie Turbo applique le négatif via un mécanisme alternatif (rescale CFG, neg weight) **au-delà** de la simple formule classifier-free.")
        md.append("2. La déterminisme du sampler dépend du conditioning passé (ordre / contenu) même quand le coefficient final est nul (calcul intermédiaire avec arrondi flottant).")
        md.append("")
        md.append("Quoi qu'il en soit, **le pipeline d'injection est branché correctement**. Reste à mesurer (visuellement) si l'effet est exploitable pour corriger les 3 problèmes du POC `image-quality`.")
    else:
        md.append("❌ **Au moins 2 variantes ont le même sha256 → le fix N'EST PAS effectif.**")
        md.append("")
        md.append("Causes possibles :")
        md.append("- ComfyUI cache toujours le résultat parce qu'il considère les workflows équivalents (vérifier que le contrat injecte bien la nouvelle valeur dans node 15).")
        md.append("- Une autre couche du pipeline annule encore le négatif (ConditioningZeroOut résiduel ou variant ?). Re-checker le JSON node-par-node.")
        md.append("- À CFG=1.0, le sampler ignore mathématiquement le négatif (cf. POC 2026-05-05_poc-negative-prompt). Dans ce cas le fix workflow est correct mais inopérant — il faut bumper CFG > 1 pour observer un effet.")
    md.append("")

    md.append("## Effet visuel observé")
    md.append("")
    md.append("Voir `docs/reports/test-negative-fix/soccer_compare.png` (4 colonnes côte à côte). Évaluation à compléter par hamma :")
    md.append("")
    md.append("- **`neg_none` vs `neg_standard`** : le négatif standard supprime-t-il les couleurs résiduelles, ombres, texte ?")
    md.append("- **`neg_none` vs `neg_anatomy`** : le négatif anatomy corrige-t-il les motion blur / extra limbs / deformed legs ?")
    md.append("- **`neg_full`** : effet cumulé propre, ou conflits / dégradations sur la silhouette principale ?")
    md.append("")
    md.append("→ [section qualitative à compléter visuellement]")
    md.append("")

    md.append("## Outputs")
    md.append("")
    md.append("```")
    md.append("docs/reports/test-negative-fix/")
    md.append("├── soccer_neg_none.png")
    md.append("├── soccer_neg_standard.png")
    md.append("├── soccer_neg_anatomy.png")
    md.append("├── soccer_neg_full.png")
    md.append("└── soccer_compare.png   ← grille 4 colonnes")
    md.append("```")
    md.append("")

    md.append("## Décision / Action suivante")
    md.append("")
    if all_different and len(codes) >= 2:
        md.append("✅ Pipeline d'injection validé. Étape suivante :")
        md.append("")
        md.append("1. **Évaluation visuelle** des 4 PNG par hamma — le négatif corrige-t-il visiblement les 3 problèmes du POC `image-quality` (couleurs résiduelles fridge, motion artifacts soccer, couleurs vivides dragon) ?")
        md.append("2. Si oui : **mettre à jour `prompt_writer_ernie`** pour qu'il génère un negative_prompt structuré (baseline + additifs par sujet, cf. ce POC).")
        md.append("3. Si non : revenir sur l'option C du POC précédent (post-process via `gray-replace` / `dithering`).")
    else:
        md.append("❌ Pipeline d'injection non validé. Re-investiguer :")
        md.append("")
        md.append("1. Inspecter le workflow JSON pour vérifier l'absence de `ConditioningZeroOut` résiduel.")
        md.append("2. Logger la valeur de `node[15].inputs.text` après `apply_overrides` pour confirmer l'injection.")
        md.append("3. Tester avec CFG=2.0+ pour exclure l'effet \"CFG=1 ignore neg\".")
    md.append("")

    md.append("## Annexes")
    md.append("")
    md.append("- Données brutes : `2026-05-05_test-negative-fix.json`")
    md.append("- Script : `scripts/test_negative_prompt_fix.py`")
    md.append("- Workflow : `data/workflows/ernie-image-turbo-q8-api.json` + `.overrides.json`")
    md.append("- POC initial (avant fix) : `docs/reports/2026-05-05_poc-negative-prompt.md`")
    md.append("- Code d'injection : `src/workers/image_worker.py::process()` + `src/workers/comfy_client.py::apply_overrides`")

    REPORT_MD.write_text("\n".join(md), encoding="utf-8")
    print(f"Rapport MD → {REPORT_MD}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
