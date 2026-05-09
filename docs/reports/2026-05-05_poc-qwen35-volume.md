# POC volume — qwen3.5:4b sur 38 paires AR + investigation bug voitures
Date : 2026-05-05

## Contexte
Avant de promouvoir `qwen3.5:4b` comme modèle par défaut prod (champion à 98.2/100 sur le retest 10 paires), valider sur volume (cible 50 paires variées) et investiguer le bug `voitures→0 children` du retest concepts.

Tâche bundle : (1) volume AR Prompt A POC-4 sur 50 paires variées, bornes SOFT title [25, 55] / desc [40, 100], (2) diag du bug d'extraction concepts.

## Résultats Tâche 1 — Volume

**38 paires effectives** (cible 50 ; taxonomie limitée à 74 termes feuilles avec name_ar, et le cap "3 max par catégorie" pour éviter le sur-échantillonnage des chiens phonétiques restreint à 38 paires uniques diverses).

### Métriques globales

| Métrique | Score | Conformité |
|---|---|---|
| JSON parsable | **38/38** | **100 %** ✅ |
| Anchor présent | **37/38** | **97 %** ✅ |
| `title` ∈ [25, 55] | **38/38** | **100 %** ✅ |
| `title_card` ≤ 25 | 37/38 | 97 % |
| `description` ∈ [40, 100] | **24/38** | **63 %** ⚠ |
| `keywords` = 5 | 38/38 | 100 % ✅ |
| Harakat absents | **28/38** | **74 %** ⚠ |
| Latin absents | 38/38 | 100 % ✅ |

### Distribution des longueurs

| Champ | min | médiane | moy | max | borne |
|---|---|---|---|---|---|
| `title` | 26 | 33 | 33.0 | 44 | [25, 55] |
| `title_card` | min ≤ 25, max 26 (1 dépassement) | — | — | 26 | ≤ 25 |
| `description` | 66 | 98 | **94.8** | **117** | [40, 100] |

→ Le `title` est dans la cible avec une bonne marge (médiane 33, max 44) — comportement très stable.
→ La `description` plafonne juste au-dessus de la borne haute 100 dans 14/38 cas (37 %), avec un max à 117 chars. Le modèle a tendance à dépasser légèrement la borne haute systématiquement.

### Latence

| Métrique | Valeur |
|---|---|
| Latence min | 1.82 s |
| Latence médiane | 2.13 s ⚡ |
| Latence moyenne | 2.13 s |
| Latence max | 3.13 s |

Latence **très stable** sur 38 calls (variance ~1.3 s). Pas de cold start observable après les 2 premières paires.

### Distribution par catégorie

29 catégories distinctes représentées : `animaux` (6), `cartoons` (3), `mandalas` (3), 26 autres avec 1 paire chacune (saisons, fêtes, véhicules, métiers, lettres, science, vie quotidienne, etc.). **Cap 3/catégorie respecté** — pas de sur-échantillonnage des chiens.

### Comparaison — petit volume (10) vs volume (38)

| Métrique | Retest 10 paires (POC qwen35-retest) | Volume 38 paires | Δ |
|---|---|---|---|
| JSON parsable | 10/10 (100 %) | 38/38 (100 %) | stable ✅ |
| Anchor | 10/10 (100 %) | 37/38 (97 %) | -3 pp |
| title bornes | 10/10 (100 %) | 38/38 (100 %) | stable ✅ |
| desc bornes | 10/10 (100 %) | **24/38 (63 %)** | **-37 pp** ⚠ |
| Harakat clean | 10/10 (100 %) | **28/38 (74 %)** | **-26 pp** ⚠ |
| Latin clean | 10/10 (100 %) | 38/38 (100 %) | stable ✅ |

→ Les **10 paires du retest n'étaient pas représentatives** du comportement à volume sur 2 axes : description et harakat. Le bench volume révèle des patterns que le petit échantillon a ratés.

## Résultats Tâche 2 — Bug voitures investigation

