# Document fonctionnel (vivant) — Artiste Coloriage

> Usage : **personnel** (notes + clarification progressive).  
> Objectif : garder une vue claire du produit, des parcours et des règles métier, sans entrer dans l’implémentation.

## 1) Résumé en 10 lignes

- Le produit permet de **créer et maintenir une taxonomie de thèmes** (ex. animaux, mandalas, véhicules…).
- À partir de cette taxonomie, on **fabrique des concepts d’images** (idées) et on les **organise**.
- On utilise l’IA pour **générer/améliorer/valider des prompts** de génération d’images.
- On lance des **jobs** de génération, on récupère des **outputs** (plusieurs variantes), puis on **sélectionne** le meilleur.
- On suit des **statuts** (concept → prêt → généré → validé → publié, etc.).
- Le produit inclut des écrans d’administration pour : taxonomie, images, jobs, sites.
- On peut **préparer des contenus par site** (langue, audience, organisation, exports).
- But global : un **pipeline éditorial** de bout en bout, de l’idée à l’image prête à publier.

## 2) Glossaire (objets métier)

- **Taxonomie** : structure globale (id, label, langues) + un ou plusieurs vocabulaires.
- **Vocabulaire** : collection de termes (souvent “themes”).
- **Terme** : nœud d’arbre (id, slug, libellés, descriptions, poids/ordre, mots-clés, parent/enfants).
- **Concept image** : une “idée d’image” à produire (titre, brief, statut, tags).
- **Tag taxonomique** : lien entre une image et un terme.
- **Prompt** : consigne textuelle utilisée pour la génération d’image.
- **Job** : tâche asynchrone (génération image, enrichissement texte, export, etc.).
- **Output** : résultat concret d’un job de génération (fichier/image + métadonnées).
- **Site** : cible de publication (langue, règles, taxonomie dérivée, exports).

## 3) Écrans / intentions utilisateur

- **Admin (hub)** : point d’entrée (navigation).
- **Taxonomie** : créer/éditer/chercher des termes ; import/export ; cohérence de l’arbre.
- **Images** : gérer les concepts, prompts, tags, statuts ; lancer des générations ; choisir un output.
- **Jobs** : surveiller, relancer, annuler ; comprendre les échecs ; prioriser.
- **Sites** : définir une cible ; dériver/adapter ; préparer collections/exports.

## 4) Parcours principaux (MVP)

### 4.1 Maintenir la taxonomie

- Créer un terme (racine ou enfant)
- Renommer / enrichir (descriptions, keywords)
- Déplacer (changer de parent) et réordonner (poids)
- Supprimer (avec garde-fous si référencé / enfants)
- Rechercher un terme (id / slug / libellés)
- Importer une taxonomie initiale ; exporter pour sauvegarde

### 4.2 Créer un lot de concepts image

- Partir d’un thème (terme) → générer/collecter des idées
- Nettoyer : doublons, cohérence, niveau de difficulté, style
- Tagger les concepts avec des termes (pour navigation / stats / publication)
- Mettre en file des jobs (prompts puis génération)

### 4.3 Produire des images

- Générer un prompt depuis un concept (ou améliorer un prompt existant)
- Valider la qualité (contraintes “line art”, contenu acceptable, langue, etc.)
- Lancer une génération
- Comparer les outputs et sélectionner celui à retenir
- Éventuellement itérer (nouvelle variante) si le résultat n’est pas satisfaisant

### 4.4 Piloter la production (jobs)

- Voir la file : ce qui tourne / ce qui attend / ce qui a échoué
- Relancer un job échoué (avec correction si nécessaire)
- Annuler si non pertinent
- Éviter les doublons (ne pas lancer 2 fois la même chose sans raison)

### 4.5 Préparer la publication multi-sites

- Définir un site et ses contraintes (langue, ton, thèmes)
- Dériver une taxonomie adaptée (simplification, sélection de branches)
- Organiser en collections et exporter dans le format cible

## 5) Statuts & transitions (à préciser)

### 5.1 Concept image — proposition de chaîne

- **draft** : idée brute
- **prompt_ready** : prompt validé / prêt à générer
- **scheduled** : en attente (job créé)
- **generating** : génération en cours
- **generated** : outputs disponibles
- **approved** : output choisi + validation éditoriale
- **published** : exporté/publié (ou prêt à l’être)

Notes / règles (à compléter) :
- Quand passe-t-on à *approved* ?
- Est-ce qu’un concept peut redevenir *draft* ?

### 5.2 Job — intentions

- **pending / running / failed / completed**
- Règles d’exclusivité : “un job de génération actif par image” (à confirmer)

## 6) Règles métier & garde-fous (liste initiale)

- **Cohérence taxonomie** : un terme a un id stable ; pas de parent manquant ; ordre déterministe.
- **Suppression** : refuser si le terme est référencé (images/collections/stats), sauf mode “cascade” explicitement choisi.
- **Qualité prompts** : respecter le style “coloriage line art”, éviter contenus interdits, garder un niveau de détail adapté.
- **Traçabilité minimale** : savoir pourquoi un job a été relancé / annulé (notes perso).

## 7) Indicateurs utiles (pour piloter)

- Couverture : nb d’images par terme / branche
- Taux d’échec des jobs (par type)
- Temps moyen de génération
- % d’outputs rejetés vs retenus

## 8) Checklist “mise en route” (environnement)

- [ ] Base initialisée
- [ ] Taxonomie importée
- [ ] Éditeur taxonomie accessible
- [ ] Génération test : 1 concept → 1 job → 1 output

## 9) Backlog perso (à alimenter)

- [ ] Clarifier “définition de done” d’une image *approved*
- [ ] Règles de dérivation de taxonomie par site (méthode + critères)
- [ ] Stratégie anti-doublons (concepts et jobs)
- [ ] Templates de prompts : versioning et tests de non-régression
- [ ] “Qualité” : grille de validation simple (score + raisons)

## 10) Notes / décisions (journal)

> Ajouter ici les décisions prises, avec date, contexte et impact.

- 2026-..-.. — …

