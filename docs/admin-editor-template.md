# Template éditeur administration – Artiste Coloriage

Ce document décrit le **pattern d’éditeur** utilisé pour les pages d’administration du projet. L’éditeur taxonomie (`data/taxonomy_editor.html`) en est l’implémentation de référence.

## 1. Structure type

```
┌─────────────────────────────────────────────────────────────┐
│ Header : titre                                               │
├─────────────────────────────────────────────────────────────┤
│ Meta-bar : métadonnées (ID, label, vocabulaires)             │
├─────────────────────────────────────────────────────────────┤
│ Barre d'actions : Charger, Enregistrer, Undo, Redo, Export,  │
│   Ajouter, Config (thème, colonnes visibles, auto-save,      │
│   supprimer sélection), filtre, indicateur autosave, statut │
├─────────────────────────────────────────────────────────────┤
│ Main panel (pleine largeur)                                  │
│ ┌───────────────────────────────────────────────────────────┐
│ │ Tableau Tabulator : colonne sélection (gelée), colonnes   │
│ │ données, colonne Actions (Edit / Del / Dup) gelée          │
│ │ Édition inline au double-clic uniquement                   │
│ └───────────────────────────────────────────────────────────┘
├─────────────────────────────────────────────────────────────┤
│ Panneau formulaire (latéral, optionnel) : s'ouvre au clic    │
│   sur Edit ; formulaire terme + Enregistrer / Annuler        │
└─────────────────────────────────────────────────────────────┘
```

## 2. Fonctionnalités communes

| Fonctionnalité | Description | Clé localStorage |
|----------------|-------------|-------------------|
| Thème clair/sombre | Bascule visuelle | `{prefix}_theme` |
| Colonnes visibles | Sélecteur de colonnes | `{prefix}_columns` |
| Recherche | Filtre global sur la grille | - |
| Chargement API | Fetch depuis l’API | - |
| Chargement fichier | Fallback fichier local | - |
| Auto-save | Sauvegarde automatique après modification | `{prefix}_autosave` |

**Préfixe** : par éditeur (ex. `taxonomy_editor_`, `sites_editor_`).

## 3. Synchronisation (auto-save vs manuel)

### Mode Auto-save (activé)

- Après chaque modification (cellule, ajout, suppression), une sauvegarde est planifiée avec **debounce 600 ms**.
- Évite les requêtes multiples lors d’éditions rapides.
- L’utilisateur n’a pas besoin de cliquer sur « Enregistrer ».

### Mode manuel (désactivé)

- Aucune sauvegarde automatique.
- **Indicateur de modifications non sauvegardées** :
  - Point coloré + texte « Modifications non enregistrées » dans la zone de statut.
  - Bouton « Enregistrer » mis en évidence (bordure ou accent).
  - Optionnel : préfixe « ● » dans le titre de page.
- **Avertissement avant fermeture** : `beforeunload` si des modifications sont en attente.

### Toggle Auto-save

- Dans **Config** (menu au-dessus du tableau) : case « Activer l'auto-save ».
- Valeur par défaut : `false` (mode manuel) pour limiter les écritures involontaires.
- **Indicateur visuel** : spinner ou texte « Enregistrement… » affiché pendant les requêtes PUT d'auto-save.

## 4. Conventions techniques

### API_BASE

- Même origine si servi par FastAPI : `''`
- En `file://` : `'http://localhost:8000'` pour pointer vers l’API.

### Événements à écouter

- **cellEdited** : modification d’une cellule.
- **rowAdded** : ajout de ligne (Tabulator ou handler custom).
- **rowDeleted** : suppression de ligne.

### Éditeur taxonomie : API atomique (pas de PUT global)

- **Grille Tabulator** : mode arbre (`dataTree`), **première colonne** gelée = sélection des lignes, **dernière colonne** gelée = boutons d’actions (Edit, Delete, Duplicate). Édition des cellules au **double-clic uniquement** (`editTriggerEvent: 'dblclick'`).
- **Barre d’actions** au-dessus du tableau : Charger, Enregistrer, Undo, Redo, Export, Ajouter un terme, **Config** (thème, colonnes visibles, auto-save, supprimer la sélection), filtre, indicateur « Enregistrement… », statut.
- **Panneau formulaire** latéral : s’ouvre au clic sur **Edit** dans la colonne Actions ; formulaire complet (id, slug, name_*, weight, description_*, keywords) ; Enregistrer → PUT puis fermeture ; Annuler / Fermer sans sauvegarder.
- **Undo / Redo** : piles d’opérations (cellEdit, add, delete) ; Undo/Redo appellent l’API inverse puis rafraîchissent la grille.
- **cellEdited** : enregistre l’opération pour Undo, déclenche un PUT du terme (debounce 500 ms en auto-save) ou ajoute l’id à la liste des modifiés pour Enregistrer.
- **Enregistrer** : PUT par terme modifié, puis réinitialisation de l’indicateur.
- **Ajout / Suppression / Duplication** : POST ou DELETE puis rechargement des termes ; chaque action est enregistrée pour Undo.

## 5. Réutilisation pour un nouvel éditeur

Pour créer une nouvelle page d’administration (ex. sites, use cases) :

1. **Préfixe localStorage** : `sites_editor_theme`, `sites_editor_autosave`, etc.
2. **Endpoint API** : ex. `GET/PUT /api/sites`.
3. **buildPayload()** : fonction qui construit le body du PUT à partir des données de la grille.
4. **Événements** : brancher `cellEdited`, et les handlers d’ajout/suppression de lignes sur `onDataChanged` ou équivalent.
5. **Structure HTML/CSS** : reprendre header, meta-bar, barre d’actions (dont Config), main panel pleine largeur, panneau formulaire latéral si besoin.

## 6. Référence

- **Implémentation** : [data/taxonomy_editor.html](../data/taxonomy_editor.html)
- **Documentation taxonomie** : [docs/taxonomy_universal_v0.md](taxonomy_universal_v0.md)
- **UI Gestion taxonomies** : interface principale **éditeur tabulaire** [data/taxonomy_editor.html](../data/taxonomy_editor.html) (Tabulator + API atomique) ; alternative master-detail [data/taxonomy_manage.html](../data/taxonomy_manage.html). Doc : [ui-taxonomy-manage.md](ui-taxonomy-manage.md).
