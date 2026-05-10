"""Smoke test pivot T25 — 3+3 prompts pour template_frieze_1xN et template_grid_3x3_imagier.

Usage : depuis la racine, `python scripts/smoke_pivot_t25.py` (ce script ajoute src/ au path).
Script jetable lié au brief 2026-05-10_brief-pivot-templates-narratifs-jeu-differences.md.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from services.prompt_generator import PromptGenerator  # noqa: E402

g = PromptGenerator()

print("=== SMOKE — lion_in_savanna (template solo, hors pivot) ===")
r = g.build_prompt("lion_in_savanna")
print("positive[:80]=", r["positive"][:80])
print("workflow_class=", r["workflow_class"])
print()

frieze_leaves = [
    "baby_first_year",          # life_cycle_and_aging — Frise narrative 1×N
    "spring_blooming_meadow",   # four_seasons — Frise narrative 1×4
    "football_match_scene",     # team_sports — Multi-sujets ou Scène d'action
]
grid_leaves = [
    "fruits_basket",            # food_categories — Imagier différencié 3×3
    "food_pyramid_for_kids",    # healthy_eating — Imagier différencié OU Solo
    "number_zero_with_eggs",    # illustrated_numbers — Multi-sujets via grille
]

print("=== template_frieze_1xN — 3 prompts ===")
for lid in frieze_leaves:
    r = g.build_prompt(lid)
    print(f"--- {lid}  (class={r['workflow_class']!r}) ---")
    print("POSITIVE:")
    print(r["positive"])
    print()

print("=== template_grid_3x3_imagier — 3 prompts ===")
for lid in grid_leaves:
    r = g.build_prompt(lid)
    print(f"--- {lid}  (class={r['workflow_class']!r}) ---")
    print("POSITIVE:")
    print(r["positive"])
    print()
