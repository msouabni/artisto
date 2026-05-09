# Analyse — Convention de reporting projet
Date : 2026-05-05

## Contexte
Mise en place d'une convention systématique de reporting pour le projet artiste-coloriage : tout output significatif que l'utilisateur doit consulter va dans `docs/reports/` avant la fin de la réponse, sans attendre qu'il le demande. Le fichier est le livrable principal, le chat un résumé optionnel.

## Résultats

### Convention installée

**Dossier** : `docs/reports/` (créé)

**Documentation** : section "Reporting convention (mandatory)" ajoutée dans `CLAUDE.md` (lignes 125-164) avec principe, déclencheurs, naming, structure minimale, règle de garde.

**6 déclencheurs explicites** définis :
1. POC ou script de test exécuté
2. Phase ou étape du plan complétée
3. `pytest` exécuté
4. Migration Alembic appliquée
5. Analyse ou arbitrage produit
6. Blocage ou découverte inattendue en cours d'implémentation

**5 types de rapports** avec naming standardisé :
- `YYYY-MM-DD_poc-<name>.md` (+ `.json` raw, `ensure_ascii=False`)
- `YYYY-MM-DD_phase-<N>-<name>.md`
- `YYYY-MM-DD_tests-<name>.md`
- `YYYY-MM-DD_migration-<name>.md`
- `YYYY-MM-DD_analyse-<name>.md`

**Structure minimale** : Contexte / Résultats / Points d'attention / Décision ou Action suivante.

**Règle de garde** : "En cas de doute : écrire le rapport."

### Rétrofit appliqué

3 POCs déjà exécutés en session ont été rétrofittés (6 fichiers, .md + .json) :
- `2026-05-05_poc-ar-transliteration` — translittération AR, 30/30, Mishkal validé sous réserve GPL
- `2026-05-05_poc-ar-vocalisation-ollama` — option A éliminée
- `2026-05-05_poc-ar-content-quality` — génération directe FR→AR éliminée, EN-first à valider

## Points d'attention

- **Immuabilité** : un rapport daté ne s'écrase jamais. Si un rétrofit ou correction est nécessaire après publication, **créer un nouveau rapport** (par exemple `_v2.md` ou redaté) plutôt que modifier l'existant. Le journal historique a valeur en soi.
- **Risque de glissement** : sans rappels périodiques, la convention pourrait dériver vers "j'écris au chat et je promets de remplir le rapport plus tard". La règle "le fichier doit exister AVANT la fin de la réponse" coupe court à ça — c'est l'intention du wording dans CLAUDE.md.
- **Coût** : ~30s à 2min par rapport selon densité. Acceptable au regard de la valeur (mémoire long terme + lecture asynchrone par l'utilisateur).
- **Auto-application manquée** : ce rapport-ci n'a été créé qu'**après rappel utilisateur**. Première itération de la règle, signale qu'elle n'était pas encore intégrée comme réflexe — le rappel sert d'ancrage. À surveiller sur les prochains déclencheurs.
- **JSON pour POC** : certains POC produisent du JSON naturellement (script ad hoc), d'autres pas (le rapport JSON est alors manuellement structuré depuis les résultats). Pour cohérence future, considérer faire émettre directement le `.json` par le script POC quand c'est faisable.

## Décision / Action suivante

✅ Convention en vigueur **à partir de maintenant** pour tous les déclencheurs listés.

✅ CLAUDE.md à jour, persistera sur sessions futures.

À faire au fil de l'eau (pas de TODO immédiat) :
- Quand un POC est écrit, prévoir un export `.json` natif depuis le script (évite le manuel).
- Si une convention voisine s'avère utile (ex. logs d'exécution longs, transcripts d'erreurs), l'ajouter à CLAUDE.md plutôt que de réinventer ad hoc.

Aucune décision en attente côté utilisateur.