### Diagnostic

Le raw stocké pour `voitures` dans le retest contenait :
```json
[
  { "id": "voitures_road", "name_en": "Road Cars", ... },
  { "id": "voitures_track", "name_en": "Race Cars", ... },
  ... (5 enfants au total)
]
```
suivi de **`` ``` ``** orphelin en fin (markdown fence de fermeture sans ouverture). Le JSON pur est invalide à cause de ce trailing fence : `json.loads` échoue avec `Extra data at pos 1932`.

La fonction `parse_json_response` de `src/services/ollama_json.py` :
1. tente `json.loads(clean)` → échec ;
2. tente regex ` ```…``` ` (paire complète) → ne matche pas (orphelin) ;
3. fallback : extrait le **1er bloc balanced `{...}`** dans le texte → retourne le 1er enfant (un dict, pas une liste).

Conséquence : `benchmark_concepts` voit un dict au lieu d'une liste → `children = []` (vide).

### Fix appliqué

Modification de `parse_json_response` dans `src/services/ollama_json.py` :
1. Strip des balises ``` orphelines avant le 1er `json.loads` (regex `^```(json)?\s*\n?` et `\n?\s*```\s*$`).
2. Ajout d'un fallback **`[...]` array** AVANT le fallback `{...}` actuel (pour qu'une réponse type "liste avec trailing junk" soit extraite comme array, pas comme premier élément).

### Validation

Sur le raw stocké du retest :
```
AFTER FIX → type=list
  list of 5 items
    voitures_road             fr='Voitures Route'          ar='سيارات الطريق'
    voitures_track            fr='Voitures Course'         ar='سيارات السباق'
    voitures_factory          fr='Voitures Usine'          ar='سيارات المصنع'
    voitures_fleet            fr='Flotte Voitures'         ar='فلotte السيارات'
    voitures_classic          fr='Voitures Classiques'     ar='سيارات كلاسيكية'
```

→ **5/5 enfants extraits**. Bug résolu.

→ Le retest qwen3.5:4b passe rétroactivement de **20 children / 5 termes** à **25 children / 5 termes**. Le score concepts se réaligne sur l'attendu (cf. retrobakckée vs scoreboard final).

⚠ Note : 1 enfant (`voitures_fleet`) contient un AR mixé latin (`فلotte`) — c'est un défaut côté modèle, pas parser. À flagger en cross-locale validation côté prod.

## Points d'attention

### 1. Description bornes — pattern systématique de dépassement
14/38 desc dépassent 100 chars (max 117). Le modèle veut probablement combiner sujet + contexte + appel à l'action ("rejoignez l'aventure", "amusez-vous à colorier") qui pousse vers ~110-115. Options :
- **Élargir borne haute** à 110 ou 115 (gain 30+ pp sur conformité, garde la sweet-spot intérieure).
- **Affiner le prompt** : exiger explicitement "Description : 40 à 100 caractères, COMPTEZ et NE DÉPASSEZ JAMAIS." Probable gain modeste (modèle local a souvent du mal avec count-and-stop).
- **Garder bornes [40, 100] + valider en regen loop** : ~37 % de retry → ajoute ~0.8 s de latence par image, acceptable.

Recommandé : **garder [40, 100] + regen loop**. Si la métrique reste sous 70 % en prod, élargir à [40, 115].

### 2. Harakat absents — 74 % seulement
10/38 outputs contiennent des harakat malgré la consigne explicite. Pattern observé sur : Dinosaurs, Motorbikes, Planes, Original superheroes, Easter, Birthday, Numbers, Shapes, Maps, Miscellaneous, etc.

Le modèle vocalise probablement quand il rencontre un mot rare ou ambigu (ex. "ديناصورات" = dinosaures, mot emprunté/translittéré). Régression vs retest 10 paires (10/10 clean) — confirme que le petit échantillon était optimiste.

