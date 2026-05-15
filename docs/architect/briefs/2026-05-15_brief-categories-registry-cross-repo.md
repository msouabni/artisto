# Brief — Registry partagé categoryId + test cross-repo + génération MDs depuis registry

Date : 2026-05-15
Pour : claude-code d'exécution
Repo cible : `D:\projets\artiste-coloriage` (principal) + `D:\projets\rimalab-v2` (génération MDs en sortie)

---

## Contexte

Bug A diagnostiqué 2026-05-14 : le mapper `map_leaf_to_category()` côté `artiste-coloriage` produit des categoryId (9 distincts) sans valider qu'ils existent dans `src/content/categories/*.md` côté `rimalab-v2`. Le build Astro casse au validate Zod.

Fix tactique 2026-05-14 : 7 .md catégories créés manuellement côté rimalab via brief. Mais 2026-05-15 on découvre que **claude rimalab a aussi créé 6 catégories sur main entre-temps**, avec des wordings/weights différents → divergence. Le merge `content/export-mep-v0 → main` est suspendu en attendant ce brief.

**Solution durable** : un seul registry JSON côté `artiste-coloriage` est la source unique de vérité ; le mapper le consulte (impossible d'inventer un ID) ; le pipeline régénère les MDs catégories côté rimalab depuis ce registry (idempotent).

Décision archi 2026-05-15 : on prend **nos wordings** (du brief tactique 2026-05-14) comme base initiale du registry. Le claude rimalab sera notifié séparément ; les wordings sont négociables via PR sur le registry, jamais en touchant `src/content/categories/*.md` directement côté rimalab.

## Objectif

Implémenter les 4 livrables suivants :

1. **`data/categories_registry.json`** — source unique de vérité
2. **Refactor `map_leaf_to_category()`** dans `scripts/alwanbooks_pipeline.py` (ou `src/services/`) — lit le registry, refuse d'émettre un id inconnu
3. **Test pytest `tests/test_categories_registry.py`** — garde-fou : tous les leaves taxonomy mappent vers un id présent dans le registry ; tous les IDs émis par le mapper sont dans le registry
4. **Extension `alwanbooks_pipeline.py --sync-categories`** — flag CLI qui régénère les MDs `src/content/categories/*.md` côté `rimalab-v2` depuis le registry (idempotent, calque pattern existant `write_post_md` qui écrit déjà des MDs frontmatter dans rimalab)

Hors-scope mais documenté : un pre-commit hook côté rimalab-v2 qui appelle `--sync-categories` avant chaque commit sur main. À discuter post-livraison.

## Branche cible

Créer une branche dédiée côté artiste-coloriage :
```
git checkout -b feat/categories-registry-cross-repo
```

Push origin uniquement quand les 4 livrables sont mergés sur cette branche.

## Livrable 1 — `data/categories_registry.json`

**Path** : `D:\projets\artiste-coloriage\data\categories_registry.json`

**Schéma** (calque Astro frontmatter Zod + champs internes) :

```json
{
  "version": 1,
  "categories": [
    {
      "id": "animals",
      "parent_id": null,
      "weight": 1,
      "slug_i18n": { "ar": "hayawanat", "fr": "animaux", "en": "animals" },
      "name_i18n": { "ar": "حيوانات", "fr": "Animaux", "en": "Animals" },
      "description_i18n": {
        "ar": "...",
        "fr": "Coloriages d'animaux pour enfants — chats, lions, animaux de compagnie et sauvages, illustrations simples pour un coloriage facile et amusant.",
        "en": "Animal coloring pages for kids — cats, lions, pets and wild animals, simple line art for easy and fun coloring."
      },
      "keywords_i18n": {
        "ar": ["...", "...", "..."],
        "fr": ["coloriage animaux", "animaux à imprimer", "coloriage enfant"],
        "en": ["animals coloring", "animal coloring pages", "kids coloring"]
      },
      "body": "Catégorie racine pour tous les coloriages d'animaux.",
      "scope_note": "Racine de tous les sous-types animaux. Inclut par transitivité : felins, lions, oiseaux, marins, pets, wild (avec animaux de ferme et créatures fantastiques selon scope animals_pets / animals_wild)."
    }
  ]
}
```

**Champs publics vs internes** :

| Champ | Destination | Rôle |
|---|---|---|
| `id`, `parent_id`, `weight`, `slug_i18n`, `name_i18n`, `description_i18n`, `keywords_i18n` | Frontmatter Astro `src/content/categories/*.md` | Public, validé par Zod côté rimalab |
| `body` | Corps du `.md` | Public, résumé éditorial (1 ligne) |
| `scope_note` | **Registry uniquement, PAS dans le .md généré** | Interne, doc taxonomique pour le mapper et l'équipe |

Le `scope_note` documente précisément ce qui tombe dans cette catégorie côté mapper (ex: "pets inclut farm animals : sheep, cow, donkey…"). Il n'est jamais propagé dans les MDs régénérés. C'est une décision archi : la doc de scope doit vivre avec le registry, pas avec les MDs publics (qui sont régénérés).

**Scope notes critiques (à appliquer dans le registry initial)** :

- `animals_pets` : `"Animaux de compagnie + animaux de ferme. Inclut : chiens, lapins, rongeurs, oiseaux domestiques, chats domestiques (non big cats), moutons, vaches, chèvres, ânes, oies, canards (selon mapper). Décision archi 2026-05-15 : pas de animals_farm séparé pour réduire la fragmentation taxonomique."`
- `animals_wild` : `"Faune sauvage terrestre + créatures fantastiques animales. Inclut : éléphant, fox, loup, ours, tigre, leopard, jaguar, kangourou, butterfly, bee, snail, spider, ainsi que dragon, griffin, phoenix. Exclut : fairy / yeti (humanoïdes → general_humans). Décision archi 2026-05-15 : pas de animals_fantastic séparé."`
- `general_humans` : `"Humains et humanoïdes. Inclut : professions (firefighter, doctor, baker…), sportifs, personnages cartoon (iron_man, scooby_doo, tintin, mirabel), créatures humanoïdes fantastiques (fairy, yeti, princess, wizard, elf)."`
- `objects_things` : `"Fallback ultime. Inclut tout ce qui n'est pas vivant : véhicules, outils, motifs décoratifs (mandala_lion_head), jouets, bâtiments, objets du quotidien."`
- Pour les autres (animals, animals_cats, animals_lions, animals_birds, animals_marine, letters_arabic) : scope_note court (1 ligne suffit, le contenu est évident depuis le name).

**Initialisation** : Charger 10 catégories.

3 catégories historiques (à recopier exactement depuis `D:\projets\rimalab-v2\src\content\categories\animals.md`, `animals_cats.md`, `animals_lions.md` — encodage UTF-8 pour caractères AR) :

- `animals` (parent: null, weight: 1)
- `animals_cats` (parent: animals, weight: 10)
- `animals_lions` (parent: animals, weight: 20)

7 nouvelles catégories (à recopier depuis le brief tactique `docs/architect/briefs/2026-05-14_brief-creation-categories-rimalab-v2.md`, sections "Contenu littéral des 7 fichiers") :

- `animals_birds` (parent: animals, weight: 30)
- `animals_marine` (parent: animals, weight: 40)
- `animals_pets` (parent: animals, weight: 50)
- `animals_wild` (parent: animals, weight: 60)
- `general_humans` (parent: null, weight: 100)
- `objects_things` (parent: null, weight: 200)
- `letters_arabic` (parent: null, weight: 300)

**Contraintes** :
- `id` strictement `^[a-z][a-z0-9_]*$`
- `parent_id` null OU un id présent ailleurs dans le registry (transitive closure validée par test)
- 3 keywords par locale, **toujours** AR/FR/EN
- `body` = ligne courte (suffit pour Astro)
- JSON sérialisé avec `ensure_ascii=False` pour rendre les caractères AR lisibles dans le fichier
- Indentation 2 espaces

## Livrable 2 — Refactor mapper

**Cible** : `scripts/alwanbooks_pipeline.py:506` (`map_leaf_to_category`)

**Avant** : 8 règles ordonnées qui retournent des strings literal (`'animals_lions'`, `'objects_things'`, etc.) — peuvent inventer n'importe quoi.

**Après** :
1. Au startup du module : charger `data/categories_registry.json` une seule fois (cache module-level).
2. Construire `KNOWN_CATEGORY_IDS = frozenset(c["id"] for c in registry["categories"])`.
3. `map_leaf_to_category(leaf_id, ...)` : à la fin de la fonction, **avant de retourner**, vérifier `assert result in KNOWN_CATEGORY_IDS, f"mapper emitted unknown categoryId: {result}"`. Si le check casse → c'est un bug local, on veut un fail-fast (le test pytest l'attrapera avant).
4. Pas d'autres changements de logique métier (mêmes 8 règles).

