# UI Gestion des taxonomies

Interface de gestion des taxonomies (vocabulaires et termes en arbre), conçue selon le plan « UI taxonomies page blanche, bonnes pratiques ». Une action = une requête API (pas de sauvegarde globale).

## Interface principale recommandée : éditeur tabulaire (Tabulator)

- **URL** : `http://127.0.0.1:8000/data/taxonomy_editor.html` (ou ouverture locale du fichier)
- **Fichier** : [data/taxonomy_editor.html](../data/taxonomy_editor.html)
- **Affichage** : grille Tabulator en mode arbre (expand/collapse), **première colonne gelée** = sélection des lignes, **dernière colonne gelée** = Actions (Edit, Delete, Duplicate). **Édition des cellules au double-clic uniquement.** Sauvegarde atomique (PUT/POST/DELETE par terme). Sélecteur de vocabulaire si plusieurs vocabulaires.
- **Barre d’actions** au-dessus du tableau : Charger, Enregistrer, Undo, Redo, Export, Ajouter un terme, **Config** (thème, colonnes visibles, auto-save, supprimer la sélection), filtre, indicateur « Enregistrement… », statut.
- **Panneau formulaire** latéral : ouvert par le bouton **Edit** d’une ligne ; formulaire complet du terme ; Enregistrer / Annuler.
- **Undo / Redo** : historique des opérations (édition cellule, ajout, suppression) ; annulation et rejeu via l’API.

## Alternative : master-detail (arbre + formulaire)

- **URL** : `http://127.0.0.1:8000/data/taxonomy_manage.html`
- **Fichier** : [data/taxonomy_manage.html](../data/taxonomy_manage.html)

## Architecture de l’écran (éditeur tabulaire)

| Zone | Contenu |
|------|--------|
| **Header** | Titre « Éditeur Taxonomie universelle v0 ». |
| **Meta-bar** | ID taxonomie, label, langues, sélecteur de vocabulaire si plusieurs. |
| **Barre d’actions** | Charger, Enregistrer, Undo, Redo, Export JSON, Ajouter un terme, **Config** (thème, colonnes visibles, auto-save, supprimer la sélection), filtre recherche, indicateur autosave, indicateur « non enregistré », statut. |
| **Tableau** | Colonne sélection (gelée), colonnes données (id, slug, name_*, weight, description_*, keywords), colonne Actions (Edit, Del, Dup) gelée. Scroll vertical et horizontal. Header du tableau fixe. |
| **Panneau formulaire** | Panneau latéral droit ; ouvert par **Edit** ; formulaire (id, slug, name_*, weight, description_*, keywords) ; Enregistrer / Annuler. |

## Parcours utilisateur (éditeur tabulaire)

1. **Consulter** : Ouverture de la page → chargement GET `/api/taxonomy` → affichage de l’arbre du premier vocabulaire. Double-clic sur une cellule pour éditer inline ; clic sur **Edit** pour ouvrir le formulaire latéral.
2. **Modifier (inline)** : Double-clic sur une cellule → édition → blur ou Entrée → PUT du terme (auto-save si activé) ou marquage « non enregistré ». Indicateur « Enregistrement… » pendant le PUT.
3. **Modifier (formulaire)** : Clic **Edit** → panneau formulaire ouvert, champs pré-remplis → modification → **Enregistrer** → PUT puis fermeture du panneau et rafraîchissement.
4. **Créer** : **Ajouter un terme** → POST (enfant du terme sélectionné ou racine) → arbre rechargé. Undo annule la création (DELETE).
5. **Supprimer** : Clic **Del** sur une ligne ou sélection multiple + **Config** → **Supprimer la sélection** → DELETE. Si 409 (référencé ou enfants), message d’erreur affiché.
6. **Dupliquer** : Clic **Dup** sur une ligne → POST d’une copie (nouvel id) → arbre rechargé. Undo supprime le terme dupliqué.
7. **Undo / Redo** : Boutons dans la barre d’actions ; annulation ou rejeu de la dernière opération (édition cellule, ajout, suppression).
8. **Recherche** : Champ filtre dans la barre d’actions ; filtre côté client sur les colonnes visibles.

## Endpoints API utilisés

| Méthode | Endpoint | Usage |
|---------|----------|--------|
| GET | `/api/taxonomy` | Chargement initial (métadonnées + vocabulaires). |
| GET | `/api/taxonomy/vocabularies/{vid}/terms` | Arbre des termes d’un vocabulaire. |
| GET | `/api/taxonomy/vocabularies/{vid}/terms/{tid}` | Détail d’un terme (descriptions, keywords). |
| PUT | `/api/taxonomy/vocabularies/{vid}/terms/{tid}` | Mise à jour d’un terme (upsert). |
| POST | `/api/taxonomy/vocabularies/{vid}/terms` | Création d’un terme (ex. enfant). |
| DELETE | `/api/taxonomy/vocabularies/{vid}/terms/{tid}` | Suppression (409 si référencé ou a des enfants). |
| GET | `/api/taxonomy/terms/search?q=...&vocabulary_id=...` | Recherche pour l’onglet Recherche. |

## Comportements

- **Avertissement avant sortie** : si le formulaire a été modifié sans enregistrement, `beforeunload` demande confirmation.
- **Suppression** : modal de confirmation ; en cas de 409, le détail (références ou nombre d’enfants) est affiché dans la modal.
- **Responsive** : sur petit écran, la zone master est au-dessus, le détail en dessous ; onglets Arbre / Recherche pour basculer le contenu du master.

## Références

- Plan : « UI taxonomies page blanche, bonnes pratiques »
- Template admin : [admin-editor-template.md](admin-editor-template.md)
- Schéma et API : [data/schema.sql](../data/schema.sql), [src/api/routes/taxonomy.py](../src/api/routes/taxonomy.py)
