# Phase complétée — P2 Content Generator (⑥b)
Date : 2026-05-05

## Contexte
Implémentation du **service de génération de contenu éditorial i18n** pour la Phase 2 du pipeline (cf. `docs/workflow-pipeline.md` § Phase 3 ⑥b). Le service produit, à partir d'un concept image, le triplet **EN + FR + AR** complet (title, title_card, description, keywords) en respectant les SOFT caps pipeline (cf. `CLAUDE.md` § Validation de contenu) et les contraintes AR spécifiques (no harakat, no latin, ancre lexicale du term parent).

## Architecture du service

### Module
`src/services/content_generator.py`

### Dataclasses

```python
@dataclass
class LocaleContent:
    title: str
    title_card: str
    description: str
    keywords: list[str]

@dataclass
class ContentResult:
    en: LocaleContent
    fr: LocaleContent
    ar: LocaleContent
    review_flags: list[str]   # ex. ["ar_anchor_missing", "ar_retried_2x", "en_bounds:..."]
    retries_ar: int
    latency_ms: int
```

### Entrypoint

```python
def generate_content(
    concept_name_en: str,
    concept_name_fr: str,
    term_name_ar: str,        # ancre AR depuis term.name_ar
    model: str = "qwen3.5:4b",
    max_retries: int = 3,
) -> ContentResult
```

### Flow interne

```
1. Generate EN (1 call)              → bornes [40,60] / ≤30 / [80,130]
2. Generate FR (1 call, guidé par concept_name_fr) → bornes EN/FR
3. Generate AR (loop, max_retries calls)
   ├─ call LLM avec ancrage term_name_ar
   ├─ strip_harakat sur tous les champs (post-process)
   ├─ validate_ar :
   │   ├─ HARD : bornes [25,55]/≤25/[40,100], pas de chars latins
   │   └─ SOFT : ancre présente (ou variante morphologique)
   ├─ si HARD vide → break
   ├─ sinon → retry (jusqu'à max_retries)
   └─ accumuler anchor_failures
4. Construire review_flags :
   - ar_hard_issues:... (si hard issues persistent au dernier essai)
   - ar_retried_Nx (si retries_ar > 0)
   - ar_anchor_missing (si anchor_failures ≥ 2 ou absent au final)
   - en_bounds:... / fr_bounds:... (sans regen — surfaçage seulement)
5. Return ContentResult (avec latency_ms)
```

### Bornes SOFT (cf. CLAUDE.md "Validation de contenu")

| Champ | EN/FR | AR |
|---|---|---|
| `title` | [40, 60] | [25, 55] |
| `title_card` | ≤ 30 | ≤ 25 |
| `description` | [80, 130] | [40, 100] |
| `keywords` count | 5 | 5 |

EN/FR : bornes surfacées en `review_flags` (pas de regen — coût latence prohibitif × 3 locales). Seul l'AR a une boucle validate-regen, parce que c'est la locale la plus problématique côté qualité (cf. POC qwen35-volume).

### Endpoint API

```
POST /api/ai/generate-content
Body : { concept_name_en, concept_name_fr, term_name_ar, model?, max_retries? }
→ 200 { en, fr, ar, review_flags, retries_ar, latency_ms }
→ 502 si erreur LLM
```

Synchrone (pas de queue) — typique 10-30 s par appel.

### Helpers ajoutés à `src/services/ollama_json.py`

- `HARAKAT_RE` : compilée avec codepoints explicites `[ؐ-ًؚ-ٟ]` (RTL trap résolu — bug déjà rencontré dans 3 POC précédents).
- `strip_harakat(text)` : retire tous les harakat d'une string. No-op sur texte non-arabe.

## Tests unitaires

Fichier : `tests/test_content_generator.py` — 5 tests, **5/5 PASSED**.

| Test | Vérifie |
|---|---|
| `test_generate_content_en_fr_ar_valid` | Happy path : 3 locales valides, 0 retry, 0 review_flag |
| `test_ar_regen_on_desc_too_long` | 1er AR retourne desc 110c (hors [40,100]) → regen → 2e AR à 60c valide → `retries_ar=1`, flag `ar_retried_1x` |
| `test_ar_strip_harakat` | LLM retourne AR vocalisé → harakat strippés avant validation, ancre `ميكي` présente après strip |
| `test_ar_anchor_missing_flag` | LLM ne retourne jamais l'ancre AR → flag `ar_anchor_missing` posé |
| `test_strip_harakat_helper` | Sanity check de l'utilitaire `strip_harakat` (codepoints explicites OK) |

Mocks : `monkeypatch.setattr(cg, "call_ollama_sync", fake_call)` avec une queue de réponses canned. Aucune dépendance Ollama vivant. Cohérent avec la convention `tests SQLite-portable` du projet.

### Suite complète après ajout

`pytest --ignore=tests/test_start_singleton_lock.py` → **144 passed in 2.04s**. Aucune régression. Le test `test_start_singleton_lock` était déjà cassé avant mes modifs (`No module named 'start'` — issue pré-existante de PYTHONPATH).

## Exemple — appel réel sur Mickey Mouse

Appel direct via `python -c "from services.content_generator import generate_content; ..."` avec :
- `concept_name_en="Mickey Mouse in a Magic Forest"`
- `concept_name_fr="Mickey Mouse dans une forêt magique"`
- `term_name_ar="ميكي ماوس"`
- `model="qwen3.5:4b"` (défaut)
- `max_retries=3` (défaut)

Réponse réelle (latency_ms = 34 423) :