**Compatibilité** : le pattern actuel `map_leaf_to_category` continue de fonctionner. Aucun appelant côté `alwanbooks_pipeline.py` ne change.

## Livrable 3 — Test pytest

**Path** : `tests/test_categories_registry.py`

**Tests minimum** :

```python
def test_registry_is_valid_json():
    """Le fichier registry parse en JSON valide."""

def test_registry_has_required_schema():
    """Chaque catégorie a id/parent_id/weight/slug_i18n/name_i18n/description_i18n/keywords_i18n/body."""

def test_registry_ids_are_unique():
    """Pas de doublon d'id dans le registry."""

def test_registry_ids_match_regex():
    """Tous les id matchent ^[a-z][a-z0-9_]*$."""

def test_registry_parent_ids_resolve():
    """Tout parent_id non-null pointe vers un id existant dans le registry (transitive)."""

def test_registry_i18n_has_three_locales():
    """slug_i18n / name_i18n / description_i18n / keywords_i18n ont toujours AR/FR/EN."""

def test_registry_keywords_count():
    """Chaque locale a exactement 3 keywords (cohérent avec les MDs existants)."""

def test_mapper_only_emits_known_categories():
    """Pour les 1376 leaves taxonomy, map_leaf_to_category retourne uniquement des IDs présents dans le registry."""
    # Charger coloring_taxonomy_full.json, itérer toutes les feuilles, vérifier
    # qu'aucun retour du mapper n'est hors registry.
```