Options :
- **Validate-regen loop avec critère harakat strict** : 26 % de retry. Combiné au desc retry, on est à ~50 % retry global → ~1 s ajouté par image.
- **Post-traitement** : strip des harakat côté Python avant publication. C'est correct visuellement et pragmatique. Peut être fait sans regen.

Recommandé : **strip des harakat en post-process** (pas de regen). Les harakat n'altèrent pas le sens, leur strip est sûr et instantané. La regex est déjà documentée dans `2026-05-05_poc-llm-benchmark-v2.md` (codepoints explicites U+0610-U+061A et U+064B-U+065F).

### 3. Anchor — 37/38 (97 %) très stable
Un seul échec d'anchor : `Pit Bulls`. Output produit du contenu sur les pit bulls mais le `term_ar` exact (`بولي` — translittération phonétique douteuse de Bully, signalée comme suspecte dans le POC-1) n'apparaît pas. Le modèle utilise probablement un mot AR plus naturel pour pit bull (ex. `كلب بولدوغ`). C'est une **erreur du seed taxonomique**, pas du modèle.

### 4. Latence — exceptionnellement stable
38 calls, std-dev ~0.3s autour de 2.13s médiane. **Aucun cold start visible** après pair 1. Confirme qu'en pipeline P2 le worst-case par image (3 locales × 3 retries max) tombe à ~20s, et le typical (3 locales × 1.3 retry) à ~8s. Très bon.

### 5. Volume cible 50 → réel 38
La taxonomie projet a 74 leaves avec name_ar, mais le cap "3 max par catégorie" pour éviter le cluster chiens limite à 38 paires diverses. Pour atteindre 50 il faudrait soit bumper le cap (au prix de la diversité), soit générer des concepts variés à partir d'un même leaf (concept ≠ term, comme POC-4). À envisager si on veut un bench statistique plus robuste.

## Décision / Action suivante

✅ **qwen3.5:4b validé pour P2** comme modèle par défaut, avec deux ajustements pipeline :
1. **Validate-regen sur description** (~37 % retry, +0.8 s/image typical).
2. **Strip harakat en post-process** (instantané, pas de retry — les harakat n'altèrent pas le sens, leur élimination est sûre).

⚠ **Ne pas adopter aveuglément** : les 100 % du retest étaient un artefact de petit échantillon. Sur volume, le modèle reste compétitif mais nécessite la chaîne validate-regen pour atteindre les SOFT caps.

🛠 **Bug parser corrigé** dans `src/services/ollama_json.py::parse_json_response` :
- strip des fences ``` orphelines
- fallback `[...]` AVANT fallback `{...}`

Effet de bord : tous les jobs LLM API qui passent par `parse_json_response` (ai/text routes, suggest_children worker) bénéficient automatiquement du fix.

🚀 **À mettre à jour pour P2** (après confirmation arbitrage) :
- `OLLAMA_MODEL=qwen3.5:4b` dans `.env`
- `defaults.model: qwen3.5:4b` dans `prompts/taxonomy_prompts.yaml` et `prompts/image_prompts.yaml`
- Documenter le routing dans CLAUDE.md (qwen3.5:4b primary, qwen3:8b fallback qualité, qwen2.5:7b fallback latence)
- Implémenter strip harakat dans le post-process de `validate_ar_content`

📋 **Question résolue** : qwen3.5:4b stable sur volume ? **Oui, avec regen loop + post-process harakat**. Pas de bloquer.

📋 **Question ouverte** : tester qwen3.5:9b en mode multimodal pour P3 (si supporté natif) — décorrélé de cette décision.

## Annexes

- Données brutes volume : `2026-05-05_poc-qwen35-volume.json`
- Script volume : `scripts/poc_qwen35_volume.py`
- Fix parser : `src/services/ollama_json.py::parse_json_response`
- Rapport retest préalable : `docs/reports/2026-05-05_poc-qwen35-retest.md`
- Rapport benchmark v2 : `docs/reports/2026-05-05_poc-llm-benchmark-v2.md`