### EN
| Champ | Valeur | Longueur | Borne |
|---|---|---|---|
| title | `Mickey Mouse in a Magic Forest Adventure` | 40 | [40,60] ✓ |
| title_card | `Mickey Magic Forest` | 19 | ≤30 ✓ |
| description | `Color this delightful page featuring Mickey Mouse exploring a vibrant enchanted woodland filled with glowing mushrooms and friendly creatures.` | 142 | [80,130] ⚠ (+12) |
| keywords | `Mickey Mouse`, `Magic Forest`, `Coloring Page`, `Childrens Art`, `Enchanted Woods` | 5 ✓ | |

### FR
| Champ | Valeur | Longueur | Borne |
|---|---|---|---|
| title | `Mickey Mouse dans une forêt magique` | 35 | [40,60] ⚠ (-5) |
| title_card | `Mickey dans la forêt` | 20 | ≤30 ✓ |
| description | `Découvrez Mickey Mouse explorant une forêt enchantée remplie de créatures mystérieuses et de lumières magiques pour les enfants.` | 127 | [80,130] ✓ |
| keywords | `Mickey`, `forêt`, `magique`, `coloriage`, `enfants` | 5 ✓ | |

### AR (3 retries, harakat strippés post-process)
| Champ | Valeur | Longueur | Borne |
|---|---|---|---|
| title | `ميكي ماوس في الغابة السحرية` | 27 | [25,55] ✓ |
| title_card | `ميكي ماوس في الغابة السحرية` | 27 | ≤25 ⚠ (+2) |
| description | `تصفح صفحة التلوين الخاصة بميكي ماوس في الغابة السحرية، حيث يجتمع البطل مع الحيوانات في عالم مليء بالأسرار والمغامرات.` | 117 | [40,100] ⚠ (+17) |
| keywords | `ميكي ماوس`, `الغابة السحرية`, `صفحة تلوين`, `أطفال`, `مغامرات` | 5 ✓ | |

### review_flags

```
[
  "ar_hard_issues:title_card_len=27 > 25,description_len=117 not in [40,100]",
  "ar_retried_3x",
  "en_bounds:description_len=142 not in [80,130]",
  "fr_bounds:title_len=35 not in [40,60]"
]
```

→ `retries_ar = 3` (max épuisé) — l'AR n'a jamais convergé sur les bornes title_card et description. L'admin voit immédiatement les 4 dimensions à arbitrer en file d'exception : raccourcir title_card AR, raccourcir desc AR, raccourcir desc EN, allonger title FR.

L'**ancre AR (ميكي ماوس) est bien présente** dans le title et la description AR — pas de flag `ar_anchor_missing`. Le pipeline a fait son job d'ancrage taxonomique.

## Points d'attention

- **`max_retries=3` épuisé sur AR** dans cet exemple → en production, c'est probablement le cas dominant (qwen3.5:4b a tendance à dépasser 100c sur AR description même après retry, cf. POC qwen35-volume où 14/38 desc dépassaient 100). Deux options :
  - **Élargir la borne** AR description haute à 110-120c (acceptable côté UX et toujours dans HARD cap [20,200]).
  - **Garder [40,100]** + accepter ~37 % de retry budget × 3 locales = ~12 s ajoutées par image.
- **Pas de regen sur EN/FR** : décision de design (coût latence × 3 locales prohibitif). EN/FR vont en file d'exception via `review_flags`. Si volume des flags devient ingérable, on peut activer un regen optionnel via paramètre `regen_en_fr=True`.
- **Détection de mots anglais en FR** non implémentée (le check `_has_latin` était bogué — FR contient naturellement du latin). À ajouter en v2 via une heuristique lexicale (ex. mots de 3+ chars sans accent et présents dans un dictionnaire EN connu).
- **Latence ~34 s par image** = 3 calls × 2-3 s × 1-3 retries. Acceptable en pipeline asynchrone batch. À mesurer en charge réelle (concurrence Ollama remote — cf. dette technique POC-LLM v2).
- **`title_card` dépasse souvent ≤25** sur AR (27 ici). Probablement parce que le modèle tend à recopier le `title` complet dans le `title_card` quand le sujet est court. À surveiller — peut nécessiter une consigne plus stricte dans le prompt AR.

## Décision / Action suivante

✅ **Service P2 ⑥b livré et fonctionnel** :
- Endpoint `POST /api/ai/generate-content` opérationnel
- Tests unitaires 5/5 ✓, suite globale 144/144 ✓ (aucune régression)
- Helper `strip_harakat` ajouté à `ollama_json.py` (codepoints explicites — bug regex définitivement résolu)
- review_flags surfacent les écarts pour l'admin sans bloquer le pipeline

À adresser **avant intégration au worker queue** :
1. **Wrapping job_type** : ce service est sync. Pour l'intégrer à la queue de jobs (cf. `base_worker.py`), créer un job_type `image_generate_i18n_content` qui appelle `generate_content()` et stocke le résultat dans `image_locale_content` (table à créer en P1 si pas encore fait).
2. **Décision bornes AR description** : élargir à [40, 120] ou garder [40, 100] avec budget retry. À arbitrer côté hamma.
3. **POC volume** : tester sur 50 images réelles pour mesurer (a) le taux de retries_ar, (b) la distribution des review_flags, (c) la latence cumulée. Bench distinct, scope de la prochaine étape P2.

## Annexes

- Service : `src/services/content_generator.py`
- Endpoint : `src/api/routes/ai.py` (route `/api/ai/generate-content`, request model `GenerateContentRequest`)
- Tests : `tests/test_content_generator.py` (5 tests, 5/5 ✓)
- Utilitaire ajouté : `src/services/ollama_json.py::strip_harakat` (+ `HARAKAT_RE` codepoints explicites)
- Routing LLM appliqué : `qwen3.5:4b` (cf. `2026-05-05_decision-llm-finale.md`)
- Bornes appliquées : cf. `CLAUDE.md` § "Validation de contenu" + `2026-05-05_analyse-bornes-validation.md`