**Convention** : tests pytest SQLite-portables (cf. CLAUDE.md §Pipeline). Pas de DB requise pour ces tests, c'est du pur in-memory.

**Suite globale** : la suite doit rester verte (`pytest --ignore=tests/test_content_generator.py`). Si un test préexistant casse à cause de cette refonte → diagnostic et fix dans le même brief.

## Livrable 4 — Génération MDs depuis registry

**Cible** : `scripts/alwanbooks_pipeline.py`, nouveau flag CLI `--sync-categories`.

**Comportement** :
- Quand `--sync-categories` est passé, le pipeline ignore les Posts et écrit uniquement les MDs `<rimalab_root>/src/content/categories/<id>.md`.
- 1 fichier MD par catégorie du registry. Frontmatter conforme au schema Astro Zod (calque `animals_lions.md`).
- **`scope_note` n'est PAS écrit dans le .md** — c'est un champ interne du registry uniquement.
- **Idempotence byte-identique** (critère dur, à confirmer en test) : re-run sans modification du registry → 0 fichier touché (compare bytes via SHA-256 ou diff direct, pas juste mtime). Sinon faux diffs git à chaque sync, l'utilisateur perd confiance.
- **Ordre déterministe** des champs YAML frontmatter : `id`, puis `slug_i18n` (ar/fr/en), puis `name_i18n` (ar/fr/en), puis `description_i18n` (ar/fr/en), puis `keywords_i18n` (ar/fr/en), puis `parent_id`, puis `weight`. Indentation 2 espaces. Strings entre apostrophes simples (cohérent avec les .md existants : `id: 'animals_lions'`). Newline final unique.
- Encodage UTF-8 **sans BOM** (cohérent avec les .md existants côté rimalab). Vérifier first bytes `!= 239,187,191`.
- Logging : `[sync-categories] wrote=X skipped=Y total=Z`.

