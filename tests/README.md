# Tests Artiste Coloriage

## Lancer les tests

Depuis la **racine du projet** :

```bash
python -m pytest tests/ -v
```

`pytest.ini` configure `pythonpath = src` pour que les imports `api.*` fonctionnent.

## Contenu

- **test_taxonomy_api.py** : API taxonomie
  - Robustesse aux champs NULL en base (ex. `weight` NULL) : tri, réponses GET
  - À étendre pour d'autres endpoints et cas limites

## En cas d'erreur 500 (API)

Pour diagnostiquer une 500 renvoyée par l'API (ex. GET terms) : (1) **Corps de la réponse** : DevTools → Network → requête en erreur → onglet Response/Preview ; FastAPI renvoie `{"detail": "..."}`. (2) **Barre de statut** : l'éditeur taxonomie affiche ce détail en bas. (3) **Logs serveur** : lancer l'API en terminal et consulter la traceback.

## Règle projet

Voir `.cursor/rules/null-safe-db-api.mdc` : champs NULL normalisés ; valeurs en réponse en types JSON-serialisables ; couvert par un test.
