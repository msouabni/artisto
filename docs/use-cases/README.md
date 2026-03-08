# Référentiel de use cases – Artiste Coloriage

Ce dossier contient le **référentiel des cas d’usage** du projet Artiste Coloriage.  
L’objectif est de :

- centraliser les besoins fonctionnels,
- les classer par **domaine** et par **phase** du plan,
- suivre l’**avancement** et préparer les **évolutions**.

---

## Fichier maître : `use_cases.yaml`

- Emplacement : `docs/use-cases/use_cases.yaml`
- Structure générale :

```yaml
domains:
  - id: taxonomy
    label: "Taxonomie universelle et dérivées"
    use_cases:
      - id: TAXO_CREATE_UNIVERSAL
        title: "Créer et maintenir la taxonomie universelle v0 FR/EN/AR"
        phase: 1
        actors: ["admin_plateforme"]
        status: planned   # planned | in_progress | done | deprecated
        description: "Définir la hiérarchie des thèmes universels et la maintenir."
        related_files:
          - "data/taxonomy_universal_v0.json"
          - "data/taxonomy_editor.html"
          - "src/taxonomy.py"
        related_taxonomy_terms:
          - "animaux"
          - "mandalas"
        notes: "Basé sur le plan de taxonomie v0 exhaustive."
```

### Champs d’un use case

- `id` : identifiant stable (UPPER_SNAKE_CASE).
- `title` : titre court lisible.
- `phase` : phase principale du plan (`0` à `6`) où le use case est traité.
- `actors` : rôles impliqués (ex. `admin_plateforme`, `visiteur_site`, `agent_systeme`).
- `status` : état d’avancement : `planned`, `in_progress`, `done`, `deprecated`.
- `description` : description fonctionnelle courte.
- `related_files` : fichiers principaux (specs, code, docs) qui implémentent ce use case.
- `related_taxonomy_terms` (optionnel) : ids de termes importants de la taxonomie liés au use case.
- `notes` : remarques complémentaires.

---

## Éditeur visuel

Un éditeur HTML permet de visualiser et modifier `use_cases.yaml` sous forme de tableau :

1. Ouvrir `use_cases_editor.html` dans un navigateur (double-clic ou via un serveur local).
2. Cliquer sur **Charger un YAML** et sélectionner `use_cases.yaml`.
3. Modifier les cellules (double-clic pour éditer).
4. Cliquer sur **Enregistrer (télécharger)** pour télécharger le YAML modifié.

Le fichier téléchargé doit remplacer manuellement le fichier source si vous souhaitez conserver les modifications.

**Convention du projet** : tout livrable YAML ou JSON doit être accompagné d’un éditeur visuel de ce type (voir règle `.cursor/rules/editors-yaml-json.mdc`).

---

## Domaines actuels

Les domaines sont alignés avec l’architecture et le plan de phases :

- **taxonomy** : taxonomie universelle et taxonomies de sortie.
- **generation** : génération de concepts, prompts et images.
- **postprocess** : nettoyage / amélioration des images (line art).
- **export** : création de collections, dossiers, PDF, exports vers sites.
- **monitoring** : suivi des jobs, de la qualité, de la couverture taxonomique, de la publication par site.
- **agent** : cas d’usage liés au pilotage par un agent (proposition de thèmes, orchestration du pipeline, suggestions de nouvelles branches de taxonomie).
- **sites** : gestion du portefeuille de sites (initialisation, mises à jour, adaptation locale).

---

## Suivi de l’avancement

- Un use case est :
  - `planned` : défini fonctionnellement mais pas encore implémenté.
  - `in_progress` : en cours d’implémentation (branche de travail en cours).
  - `done` : implémenté et testé au niveau requis pour le projet.
  - `deprecated` : obsolète ou remplacé par un autre use case.

### Processus recommandé

1. Toute **nouvelle fonctionnalité** ou évolution commence par :
   - créer un nouveau use case dans `use_cases.yaml`, ou
   - mettre à jour un use case existant (description, phase, fichiers liés).
2. Avant de modifier la taxonomie, le pipeline ou l’architecture, identifier les **use cases impactés** via les champs `domains` et `related_files`.
3. Pour les futurs sites, ajouter des use cases dans le domaine `sites` (init, sync, adaptation locale) qui réutilisent les mêmes briques (taxonomie, génération, export).
4. **Convention du projet** : lors de l'implémentation d'un use case, mettre à jour son `status` et ses `related_files` dans use_cases.yaml (voir règle `.cursor/rules/use-cases-update.mdc`).

---

## Utilisation pour la planification

- Le référentiel de use cases sert de **grille de lecture** pour prioriser les travaux :
  - ex. viser d’abord les use cases `generation` et `postprocess` critiques pour une première livraison.
- Il facilitera aussi le lien avec les **tests** (unitaires, intégration) en associant chaque test à un ou plusieurs use cases.