**Combinaison** : `python scripts/alwanbooks_pipeline.py --sync-categories --no-git-push` → uniquement les categories, pas de commit auto.

**Aussi** : ajouter `--sync-categories` à l'aide CLI `--help`.

**Test pytest** : `tests/test_sync_categories.py` :
- Mock filesystem (`tmp_path`), passer un registry minimal (2 catégories), appeler la fonction sync, vérifier 2 MDs écrits avec le bon contenu.
- **Test idempotence byte-identique** : re-run = 0 écriture supplémentaire si contenu identique. Vérifier via `Path.stat().st_mtime` inchangé OU via assertion explicite que la fonction `_write_if_changed` retourne `False` (skipped) sur le 2e appel.
- Test que `scope_note` n'apparaît jamais dans le .md généré (vérifier `"scope_note" not in md_content`).

## Workflow utilisateur post-livraison

```powershell
# 1. Modifier une catégorie (renommer, changer wording, ajouter une nouvelle)
#    → éditer data/categories_registry.json uniquement
# 2. Tests
pytest tests/test_categories_registry.py -v
# 3. Régénérer les MDs côté rimalab
cd D:\projets\artiste-coloriage
python scripts/alwanbooks_pipeline.py --sync-categories --no-git-push
# 4. Commit + push côté rimalab
cd D:\projets\rimalab-v2
git add src/content/categories/
git commit -m "sync(categories): regen depuis registry artiste-coloriage v<X>"
git push origin <branche>
```

C'est désormais le seul workflow autorisé pour modifier une catégorie. Toute modification directe de `src/content/categories/*.md` côté rimalab sans passer par le registry = à rejeter en PR review.

## Critères d'acceptation

1. `data/categories_registry.json` créé avec 10 catégories valides (3 historiques + 7 nouvelles)
2. `map_leaf_to_category()` refactoré (charge registry au boot, assert avant retour)
3. `tests/test_categories_registry.py` créé, 8+ tests verts
4. `tests/test_sync_categories.py` créé, 2+ tests verts
5. Flag `--sync-categories` opérationnel dans `alwanbooks_pipeline.py`, aide CLI mise à jour
6. Suite pytest globale : aucune régression (`pytest --ignore=tests/test_content_generator.py`)
7. Sanity manuel : `python scripts/alwanbooks_pipeline.py --sync-categories --no-git-push` régénère 10 MDs côté `D:\projets\rimalab-v2\src\content\categories\`, diff git visible si wordings diffèrent de l'actuel
8. Branche `feat/categories-registry-cross-repo` créée côté artiste-coloriage, commits propres, **PAS de push origin** (l'archi valide avant push)
9. Rapport `docs/reports/2026-05-15_phase-categories-registry-cross-repo.md` rédigé

## Hors-scope

- Modification de `src/content/categories/*.md` côté rimalab manuellement (le sync s'en charge)
- Modification de `src/content/posts/*/*.md` côté rimalab (les Posts ne changent pas)
- Push origin de la branche `feat/categories-registry-cross-repo` (archi valide d'abord)
- Pre-commit hook côté rimalab (à discuter post-livraison)
- Investigation du Bug B (5 slugs FR=EN identiques, brief séparé)
- Résolution du merge content/export-mep-v0 → main (séparé, après livraison de ce brief)

## Reporting

`docs/reports/2026-05-15_phase-categories-registry-cross-repo.md` (côté artiste-coloriage) avec :
- Fichiers livrés (path + LOC approximatif)
- Sortie complète pytest pour les nouveaux tests
- Diff observé après `--sync-categories --no-git-push` (combien de MDs régénérés vs identiques)
- Commits créés sur la branche (hash + message)
- Tout point d'attention rencontré
