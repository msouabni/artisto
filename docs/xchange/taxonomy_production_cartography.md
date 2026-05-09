# Cartographie de production — Taxonomie Alwan Books

**Version** : 1.0
**Basée sur** : checklist v2.2
**Statut** : Validé empiriquement sur 14 phases de tests + 14 cas d'échantillon production (moyenne 8.5/10)

---

## Configuration de production par défaut

- **Workflow** : `WF_baseline (ERNIE-Image-Turbo Q8 GGUF + flux2-vae + ministral-3-3b, euler/normal, 8 steps, CFG 1.0)`
- **Negative prompt v3** :

```
no colors, extra legs, third leg, duplicate limbs, fused legs, malformed anatomy, wrong number of limbs, six fingers, deformed feet no motion, no fill colors, no intersection, no change in ink transparency for different plan only black stroke
```

---

## Statistiques globales

- **18** catégories racines
- **145** sous-catégories
- **1376** feuilles au total

### Distribution par niveau de confiance

| Confiance | Nombre |
|---|---|
| Haute | 93 |
| Moyenne | 44 |
| Mixte | 2 |
| Haute (pour SVG) | 2 |
| Faible | 1 |
| Haute (avec hybride) | 1 |
| Haute (un par un) | 1 |
| Haute (avec règles) | 1 |

---

## Comment lire ce document

Pour chaque sous-catégorie, vous trouverez :

- **Classe** : type de prompt selon la checklist v2.2 (Solo, Humain+entité, Multi-sujets, etc.)
- **Technique** : pattern de composition à appliquer
- **Résolution** : 1024×1024, 848×1264 (portrait), ou 1376×768 (panoramique)
- **Pipeline** : ERNIE direct, hybride avec SVG, ou composition PIL post-traitement
- **Confiance** : Haute / Moyenne / Faible — basée sur les tests empiriques
- **Pièges** : risques connus pour cette catégorie
- **Negative additionnel** : compléments au negative v3 standard
- **Notes** : observations éditoriales

---

## Animals — Animaux

**ID** : `animals`
**Sous-catégories** : 11
**Feuilles** : 136

### Pet Animals — Animaux domestiques

- **ID** : `pet_animals`
- **Feuilles** : 15
- **Classe** : Solo animal
- **Technique** : Solo classique en profil + décor minimal
- **Résolution** : `1024x1024`
- **Pipeline** : ERNIE direct
- **Confiance** : Haute
- **Pièges** :
  - Vue frontale risquée pour chats/chiens — préférer profil ou trois-quarts
- **Notes** : Phase A1 validée (lion). Animaux domestiques très représentés dans datasets.

### Farm Animals — Animaux de la ferme

- **ID** : `farm_animals`
- **Feuilles** : 12
- **Classe** : Solo animal
- **Technique** : Solo classique avec décor de ferme simple
- **Résolution** : `1024x1024`
- **Pipeline** : ERNIE direct
- **Confiance** : Haute
- **Pièges** :
  - Préciser 'four legs visible on the ground' pour les ongulés
- **Notes** : Validé Phase A (farm horse). Peut nécessiter pose statique pour anatomie correcte.

### African Wild Animals — Animaux sauvages d'Afrique

- **ID** : `african_wild_animals`
- **Feuilles** : 13
- **Classe** : Solo animal
- **Technique** : Solo en profil + savane/jungle silhouette en arrière-plan
- **Résolution** : `1024x1024`
- **Pipeline** : ERNIE direct
- **Confiance** : Haute
- **Pièges** :
  - Acacia tree à préciser 'fully visible' (Insight A)
- **Notes** : Validé sur lion. Éléphant, girafe, zèbre devraient suivre.

### Asian Wild Animals — Animaux sauvages d'Asie

- **ID** : `asian_wild_animals`
- **Feuilles** : 10
- **Classe** : Solo animal
- **Technique** : Solo en profil + bambou/montagne stylisée
- **Résolution** : `1024x1024`
- **Pipeline** : ERNIE direct
- **Confiance** : Haute
- **Pièges** :
  - Panda risque de fusion noir/blanc — bien définir les zones par contour
- **Notes** : Animaux asiatiques bien représentés (bias dataset Baidu).

### American Wild Animals — Animaux sauvages d'Amérique

- **ID** : `american_wild_animals`
- **Feuilles** : 12
- **Classe** : Solo animal
- **Technique** : Solo en profil + paysage américain stylisé
- **Résolution** : `1024x1024`
- **Pipeline** : ERNIE direct
- **Confiance** : Haute
- **Notes** : Sujets standards, faible risque.

### Arctic Animals — Animaux de l'Arctique

- **ID** : `arctic_animals`
- **Feuilles** : 9
- **Classe** : Solo animal
- **Technique** : Solo + paysage glacé minimaliste
- **Résolution** : `1024x1024`
- **Pipeline** : ERNIE direct
- **Confiance** : Haute
- **Pièges** :
  - Pingouins en groupe : utiliser formule procession §6.4
- **Notes** : Iceberg/glace à préciser 'fully visible' (Insight A).

### Marine Animals — Animaux marins

- **ID** : `marine_animals`
- **Feuilles** : 15
- **Classe** : Solo animal
- **Technique** : Solo en eau + bulles ou plantes marines simples
- **Résolution** : `1024x1024`
- **Pipeline** : ERNIE direct
- **Confiance** : Haute
- **Pièges** :
  - Requin de face risqué — préférer profil
- **Notes** : Validé sur monarch butterfly principe similaire (corps + ailes/nageoires symétriques).

### Insects and Minibeasts — Insectes et petites bêtes

- **ID** : `insects_and_minibeasts`
- **Feuilles** : 12
- **Classe** : Solo animal
- **Technique** : Solo + élément botanique simple (feuille, fleur)
- **Résolution** : `1024x1024`
- **Pipeline** : ERNIE direct
- **Confiance** : Haute
- **Pièges** :
  - Préciser nombre exact de pattes : 6 pour insectes, 8 pour araignées
- **Notes** : Symétrie volontaire OK pour papillons/coccinelles (Z6 perfect).

### Birds — Oiseaux

- **ID** : `birds`
- **Feuilles** : 14
- **Classe** : Solo animal
- **Technique** : Solo + posture explicite (Insight D critique)
- **Résolution** : `1024x1024`
- **Pipeline** : ERNIE direct
- **Confiance** : Moyenne
- **Pièges** :
  - Insight D : oiseau en vol DOIT préciser 'flying with wings spread open and body horizontal in flight pose'
  - Sinon retour à pose de repos par défaut (oiseau debout)
- **Negative additionnel** : `bird standing in air, vertical flying body`
- **Notes** : Cas 15 a montré le bug 'oiseau debout dans le ciel'. Vigilance forte.

### Dinosaurs and Prehistoric Animals — Dinosaures et préhistoire

- **ID** : `dinosaurs_and_prehistoric`
- **Feuilles** : 12
- **Classe** : Solo animal
- **Technique** : Solo en profil + paysage préhistorique stylisé
- **Résolution** : `1024x1024`
- **Pipeline** : ERNIE direct
- **Confiance** : Moyenne
- **Pièges** :
  - T-Rex : préciser 'two short arms' pour éviter membres en trop
- **Notes** : Anatomie spécifique. Validation cas par cas recommandée.

### Fantasy Animals — Animaux fantastiques

- **ID** : `fantasy_animals`
- **Feuilles** : 12
- **Classe** : Solo animal
- **Technique** : Solo en pose épique + éléments fantastiques
- **Résolution** : `1024x1024`
- **Pipeline** : ERNIE direct
- **Confiance** : Haute
- **Pièges** :
  - Dragon : version kid-friendly, pas effrayant
- **Negative additionnel** : `scary, menacing, sharp teeth visible`
- **Notes** : Animaux fantastiques très représentés. Adapter pour audience enfants 3-12.

---

## Fictional Characters — Personnages fictifs

**ID** : `fictional_characters`
**Sous-catégories** : 9
**Feuilles** : 114

### Disney Universe — Univers Disney

- **ID** : `disney_universe`
- **Feuilles** : 15
- **Classe** : Solo humain (personnalité)
- **Technique** : Personnage nommé OU version générique (cf. risque IP §4.2)
- **Résolution** : `1024x1024`
- **Pipeline** : ERNIE direct (test) / Production version générique
- **Confiance** : Haute (pour test), Moyenne (commercial)
- **Pièges** :
  - IP risk : production version générique pour usage commercial
- **Negative additionnel** : `scary, dark expression`
- **Notes** : Phase F validée que les versions A nommées sont reconnaissables. ATTENTION IP en commercial.

### Pixar Universe — Univers Pixar

- **ID** : `pixar_universe`
- **Feuilles** : 13
- **Classe** : Solo humain ou objet
- **Technique** : Idem Disney (IP risk identique)
- **Résolution** : `1024x1024`
- **Pipeline** : ERNIE direct (test) / Production version générique
- **Confiance** : Moyenne
- **Pièges** :
  - IP risk fort, surtout characters récents (Lightning McQueen)
- **Notes** : Privilégier versions génériques pour production commerciale.

### Marvel Universe — Univers Marvel

- **ID** : `marvel_universe`
- **Feuilles** : 13
- **Classe** : Solo humain (personnalité)
- **Technique** : Personnage nommé en pose héroïque + accessoire signature
- **Résolution** : `848x1264`
- **Pipeline** : ERNIE direct (test) / Production version générique
- **Confiance** : Moyenne
- **Pièges** :
  - IP risk Disney+Marvel
- **Negative additionnel** : `scary, dark expression, blood, weapons`
- **Notes** : Format portrait pour mettre en valeur la pose héroïque verticale.

### DC Universe — Univers DC

- **ID** : `dc_universe`
- **Feuilles** : 10
- **Classe** : Solo humain (personnalité)
- **Technique** : Idem Marvel
- **Résolution** : `848x1264`
- **Pipeline** : ERNIE direct (test) / Production version générique
- **Confiance** : Moyenne
- **Pièges** :
  - IP risk Warner Bros
- **Negative additionnel** : `scary, dark expression, blood, weapons`
- **Notes** : Idem Marvel.

### Popular Anime — Anime populaires

- **ID** : `popular_anime`
- **Feuilles** : 15
- **Classe** : Solo humain ou créature
- **Technique** : Personnage nommé style anime simplifié
- **Résolution** : `1024x1024`
- **Pipeline** : ERNIE direct (test) / Production version générique
- **Confiance** : Moyenne
- **Pièges** :
  - IP risk Pokemon/Naruto/etc.
- **Notes** : Pikachu et co fortement représentés dans datasets — bonne reconnaissance.

### Classic Cartoons — Cartoons classiques

- **ID** : `classic_cartoons`
- **Feuilles** : 11
- **Classe** : Solo humain/animal cartoon
- **Technique** : Personnage en pose iconique
- **Résolution** : `1024x1024`
- **Pipeline** : ERNIE direct
- **Confiance** : Haute
- **Pièges** :
  - IP variable selon âge des personnages
- **Notes** : Bugs Bunny, Tweety très représentés.

### Modern Cartoons — Cartoons modernes

- **ID** : `modern_cartoons`
- **Feuilles** : 13
- **Classe** : Solo humain/animal cartoon
- **Technique** : Personnage en pose iconique
- **Résolution** : `1024x1024`
- **Pipeline** : ERNIE direct (test) / Production version générique
- **Confiance** : Moyenne
- **Pièges** :
  - IP risk fort (Bluey, Miraculous)
- **Notes** : Productions récentes, IP active.

### Video Game Characters — Personnages de jeux vidéo

- **ID** : `video_games`
- **Feuilles** : 15
- **Classe** : Solo humain (personnalité)
- **Technique** : Personnage nommé en pose iconique
- **Résolution** : `1024x1024`
- **Pipeline** : ERNIE direct (test) / Production version générique
- **Confiance** : Moyenne
- **Pièges** :
  - IP risk Nintendo/Sony/etc.
- **Notes** : Mario et co très représentés. Mais IP forte.

### Original Superheroes — Super-héros originaux

- **ID** : `original_superheroes`
- **Feuilles** : 9
- **Classe** : Solo humain (générique)
- **Technique** : Super-héros générique sans IP
- **Résolution** : `848x1264`
- **Pipeline** : ERNIE direct
- **Confiance** : Haute
- **Negative additionnel** : `scary, dark, weapons`
- **Notes** : Aucun IP risk. Catégorie sûre.

---

## Sports Personalities — Personnalités sportives

**ID** : `sports_personalities`
**Sous-catégories** : 8
**Feuilles** : 64

### Football Stars — Stars du football

- **ID** : `football_stars`
- **Feuilles** : 10
- **Classe** : Solo humain (personnalité) + action figée
- **Technique** : Personnage nommé en mid-action (Z7 perfect)
- **Résolution** : `848x1264`
- **Pipeline** : ERNIE direct
- **Confiance** : Haute
- **Pièges** :
  - Pose dynamique → risque membres en trop. Énumérer les bras.
- **Negative additionnel** : `extra arm, third arm`
- **Notes** : Validé cas 14 Messi = perfect. Pattern reproductible pour tous les joueurs.

### Basketball Stars — Stars du basketball

- **ID** : `basketball_stars`
- **Feuilles** : 9
- **Classe** : Solo humain (personnalité) + action figée
- **Technique** : Personnage nommé en mid-action (dunk, shoot, dribble)
- **Résolution** : `848x1264`
- **Pipeline** : ERNIE direct
- **Confiance** : Haute
- **Pièges** :
  - Idem football
- **Negative additionnel** : `extra arm, third arm`
- **Notes** : Reproduire pattern Messi sur LeBron, Curry, etc.

### Tennis Stars — Stars du tennis

- **ID** : `tennis_stars`
- **Feuilles** : 9
- **Classe** : Solo humain (personnalité) + action figée
- **Technique** : Personnage nommé avec raquette en service ou frappe
- **Résolution** : `848x1264`
- **Pipeline** : ERNIE direct
- **Confiance** : Haute
- **Negative additionnel** : `extra arm, third arm`
- **Notes** : Pattern stable.

### Olympic Athletes — Athlètes olympiques

- **ID** : `olympic_athletes`
- **Feuilles** : 8
- **Classe** : Solo humain (personnalité) + action figée
- **Technique** : Personnage nommé selon discipline
- **Résolution** : `848x1264`
- **Pipeline** : ERNIE direct
- **Confiance** : Moyenne
- **Pièges** :
  - Gymnastique : poses très complexes, tester chaque cas
- **Negative additionnel** : `extra arm, third arm, extra leg`
- **Notes** : Variabilité selon discipline. Sprint OK, gymnastique à valider.

### Boxing and Martial Arts Stars — Stars de la boxe et arts martiaux

- **ID** : `boxing_martial_arts_stars`
- **Feuilles** : 7
- **Classe** : Solo humain (personnalité) + action figée
- **Technique** : Personnage nommé en pose de combat
- **Résolution** : `848x1264`
- **Pipeline** : ERNIE direct
- **Confiance** : Moyenne
- **Pièges** :
  - Adapter pour audience enfants 3-12
- **Negative additionnel** : `scary, blood, violence`
- **Notes** : Tonalité : focus sur la pose technique, pas le combat agressif.

### Cycling Stars — Stars du cyclisme

- **ID** : `cycling_stars`
- **Feuilles** : 6
- **Classe** : Solo humain (personnalité) sur vélo
- **Technique** : Personnage nommé sur vélo en course
- **Résolution** : `1376x768`
- **Pipeline** : ERNIE direct
- **Confiance** : Moyenne
- **Pièges** :
  - Interaction main-guidon : préférer 'riding it' à 'holding handlebars' (cf. C3)
- **Notes** : Format panoramique pour le mouvement horizontal.

### Winter Sports Stars — Stars des sports d'hiver

- **ID** : `winter_sports_stars`
- **Feuilles** : 6
- **Classe** : Solo humain (personnalité) en action
- **Technique** : Personnage nommé sur skis/snowboard en mouvement
- **Résolution** : `848x1264`
- **Pipeline** : ERNIE direct
- **Confiance** : Moyenne
- **Pièges** :
  - Posture explicite (Insight D) — pas de skieur 'debout dans la pente'
- **Notes** : Posture du corps en descente à expliciter.

### National Teams and Iconic Clubs — Équipes nationales et clubs emblématiques

- **ID** : `national_teams_and_clubs`
- **Feuilles** : 9
- **Classe** : Multi-sujets ou Scène
- **Technique** : Frise 1×N (pas panoramique partagé — anti-pattern Z5b)
- **Résolution** : `1376x768`
- **Pipeline** : ERNIE direct (test) / Production simplifiée
- **Confiance** : Faible
- **Pièges** :
  - IP risk logos clubs
- **Notes** : Logos officiels = IP. Privilégier scènes sans logos identifiables.

---

## Sports and Physical Activities — Sports et activités physiques

**ID** : `sports_and_physical_activities`
**Sous-catégories** : 10
**Feuilles** : 86

### Team Sports — Sports collectifs

- **ID** : `team_sports`
- **Feuilles** : 11
- **Classe** : Multi-sujets ou Scène d'action
- **Technique** : Action figée du moment-clé (Z7) en cadrage panoramique
- **Résolution** : `1376x768`
- **Pipeline** : ERNIE direct
- **Confiance** : Moyenne
- **Pièges** :
  - 4+ joueurs dans même scène : utiliser frise 1×N (anti-pattern Z5b)
- **Negative additionnel** : `extra arm, third arm, extra leg`
- **Notes** : Préférer 1-3 joueurs dans la scène, ou frise.

### Individual Sports — Sports individuels

- **ID** : `individual_sports`
- **Feuilles** : 12
- **Classe** : Solo humain en action
- **Technique** : Solo + pose dynamique (Z7)
- **Résolution** : `848x1264`
- **Pipeline** : ERNIE direct
- **Confiance** : Haute
- **Pièges** :
  - Posture explicite obligatoire (Insight D)
- **Negative additionnel** : `extra arm, third arm, extra leg`
- **Notes** : Une feuille = un sportif générique = un mouvement précis.

### Winter Sports Activities — Sports d'hiver

- **ID** : `winter_sports_activities`
- **Feuilles** : 9
- **Classe** : Solo humain en action
- **Technique** : Idem individual_sports + paysage neige
- **Résolution** : `848x1264`
- **Pipeline** : ERNIE direct
- **Confiance** : Haute
- **Notes** : Paysage neige minimaliste.

### Water Sports — Sports nautiques

- **ID** : `water_sports`
- **Feuilles** : 10
- **Classe** : Solo humain en action
- **Technique** : Idem + horizon mer (P3 validé)
- **Résolution** : `1376x768`
- **Pipeline** : ERNIE direct
- **Confiance** : Haute
- **Pièges** :
  - Horizon mer comme séparation 2 plans naturelle
- **Notes** : Pattern P3 réutilisable.

### Extreme Sports — Sports extrêmes

- **ID** : `extreme_sports`
- **Feuilles** : 9
- **Classe** : Solo humain en action
- **Technique** : Action figée + motion lines (Z7)
- **Résolution** : `848x1264`
- **Pipeline** : ERNIE direct
- **Confiance** : Haute
- **Pièges** :
  - Posture aérienne explicite (Insight D)
- **Notes** : Sports aériens (BMX, parachute) : posture critique.

### Equestrian Sports — Sports équestres

- **ID** : `equestrian_sports`
- **Feuilles** : 6
- **Classe** : Humain + entité (cheval)
- **Technique** : Formule asymétrie OU humain SUR cheval
- **Résolution** : `848x1264`
- **Pipeline** : ERNIE direct
- **Confiance** : Haute
- **Pièges** :
  - Si humain sur cheval : 'rider seated on the horse, both clearly visible'
- **Notes** : Pattern humain+entité validé en C.

### Martial Arts Disciplines — Disciplines d'arts martiaux

- **ID** : `martial_arts_disciplines`
- **Feuilles** : 8
- **Classe** : Solo humain en action
- **Technique** : Pose technique précise
- **Résolution** : `848x1264`
- **Pipeline** : ERNIE direct
- **Confiance** : Haute
- **Negative additionnel** : `scary, blood, violence`
- **Notes** : Pose technique > combat.

### Dance Styles — Styles de danse

- **ID** : `dance_styles`
- **Feuilles** : 8
- **Classe** : Solo humain en action
- **Technique** : Solo + pose dynamique (jambes/bras explicites)
- **Résolution** : `848x1264`
- **Pipeline** : ERNIE direct
- **Confiance** : Moyenne
- **Pièges** :
  - Poses ballet très complexes — tester individuellement
- **Negative additionnel** : `extra arm, third arm, extra leg`
- **Notes** : Énumérer membres pour éviter ajouts.

### Yoga and Wellbeing — Yoga et bien-être

- **ID** : `yoga_and_wellbeing`
- **Feuilles** : 7
- **Classe** : Solo humain en pose
- **Technique** : Pose statique précise
- **Résolution** : `848x1264`
- **Pipeline** : ERNIE direct
- **Confiance** : Haute
- **Pièges** :
  - Tree pose validé Phase B5. Étendre aux autres poses.
- **Negative additionnel** : `extra arm, extra leg`
- **Notes** : Validé empiriquement.

### E-Sports and Competitive Gaming — E-sport et gaming compétitif

- **ID** : `esports_and_gaming`
- **Feuilles** : 6
- **Classe** : Solo humain ou Scène
- **Technique** : Solo gamer + setup OU foule arena
- **Résolution** : `1024x1024`
- **Pipeline** : ERNIE direct
- **Confiance** : Moyenne
- **Pièges** :
  - Foule = pattern multi-sujets, basculer en frise
- **Notes** : Cas 'arena crowd' : utiliser frise 1×N.

---

## Professions and Jobs — Métiers et professions

**ID** : `professions`
**Sous-catégories** : 12
**Feuilles** : 108

### Health Professions — Métiers de la santé

- **ID** : `health_professions`
- **Feuilles** : 10
- **Classe** : Humain + entité OU Solo humain pose statique
- **Technique** : Formule asymétrie médecin+patient OU solo en pose
- **Résolution** : `1024x1024`
- **Pipeline** : ERNIE direct
- **Confiance** : Haute
- **Notes** : Cas 5 doctor+child validé. Pattern reproductible.

### Security and Emergency — Sécurité et urgences

- **ID** : `security_and_emergency`
- **Feuilles** : 8
- **Classe** : Solo humain pose active
- **Technique** : Solo + accessoire signature + énumération anti-bras
- **Résolution** : `848x1264`
- **Pipeline** : ERNIE direct
- **Confiance** : Haute
- **Pièges** :
  - Firefighter validé cas 4. Énumération bras critique.
- **Negative additionnel** : `extra arm, third arm`
- **Notes** : Pattern validé.

### Education and Culture — Éducation et culture

- **ID** : `education_and_culture`
- **Feuilles** : 8
- **Classe** : Humain + entité OU Multi-sujets
- **Technique** : Teacher solo OU classroom en frise 1×N
- **Résolution** : `1024x1024`
- **Pipeline** : ERNIE direct
- **Confiance** : Moyenne
- **Pièges** :
  - Classroom multi-élèves : frise 1×4 obligatoire (cas 13 anti-pattern Z5b)
- **Notes** : Choix éditorial : solo ou frise selon le visuel souhaité.

### Science and Technology Jobs — Métiers science et technologie

- **ID** : `science_and_technology_jobs`
- **Feuilles** : 9
- **Classe** : Solo humain + accessoires
- **Technique** : Solo + outils scientifiques
- **Résolution** : `1024x1024`
- **Pipeline** : ERNIE direct
- **Confiance** : Haute
- **Notes** : Sujets standards.

### Arts and Creative Jobs — Métiers d'arts et de création

- **ID** : `arts_and_creation_jobs`
- **Feuilles** : 11
- **Classe** : Solo humain + accessoires
- **Technique** : Solo + outils artistiques
- **Résolution** : `1024x1024`
- **Pipeline** : ERNIE direct
- **Confiance** : Haute
- **Pièges** :
  - Painter at easel : préciser 'easel fully visible'
- **Notes** : Décors d'atelier à préciser fully visible.

### Food Industry Jobs — Métiers de l'alimentation

- **ID** : `food_jobs`
- **Feuilles** : 9
- **Classe** : Solo humain + accessoires
- **Technique** : Solo + outils cuisine
- **Résolution** : `1024x1024`
- **Pipeline** : ERNIE direct
- **Confiance** : Haute
- **Pièges** :
  - 4+ chefs : frise 1×4 obligatoire (cas Z5b)
- **Notes** : Validé cas Z5b pour multi-chefs.

### Agriculture and Nature Jobs — Métiers de l'agriculture et de la nature

- **ID** : `agriculture_and_nature_jobs`
- **Feuilles** : 9
- **Classe** : Humain + entité
- **Technique** : Formule asymétrie humain+outil OU humain+animal
- **Résolution** : `1024x1024`
- **Pipeline** : ERNIE direct
- **Confiance** : Haute
- **Notes** : Pattern asymétrie validé.

### Construction and Crafts — Bâtiment et artisanat

- **ID** : `construction_and_crafts`
- **Feuilles** : 10
- **Classe** : Solo humain + accessoires
- **Technique** : Solo + outil + pose active
- **Résolution** : `1024x1024`
- **Pipeline** : ERNIE direct
- **Confiance** : Haute
- **Pièges** :
  - Énumérer bras pour pose active
- **Negative additionnel** : `extra arm, third arm`
- **Notes** : Pattern firefighter étendu.

### Transport and Logistics — Transport et logistique

- **ID** : `transport_and_logistics`
- **Feuilles** : 9
- **Classe** : Humain + véhicule
- **Technique** : Pilote/conducteur dans cabine OU à côté
- **Résolution** : `1024x1024`
- **Pipeline** : ERNIE direct
- **Confiance** : Moyenne
- **Pièges** :
  - Si dans cabine : préciser 'pilot seen through windshield'
- **Notes** : Variabilité selon véhicule.

### Commerce and Services — Commerce et services

- **ID** : `commerce_and_services`
- **Feuilles** : 9
- **Classe** : Humain + entité OU Solo
- **Technique** : Solo + accessoires métier
- **Résolution** : `1024x1024`
- **Pipeline** : ERNIE direct
- **Confiance** : Haute
- **Notes** : Sujets standards.

### Media and Communication — Communication et média

- **ID** : `media_and_communication`
- **Feuilles** : 8
- **Classe** : Solo humain + accessoires
- **Technique** : Solo + micro/caméra/etc.
- **Résolution** : `1024x1024`
- **Pipeline** : ERNIE direct
- **Confiance** : Haute
- **Notes** : Sujets standards.

### Sports and Leisure Jobs — Métiers du sport et des loisirs

- **ID** : `sports_and_leisure_jobs`
- **Feuilles** : 8
- **Classe** : Solo humain + accessoires
- **Technique** : Solo + sifflet/raquette/etc.
- **Résolution** : `1024x1024`
- **Pipeline** : ERNIE direct
- **Confiance** : Haute
- **Notes** : Sujets standards.

---

## Tools and Tooling — Outils et outillage

**ID** : `tools_and_tooling`
**Sous-catégories** : 8
**Feuilles** : 70

### Hand Tools — Outils manuels

- **ID** : `hand_tools`
- **Feuilles** : 12
- **Classe** : Solo objet
- **Technique** : Objet centré sur fond blanc
- **Résolution** : `1024x1024`
- **Pipeline** : ERNIE direct
- **Confiance** : Haute
- **Notes** : Catégorie la plus simple. Faible volume SEO mais essentielle pour le complétisme.

### Gardening Tools — Outils de jardinage

- **ID** : `gardening_tools`
- **Feuilles** : 10
- **Classe** : Solo objet
- **Technique** : Idem hand_tools
- **Résolution** : `1024x1024`
- **Pipeline** : ERNIE direct
- **Confiance** : Haute
- **Notes** : Idem.

### Kitchen Tools — Outils de cuisine

- **ID** : `kitchen_tools`
- **Feuilles** : 10
- **Classe** : Solo objet
- **Technique** : Idem
- **Résolution** : `1024x1024`
- **Pipeline** : ERNIE direct
- **Confiance** : Haute
- **Notes** : Idem.

### Power Tools — Outils électroportatifs

- **ID** : `power_tools`
- **Feuilles** : 8
- **Classe** : Solo objet
- **Technique** : Idem
- **Résolution** : `1024x1024`
- **Pipeline** : ERNIE direct
- **Confiance** : Haute
- **Notes** : Idem.

### Painting and Decoration Tools — Outils de peinture et décoration

- **ID** : `painting_and_decoration_tools`
- **Feuilles** : 7
- **Classe** : Solo objet
- **Technique** : Idem
- **Résolution** : `1024x1024`
- **Pipeline** : ERNIE direct
- **Confiance** : Haute
- **Notes** : Idem.

### Measuring Instruments — Instruments de mesure

- **ID** : `measuring_instruments`
- **Feuilles** : 9
- **Classe** : Solo objet
- **Technique** : Idem + détails techniques
- **Résolution** : `1024x1024`
- **Pipeline** : ERNIE direct
- **Confiance** : Haute
- **Pièges** :
  - Cadran d'horloge : préciser 'all 12 numbers visible'
- **Notes** : Détails internes à préciser.

### Traditional Farm Tools — Outils agricoles traditionnels

- **ID** : `traditional_farm_tools`
- **Feuilles** : 6
- **Classe** : Solo objet
- **Technique** : Idem hand_tools
- **Résolution** : `1024x1024`
- **Pipeline** : ERNIE direct
- **Confiance** : Moyenne
- **Notes** : Outils anciens moins représentés. Tester.

### Sewing Tools — Outils de couture

- **ID** : `sewing_tools`
- **Feuilles** : 8
- **Classe** : Solo objet
- **Technique** : Idem
- **Résolution** : `1024x1024`
- **Pipeline** : ERNIE direct
- **Confiance** : Haute
- **Notes** : Idem.

---

## Vehicles and Machines — Engins, machines et véhicules

**ID** : `vehicles_and_machines`
**Sous-catégories** : 10
**Feuilles** : 88

### Construction Machinery — Engins de chantier

- **ID** : `construction_machinery`
- **Feuilles** : 10
- **Classe** : Solo objet (véhicule)
- **Technique** : Vue trois-quarts + sol simple
- **Résolution** : `1024x1024`
- **Pipeline** : ERNIE direct
- **Confiance** : Haute
- **Pièges** :
  - Préciser nombre de roues/chenilles
- **Notes** : Engins très représentés.

### Agricultural Machinery — Engins agricoles

- **ID** : `agricultural_machinery`
- **Feuilles** : 7
- **Classe** : Solo objet (véhicule)
- **Technique** : Idem + sol champ
- **Résolution** : `1024x1024`
- **Pipeline** : ERNIE direct
- **Confiance** : Haute
- **Notes** : Idem.

### Emergency Vehicles — Véhicules d'urgence

- **ID** : `emergency_vehicles`
- **Feuilles** : 7
- **Classe** : Solo objet (véhicule)
- **Technique** : Idem + détails signaux lumineux
- **Résolution** : `1024x1024`
- **Pipeline** : ERNIE direct
- **Confiance** : Haute
- **Notes** : Idem.

### Land Transport — Transports terrestres

- **ID** : `land_transport`
- **Feuilles** : 13
- **Classe** : Solo objet (véhicule)
- **Technique** : Vue profil ou trois-quarts
- **Résolution** : `1024x1024`
- **Pipeline** : ERNIE direct
- **Confiance** : Haute
- **Pièges** :
  - Voiture : 4 roues bien visibles
- **Notes** : Catégorie volumineuse, sujets standards.

### Air Transport — Transports aériens

- **ID** : `air_transport`
- **Feuilles** : 9
- **Classe** : Solo objet en vol OU au sol
- **Technique** : Solo + ciel ou piste
- **Résolution** : `1376x768`
- **Pipeline** : ERNIE direct
- **Confiance** : Haute
- **Pièges** :
  - Si en vol : posture explicite (Insight D)
- **Notes** : Format panoramique pour avion en vol.

### Sea Transport — Transports maritimes

- **ID** : `sea_transport`
- **Feuilles** : 10
- **Classe** : Solo objet sur eau
- **Technique** : Solo + horizon mer (P3 pattern)
- **Résolution** : `1376x768`
- **Pipeline** : ERNIE direct
- **Confiance** : Haute
- **Notes** : Pattern 2 plans avec horizon mer validé.

### Space Vehicles — Engins spatiaux

- **ID** : `space_vehicles`
- **Feuilles** : 7
- **Classe** : Solo objet en espace
- **Technique** : Solo + ciel étoilé minimal
- **Résolution** : `848x1264`
- **Pipeline** : ERNIE direct
- **Confiance** : Moyenne
- **Pièges** :
  - Fond noir étoilé : exception au fond blanc, à éviter pour coloriage simple
- **Notes** : Préférer fond blanc avec étoiles dessinées plutôt que vrai fond noir.

### Industrial Machines — Machines industrielles

- **ID** : `industrial_machines`
- **Feuilles** : 8
- **Classe** : Solo objet
- **Technique** : Solo objet centré
- **Résolution** : `1024x1024`
- **Pipeline** : ERNIE direct
- **Confiance** : Haute
- **Notes** : Sujets standards.

### Sport Vehicles — Véhicules de sport

- **ID** : `sport_vehicles`
- **Feuilles** : 8
- **Classe** : Solo objet en mouvement
- **Technique** : Solo + motion lines (Z7)
- **Résolution** : `1376x768`
- **Pipeline** : ERNIE direct
- **Confiance** : Haute
- **Notes** : Format panoramique pour vitesse.

### Historic Vehicles — Véhicules historiques

- **ID** : `historic_vehicles`
- **Feuilles** : 9
- **Classe** : Solo objet
- **Technique** : Vue profil + détails époque
- **Résolution** : `1024x1024`
- **Pipeline** : ERNIE direct
- **Confiance** : Moyenne
- **Pièges** :
  - Vintage car : préciser époque pour détails
- **Notes** : Détails historiques à préciser.

---

## Household Appliances — Électroménager et appareils du quotidien

**ID** : `household_appliances`
**Sous-catégories** : 7
**Feuilles** : 57

### Kitchen Appliances — Appareils de cuisine

- **ID** : `kitchen_appliances`
- **Feuilles** : 11
- **Classe** : Solo objet
- **Technique** : Objet centré + détails fonctionnels
- **Résolution** : `1024x1024`
- **Pipeline** : ERNIE direct
- **Confiance** : Haute
- **Pièges** :
  - Réfrigérateur : préciser 'door closed' ou 'door open' explicite
- **Notes** : Sujets standards.

### Cleaning Appliances — Appareils d'entretien ménager

- **ID** : `cleaning_appliances`
- **Feuilles** : 7
- **Classe** : Solo objet
- **Technique** : Idem
- **Résolution** : `1024x1024`
- **Pipeline** : ERNIE direct
- **Confiance** : Haute
- **Notes** : Idem.

### Climate Appliances — Climatisation et chauffage

- **ID** : `climate_appliances`
- **Feuilles** : 7
- **Classe** : Solo objet
- **Technique** : Idem
- **Résolution** : `1024x1024`
- **Pipeline** : ERNIE direct
- **Confiance** : Haute
- **Notes** : Idem.

### Sound and Image — Son et image

- **ID** : `sound_and_image`
- **Feuilles** : 8
- **Classe** : Solo objet
- **Technique** : Idem
- **Résolution** : `1024x1024`
- **Pipeline** : ERNIE direct
- **Confiance** : Haute
- **Notes** : Idem.

### Computing and Phones — Informatique et téléphonie

- **ID** : `computing_and_phones`
- **Feuilles** : 9
- **Classe** : Solo objet
- **Technique** : Idem + écran simple
- **Résolution** : `1024x1024`
- **Pipeline** : ERNIE direct
- **Confiance** : Haute
- **Pièges** :
  - Écran : préciser 'simple icons on screen, no real text'
- **Notes** : Texte sur écran à éviter.

### Consumer Electronics — Électronique grand public

- **ID** : `consumer_electronics`
- **Feuilles** : 7
- **Classe** : Solo objet
- **Technique** : Idem
- **Résolution** : `1024x1024`
- **Pipeline** : ERNIE direct
- **Confiance** : Haute
- **Notes** : Sujets standards.

### Smart Home and Energy — Maison connectée et énergie

- **ID** : `smart_home_and_energy`
- **Feuilles** : 8
- **Classe** : Solo objet
- **Technique** : Idem
- **Résolution** : `1024x1024`
- **Pipeline** : ERNIE direct
- **Confiance** : Moyenne
- **Notes** : Sujets récents, moyennement représentés.

---

## Geometry and Visual Mathematics — Géométrie et mathématiques visuelles

**ID** : `geometry_and_math`
**Sous-catégories** : 7
**Feuilles** : 64

### Basic Shapes — Formes de base

- **ID** : `basic_shapes`
- **Feuilles** : 12
- **Classe** : Solo objet géométrique
- **Technique** : Forme centrée simple
- **Résolution** : `1024x1024`
- **Pipeline** : ERNIE direct (test) / SVG paramétrique si imprécis
- **Confiance** : Moyenne
- **Pièges** :
  - Précisions exactes : préciser 'perfect [shape]' (perfect circle, perfect square)
- **Notes** : Formes simples OK, précisions géométriques peu fiables.

### Geometric Solids — Solides géométriques

- **ID** : `geometric_solids`
- **Feuilles** : 10
- **Classe** : Pipeline alternatif
- **Technique** : Hors capacité ERNIE selon checklist §4.3
- **Résolution** : `N/A`
- **Pipeline** : SVG paramétrique / Pythreejs
- **Confiance** : Haute (pour SVG)
- **Pièges** :
  - 3D pure non-fiable
- **Notes** : Catégorie hors-périmètre ERNIE. Pipeline parallèle obligatoire.

### Geometric Patterns — Motifs géométriques

- **ID** : `geometric_patterns`
- **Feuilles** : 9
- **Classe** : Pattern décoratif
- **Technique** : Pattern simple OK, complexe à éviter
- **Résolution** : `1024x1024`
- **Pipeline** : ERNIE direct (simples) / SVG paramétrique (complexes)
- **Confiance** : Moyenne
- **Pièges** :
  - Tessellations strictes : hors capacité (cf. §4.3)
- **Notes** : Stripes/chevrons OK. Tessellations parfaites en SVG.

### Symmetry and Tessellation — Symétrie et pavage

- **ID** : `symmetry_and_tessellation`
- **Feuilles** : 7
- **Classe** : Pattern décoratif (avec symétrie volontaire)
- **Technique** : Symétrie volontaire (Z6 perfect)
- **Résolution** : `1024x1024`
- **Pipeline** : ERNIE direct (symétrie) / SVG (tessellation)
- **Confiance** : Haute (symétrie), Faible (tessellation)
- **Pièges** :
  - Tessellations parfaites : SVG pas ERNIE
- **Notes** : Pattern Z6 réutilisable pour butterfly et mandalas.

### Illustrated Numbers — Nombres illustrés

- **ID** : `illustrated_numbers`
- **Feuilles** : 12
- **Classe** : Multi-sujets via grille (méta-pattern §2)
- **Technique** : Chiffre + N objets : grille 3×3 si N≥6 (E.six validé)
- **Résolution** : `1024x1024`
- **Pipeline** : ERNIE direct (1-9 avec grille) / Composition PIL (10+)
- **Confiance** : Haute
- **Pièges** :
  - Comptage 6+ : grille 3×3 OBLIGATOIRE
  - Comptage 10+ : composition PIL post-traitement
- **Notes** : Game-changer Phase E.six/E.sept. Pattern documenté §6.5.

### Fractions and Proportions — Fractions et proportions

- **ID** : `fractions_and_proportions`
- **Feuilles** : 7
- **Classe** : Solo objet géométrique
- **Technique** : Pizza/cake en parts identifiables
- **Résolution** : `1024x1024`
- **Pipeline** : ERNIE direct
- **Confiance** : Moyenne
- **Pièges** :
  - Préciser le compte exact des parts
- **Notes** : Comptage parts ≤ 6 OK. Au-delà : pipeline alternatif.

### Angles and Measurements — Angles et mesures

- **ID** : `angles_and_measurements`
- **Feuilles** : 7
- **Classe** : Pipeline alternatif
- **Technique** : Géométrie pure : SVG
- **Résolution** : `N/A`
- **Pipeline** : SVG paramétrique
- **Confiance** : Haute (pour SVG)
- **Pièges** :
  - Hors capacité ERNIE
- **Notes** : Catégorie hors-périmètre ERNIE.

---

## Alphabet and Visual Language — Alphabet et langage visuel

**ID** : `alphabet_and_visual_language`
**Sous-catégories** : 8
**Feuilles** : 129

### English Alphabet Illustrated — Alphabet anglais illustré

- **ID** : `english_alphabet_illustrated`
- **Feuilles** : 26
- **Classe** : Lettre + objet
- **Technique** : Lettre géante + objet illustration
- **Résolution** : `1024x1024`
- **Pipeline** : ERNIE direct
- **Confiance** : Haute
- **Pièges** :
  - Préciser typographie thick
- **Notes** : Pattern 'Letter X with Object' standard.

### French Alphabet Illustrated — Alphabet français illustré

- **ID** : `french_alphabet_illustrated`
- **Feuilles** : 26
- **Classe** : Lettre + objet
- **Technique** : Idem English
- **Résolution** : `1024x1024`
- **Pipeline** : ERNIE direct (lettres simples) / Hybride pour accents
- **Confiance** : Moyenne
- **Pièges** :
  - Caractères accentués : préciser ou utiliser SVG
- **Notes** : Caractères É È etc. à valider.

### Arabic Alphabet Illustrated — Alphabet arabe illustré

- **ID** : `arabic_alphabet_illustrated`
- **Feuilles** : 28
- **Classe** : Pipeline alternatif (lettre) + ERNIE (objet)
- **Technique** : Texte arabe en SVG, objet en ERNIE, composition
- **Résolution** : `1024x1024`
- **Pipeline** : Hybride : SVG (lettre) + ERNIE (illustration) + composition PIL
- **Confiance** : Haute (avec hybride)
- **Pièges** :
  - Texte arabe HORS CAPACITÉ ERNIE (§4.3)
- **Notes** : Catégorie majeure pour Alwan Books. Hybride documenté.

### Decorative Letters — Lettres décoratives

- **ID** : `decorative_letters`
- **Feuilles** : 7
- **Classe** : Pattern décoratif
- **Technique** : Lettre stylisée
- **Résolution** : `1024x1024`
- **Pipeline** : ERNIE direct
- **Confiance** : Moyenne
- **Notes** : Styles spécifiques à tester (graffiti, médiéval).

### Decorative Numbers — Chiffres décoratifs

- **ID** : `decorative_numbers`
- **Feuilles** : 11
- **Classe** : Multi-sujets via grille (méta-pattern §2)
- **Technique** : Chiffre + N objets : grille 3×3 (validé E.sept perfect)
- **Résolution** : `1024x1024`
- **Pipeline** : ERNIE direct + grille
- **Confiance** : Haute
- **Pièges** :
  - 1 à 5 : énumération directe
  - 6 à 9 : grille 3×3 (Phase E.six/E.sept)
  - 10+ : composition PIL
- **Notes** : Pattern le plus emblématique de la session de tests.

### Picture Word Imagier — Imagier mot-image

- **ID** : `picture_word_imagier`
- **Feuilles** : 8
- **Classe** : Grille imagier annoté
- **Technique** : Grille 3×3 avec mot par case (X6 OK + cas 7 OK)
- **Résolution** : `1024x1024`
- **Pipeline** : ERNIE direct
- **Confiance** : Haute
- **Pièges** :
  - Mots simples seulement, pas de phrases
- **Notes** : Catégorie majeure validée. Reproductible pour fruits, légumes, couleurs, vêtements, etc.

### Comic Bubbles and Onomatopoeia — Bulles de BD et onomatopées

- **ID** : `comic_bubbles_and_onomatopoeia`
- **Feuilles** : 8
- **Classe** : Solo objet (bulle texte)
- **Technique** : Bulle stylisée + texte simple
- **Résolution** : `1024x1024`
- **Pipeline** : ERNIE direct
- **Confiance** : Moyenne
- **Pièges** :
  - Texte court (3-5 lettres max)
- **Notes** : BOOM, POW, ZAP : OK. Phrases : risqué.

### Country Flags with Names — Drapeaux des pays avec noms

- **ID** : `country_flags_with_names`
- **Feuilles** : 15
- **Classe** : Solo objet (drapeau)
- **Technique** : Drapeau + nom du pays
- **Résolution** : `1024x1024`
- **Pipeline** : ERNIE direct (simples) / SVG (complexes)
- **Confiance** : Moyenne
- **Pièges** :
  - Drapeaux complexes (croissants, étoiles précises) : SVG préférable
  - Une feuille = un drapeau (jamais regrouper, cf. X3 anti-pattern)
- **Notes** : France, USA, Tunisie : OK ERNIE. Détails complexes : SVG.

---

## Human Body and Health — Corps humain et santé

**ID** : `human_body_and_health`
**Sous-catégories** : 10
**Feuilles** : 74

### External Anatomy — Anatomie externe

- **ID** : `external_anatomy`
- **Feuilles** : 7
- **Classe** : Solo objet anatomique + labels
- **Technique** : Schéma annoté (Z1 pattern)
- **Résolution** : `1024x1024`
- **Pipeline** : ERNIE direct
- **Confiance** : Haute
- **Pièges** :
  - Labels courts uniquement
- **Notes** : Pattern Z1 validé.

### Internal Organs Educational — Organes internes éducatifs

- **ID** : `internal_organs_educational`
- **Feuilles** : 8
- **Classe** : Solo objet anatomique + labels
- **Technique** : Schéma simplifié + labels
- **Résolution** : `1024x1024`
- **Pipeline** : ERNIE direct
- **Confiance** : Moyenne
- **Pièges** :
  - Anatomie simplifiée pour kids 3-12
- **Notes** : Tester chaque organe. Cœur, poumons OK probable. Cerveau plus complexe.

### Five Senses — Cinq sens

- **ID** : `five_senses`
- **Feuilles** : 6
- **Classe** : Solo objet (organe sensoriel)
- **Technique** : Organe + élément sensoriel associé
- **Résolution** : `1024x1024`
- **Pipeline** : ERNIE direct
- **Confiance** : Haute
- **Notes** : Pattern simple validé.

### Hygiene and Self Care — Hygiène et soins personnels

- **ID** : `hygiene_and_self_care`
- **Feuilles** : 8
- **Classe** : Solo humain en action
- **Technique** : Solo + accessoire hygiène
- **Résolution** : `1024x1024`
- **Pipeline** : ERNIE direct
- **Confiance** : Haute
- **Pièges** :
  - Brushing teeth validé Phase B1
- **Notes** : Pattern enfant + activité quotidienne validé.

### Healthy Eating — Alimentation saine

- **ID** : `healthy_eating`
- **Feuilles** : 7
- **Classe** : Imagier différencié OU Solo
- **Technique** : Grille 3×3 (X1) ou solo plat
- **Résolution** : `1024x1024`
- **Pipeline** : ERNIE direct
- **Confiance** : Haute
- **Notes** : Validé cas 6 vegetable_garden_basket.

### Sport and Health — Sport et santé

- **ID** : `sport_and_health`
- **Feuilles** : 7
- **Classe** : Solo humain en action
- **Technique** : Solo + activité physique
- **Résolution** : `848x1264`
- **Pipeline** : ERNIE direct
- **Confiance** : Haute
- **Pièges** :
  - Posture explicite (Insight D) pour mouvements
- **Negative additionnel** : `extra arm, extra leg`
- **Notes** : Pattern enfant + sport reproductible.

### Emotions and Expressions — Émotions et expressions

- **ID** : `emotions_and_expressions`
- **Feuilles** : 10
- **Classe** : Imagier annoté 3×3 OU Solo visage
- **Technique** : Grille 3×3 (X6) ou solo expression
- **Résolution** : `1024x1024`
- **Pipeline** : ERNIE direct
- **Confiance** : Haute
- **Notes** : X6 OK validé. Pattern reproductible.

### Body Diversity — Diversité des corps

- **ID** : `body_diversity`
- **Feuilles** : 7
- **Classe** : Solo humain
- **Technique** : Solo + accessoire spécifique
- **Résolution** : `1024x1024`
- **Pipeline** : ERNIE direct
- **Confiance** : Haute
- **Pièges** :
  - Représenter avec dignité, pas comme curiosité
- **Notes** : Catégorie inclusive importante.

### Pregnancy and Birth — Grossesse et naissance

- **ID** : `pregnancy_and_birth`
- **Feuilles** : 6
- **Classe** : Solo humain (mère)
- **Technique** : Solo en pose + détail abdomen
- **Résolution** : `848x1264`
- **Pipeline** : ERNIE direct
- **Confiance** : Moyenne
- **Notes** : Sujet sensible. Tester représentations.

### Life Cycle and Aging — Cycle de vie et vieillissement

- **ID** : `life_cycle_and_aging`
- **Feuilles** : 8
- **Classe** : Frise narrative 1×N (pattern X2)
- **Technique** : Frise 1×4 ou 1×5 (Insight B : enrichir dernière case)
- **Résolution** : `1376x768`
- **Pipeline** : ERNIE direct
- **Confiance** : Haute
- **Pièges** :
  - Insight C : une transition à la fois entre cases
- **Notes** : Pattern X2 validé. Insights B et C critiques.

---

## Daily Life and Environments — Vie quotidienne et environnements

**ID** : `daily_life_and_environments`
**Sous-catégories** : 6
**Feuilles** : 59

### House Room by Room — Maison pièce par pièce

- **ID** : `house_room_by_room`
- **Feuilles** : 11
- **Classe** : Scène intérieure
- **Technique** : Pièce vue d'ensemble + meubles minimaux
- **Résolution** : `1024x1024`
- **Pipeline** : ERNIE direct
- **Confiance** : Haute
- **Pièges** :
  - Mobilier 'fully visible' (Insight A)
- **Notes** : Pattern cadrage dans cadrage (Z4) si fenêtre.

### School Life — Vie scolaire

- **ID** : `school_life`
- **Feuilles** : 10
- **Classe** : Multi-sujets (frise)
- **Technique** : Classroom : frise 1×N (anti-pattern Z5b)
- **Résolution** : `1376x768`
- **Pipeline** : ERNIE direct
- **Confiance** : Moyenne
- **Pièges** :
  - Ne JAMAIS faire panoramique 4+ élèves entassés
- **Notes** : Cas 13 anti-pattern documenté.

### Neighborhood and City — Quartier et ville

- **ID** : `neighborhood_and_city`
- **Feuilles** : 12
- **Classe** : Scène panoramique
- **Technique** : Vue panoramique 1376x768 + plans (P3 ou P4)
- **Résolution** : `1376x768`
- **Pipeline** : ERNIE direct
- **Confiance** : Moyenne
- **Pièges** :
  - Multi-plans : convention positionnelle (P4 perfect)
- **Notes** : Pattern multi-plans réutilisable.

### World Cuisine — Cuisine du monde

- **ID** : `world_cuisine`
- **Feuilles** : 12
- **Classe** : Solo objet (plat)
- **Technique** : Plat + détails culturels
- **Résolution** : `1024x1024`
- **Pipeline** : ERNIE direct (un plat à la fois)
- **Confiance** : Haute (un par un)
- **Pièges** :
  - X3 anti-pattern : ne JAMAIS regrouper plats par continent en grille
  - Bias asiatique du modèle
- **Notes** : Une feuille = un plat. Pas de regroupement géographique.

### Food Categories — Catégories d'aliments

- **ID** : `food_categories`
- **Feuilles** : 8
- **Classe** : Imagier différencié 3×3
- **Technique** : Grille 3×3 (X1 perfect)
- **Résolution** : `1024x1024`
- **Pipeline** : ERNIE direct
- **Confiance** : Haute
- **Notes** : Pattern X1 validé. Reproductible.

### Transport and Travel — Transport et voyage

- **ID** : `transport_and_travel`
- **Feuilles** : 6
- **Classe** : Scène
- **Technique** : Scène panoramique avec véhicule + personnages
- **Résolution** : `1376x768`
- **Pipeline** : ERNIE direct
- **Confiance** : Moyenne
- **Pièges** :
  - Si 4+ personnages : frise 1×N
- **Notes** : Pattern variable selon sujet.

---

## Nature and Environment — Nature et environnement

**ID** : `nature_and_environment`
**Sous-catégories** : 7
**Feuilles** : 66

### Four Seasons — Quatre saisons

- **ID** : `four_seasons`
- **Feuilles** : 8
- **Classe** : Frise narrative 1×4
- **Technique** : Frise 1×4 (X2 perfect, cas 9 testé presque ratage étape 4)
- **Résolution** : `1376x768`
- **Pipeline** : ERNIE direct
- **Confiance** : Haute (avec règles)
- **Pièges** :
  - Insight B : enrichir la dernière case (winter)
  - Insight C : une transition à la fois (juste les feuilles, pas le sol+animaux+ciel)
- **Notes** : Cas 9 validé presque parfait. Ajustements via Insights B et C.

### Weather Phenomena — Phénomènes météo

- **ID** : `weather_phenomena`
- **Feuilles** : 8
- **Classe** : Solo objet météo
- **Technique** : Solo + élément représentatif
- **Résolution** : `1024x1024`
- **Pipeline** : ERNIE direct
- **Confiance** : Haute
- **Pièges** :
  - Insight D : feuilles qui tombent en posture explicite
- **Notes** : Pattern simple, posture critique pour objets en chute.

### Landscapes Around the World — Paysages du monde

- **ID** : `landscapes_world`
- **Feuilles** : 10
- **Classe** : Scène paysage
- **Technique** : 2 plans avec horizon (P3 pattern)
- **Résolution** : `1376x768`
- **Pipeline** : ERNIE direct
- **Confiance** : Haute
- **Pièges** :
  - Cas 15 tropical_beach : oiseau debout (Insight D)
- **Notes** : Pattern 2 plans validé. Vigilance posture oiseaux.

### Plants and Flowers — Plantes et fleurs

- **ID** : `plants_and_flowers`
- **Feuilles** : 12
- **Classe** : Solo objet (plante)
- **Technique** : Solo + sol minimal
- **Résolution** : `1024x1024`
- **Pipeline** : ERNIE direct
- **Confiance** : Haute
- **Notes** : Sujets standards.

### Outer Space — Espace extra-atmosphérique

- **ID** : `outer_space`
- **Feuilles** : 10
- **Classe** : Scène spatiale
- **Technique** : Solo objet sur fond étoilé minimal
- **Résolution** : `848x1264`
- **Pipeline** : ERNIE direct (objets) / Composition PIL (système)
- **Confiance** : Moyenne
- **Pièges** :
  - Solar System (10 planètes) : composition PIL nécessaire
- **Notes** : Anti-pattern ERNIE : 10+ éléments en scène libre.

### Ocean and Seabed — Océan et fond marin

- **ID** : `ocean_and_seabed`
- **Feuilles** : 8
- **Classe** : Scène multi-plans OU multi-sujets
- **Technique** : P5 écosystème étagé OU procession
- **Résolution** : `1376x768`
- **Pipeline** : ERNIE direct
- **Confiance** : Moyenne
- **Pièges** :
  - P5c testé : noms d'animaux marins simples (pas 'flying squirrel')
- **Notes** : Multi-plans ou frise selon le sujet.

### Ecology and Planet Care — Écologie et protection de la planète

- **ID** : `ecology_and_planet_care`
- **Feuilles** : 10
- **Classe** : Comparatif before/after OU Solo
- **Technique** : X4 pattern pour deforestation, solo pour panneaux solaires
- **Résolution** : `1376x768`
- **Pipeline** : ERNIE direct
- **Confiance** : Haute
- **Pièges** :
  - Insight C : une transition à la fois pour comparatifs
  - Cas 12 deforestation validé presque parfait avec Insight C
- **Notes** : Pattern comparatif validé.

---

## Festivals and Celebrations — Fêtes et célébrations

**ID** : `festivals_and_celebrations`
**Sous-catégories** : 10
**Feuilles** : 73

### Christmas — Noël

- **ID** : `christmas`
- **Feuilles** : 9
- **Classe** : Variable selon sujet
- **Technique** : Solo objet OU scène (4+ frise)
- **Résolution** : `1024x1024`
- **Pipeline** : ERNIE direct
- **Confiance** : Haute
- **Pièges** :
  - Reindeer pulling sleigh : multi-sujets, frise possible
- **Notes** : Sujets très représentés.

### Halloween — Halloween

- **ID** : `halloween`
- **Feuilles** : 9
- **Classe** : Solo humain ou objet
- **Technique** : Costume kid-friendly, pas effrayant
- **Résolution** : `1024x1024`
- **Pipeline** : ERNIE direct
- **Confiance** : Haute
- **Pièges** :
  - Adapter ton pour audience 3-12
- **Negative additionnel** : `scary, blood, dark expression, sharp teeth`
- **Notes** : Negative anti-effrayant systématique.

### Easter — Pâques

- **ID** : `easter`
- **Feuilles** : 6
- **Classe** : Solo objet ou scène
- **Technique** : Solo + scène jardin
- **Résolution** : `1024x1024`
- **Pipeline** : ERNIE direct
- **Confiance** : Haute
- **Notes** : Sujets standards.

### Ramadan and Eid — Ramadan et Aïd

- **ID** : `ramadan_and_eid`
- **Feuilles** : 11
- **Classe** : Variable
- **Technique** : Solo objet (lanterne) OU scène famille
- **Résolution** : `1024x1024`
- **Pipeline** : ERNIE direct (objets) / Hybride (textes)
- **Confiance** : Haute
- **Pièges** :
  - Calligraphie arabe : pipeline hybride
- **Notes** : Catégorie clé Alwan Books. Bien représenté.

### Hanukkah — Hanoukka

- **ID** : `hanukkah`
- **Feuilles** : 5
- **Classe** : Solo objet
- **Technique** : Solo objet centré
- **Résolution** : `1024x1024`
- **Pipeline** : ERNIE direct
- **Confiance** : Haute
- **Pièges** :
  - Étoile de David : préciser '6 points exactly'
- **Notes** : Sujets standards.

### Diwali — Diwali

- **ID** : `diwali`
- **Feuilles** : 6
- **Classe** : Solo objet ou pattern
- **Technique** : Diya solo, Rangoli pattern
- **Résolution** : `1024x1024`
- **Pipeline** : ERNIE direct (simples) / SVG (Rangoli complexe)
- **Confiance** : Moyenne
- **Pièges** :
  - Rangoli complexe : SVG préférable
- **Notes** : Patterns décoratifs à tester.

### New Year Celebrations — Célébrations du nouvel an

- **ID** : `new_year_celebrations`
- **Feuilles** : 8
- **Classe** : Variable
- **Technique** : Solo ou scène
- **Résolution** : `1024x1024`
- **Pipeline** : ERNIE direct
- **Confiance** : Haute
- **Pièges** :
  - Chinese dragon : pose explicite
- **Notes** : Sujets variés selon culture.

### Love and Family Days — Fêtes de l'amour et de la famille

- **ID** : `love_and_family_days`
- **Feuilles** : 7
- **Classe** : Solo objet ou humain+entité
- **Technique** : Carte solo OU famille en interaction
- **Résolution** : `1024x1024`
- **Pipeline** : ERNIE direct
- **Confiance** : Haute
- **Notes** : Sujets standards.

### Birthdays — Anniversaires

- **ID** : `birthdays`
- **Feuilles** : 6
- **Classe** : Variable (solo objet ou frise pour party)
- **Technique** : Solo cake/cadeau OU frise 1×4 pour party
- **Résolution** : `1024x1024 ou 1376x768`
- **Pipeline** : ERNIE direct
- **Confiance** : Haute
- **Pièges** :
  - Cas 8 validé pour party en frise
- **Notes** : Pattern frise validé.

### Carnival and Mardi Gras — Carnaval et Mardi Gras

- **ID** : `carnival_and_mardi_gras`
- **Feuilles** : 6
- **Classe** : Solo humain OU objet
- **Technique** : Costume détaillé
- **Résolution** : `1024x1024`
- **Pipeline** : ERNIE direct
- **Confiance** : Haute
- **Notes** : Sujets standards.

---

## Art Creativity and Decorative Patterns — Art créativité et motifs décoratifs

**ID** : `art_creativity_and_decorative_patterns`
**Sous-catégories** : 5
**Feuilles** : 39

### Mandalas — Mandalas

- **ID** : `mandalas`
- **Feuilles** : 8
- **Classe** : Pattern décoratif (symétrie volontaire)
- **Technique** : Symétrie volontaire (Z6 perfect)
- **Résolution** : `1024x1024`
- **Pipeline** : ERNIE direct
- **Confiance** : Haute
- **Pièges** :
  - Mandalas très complexes : multiple générations + sélection
- **Notes** : Pattern Z6 réutilisable.

### World Decorative Patterns — Motifs décoratifs du monde

- **ID** : `world_decorative_patterns`
- **Feuilles** : 11
- **Classe** : Pattern décoratif
- **Technique** : Pattern simple ou via SVG si complexe
- **Résolution** : `1024x1024`
- **Pipeline** : ERNIE direct (simples) / SVG (zellige, kufique)
- **Confiance** : Moyenne
- **Pièges** :
  - Zellige, kufique : SVG paramétrique obligatoire
- **Notes** : Hors capacité documenté pour tessellations strictes.

### Abstract Patterns for Kids — Motifs abstraits pour enfants

- **ID** : `abstract_patterns_for_kids`
- **Feuilles** : 7
- **Classe** : Pattern décoratif simple
- **Technique** : Pattern libre
- **Résolution** : `1024x1024`
- **Pipeline** : ERNIE direct
- **Confiance** : Haute
- **Notes** : Patterns libres OK.

### Street Art and Graffiti — Street art et graffiti

- **ID** : `street_art_and_graffiti`
- **Feuilles** : 7
- **Classe** : Pattern décoratif (texte stylisé)
- **Technique** : Texte court stylisé + détails
- **Résolution** : `1024x1024`
- **Pipeline** : ERNIE direct
- **Confiance** : Moyenne
- **Pièges** :
  - Texte court (5 lettres max)
- **Notes** : Style spécifique.

### Famous Artworks Inspired — Œuvres célèbres revisitées

- **ID** : `famous_artworks_inspired`
- **Feuilles** : 6
- **Classe** : Scène inspirée œuvre
- **Technique** : Réinterprétation simplifiée
- **Résolution** : `1024x1024`
- **Pipeline** : ERNIE direct
- **Confiance** : Moyenne
- **Pièges** :
  - IP : œuvres post-1928 protégées
- **Notes** : Œuvres domaine public uniquement.

---

## Fantasy Magic and Tales — Fantasy magie et contes

**ID** : `fantasy_magic_and_tales`
**Sous-catégories** : 6
**Feuilles** : 55

### Classic European Tales — Contes européens classiques

- **ID** : `classic_european_tales`
- **Feuilles** : 10
- **Classe** : Scène ou solo personnage
- **Technique** : Personnage en pose iconique + scène
- **Résolution** : `1024x1024`
- **Pipeline** : ERNIE direct
- **Confiance** : Haute
- **Pièges** :
  - Domaine public, OK pour usage commercial
- **Negative additionnel** : `scary, dark`
- **Notes** : Très représenté dans datasets.

### Arabian Nights Tales — Contes des Mille et une nuits

- **ID** : `arabian_nights_tales`
- **Feuilles** : 9
- **Classe** : Scène ou solo personnage
- **Technique** : Personnage en pose + détails orientaux
- **Résolution** : `1024x1024`
- **Pipeline** : ERNIE direct
- **Confiance** : Haute
- **Notes** : Catégorie importante Alwan Books.

### Medieval Fantasy — Fantasy médiévale

- **ID** : `medieval_fantasy`
- **Feuilles** : 10
- **Classe** : Solo personnage ou créature
- **Technique** : Pose épique + détails époque
- **Résolution** : `848x1264`
- **Pipeline** : ERNIE direct
- **Confiance** : Haute
- **Pièges** :
  - Dragons : version kid-friendly
- **Negative additionnel** : `scary, blood, weapons threatening`
- **Notes** : Très représenté.

### Witchcraft and Magic — Sorcellerie et magie

- **ID** : `witchcraft_and_magic`
- **Feuilles** : 7
- **Classe** : Solo humain ou objet
- **Technique** : Sorcière friendly, pas effrayante
- **Résolution** : `1024x1024`
- **Pipeline** : ERNIE direct
- **Confiance** : Haute
- **Pièges** :
  - Adapter pour kids
- **Negative additionnel** : `scary, dark, sharp teeth, evil`
- **Notes** : Adapter ton.

### World Mythologies — Mythologies du monde

- **ID** : `world_mythologies`
- **Feuilles** : 13
- **Classe** : Solo personnage mythologique
- **Technique** : Pose iconique + attribut signature
- **Résolution** : `848x1264`
- **Pipeline** : ERNIE direct
- **Confiance** : Moyenne
- **Pièges** :
  - Méduse, Anubis : version kid-friendly
- **Negative additionnel** : `scary, blood, sharp teeth`
- **Notes** : Adaptation pour audience 3-12.

### Steampunk and Uchronia — Steampunk et uchronie

- **ID** : `steampunk_and_uchronia`
- **Feuilles** : 6
- **Classe** : Solo objet ou personnage
- **Technique** : Détails mécaniques + style époque
- **Résolution** : `1024x1024`
- **Pipeline** : ERNIE direct
- **Confiance** : Moyenne
- **Notes** : Style spécifique, niche SEO.

---

## Sciences and Technology — Sciences et technologie

**ID** : `sciences_and_technology`
**Sous-catégories** : 5
**Feuilles** : 43

### Robots and Artificial Intelligence — Robots et intelligence artificielle

- **ID** : `robots_and_artificial_intelligence`
- **Feuilles** : 8
- **Classe** : Solo objet ou personnage robot
- **Technique** : Solo + pose statique ou simple
- **Résolution** : `1024x1024`
- **Pipeline** : ERNIE direct
- **Confiance** : Haute
- **Notes** : Robots représentés.

### Scientific Experiments — Expériences scientifiques

- **ID** : `scientific_experiments`
- **Feuilles** : 9
- **Classe** : Humain + entité (instrument)
- **Technique** : Enfant + accessoire scientifique (formule asymétrie)
- **Résolution** : `1024x1024`
- **Pipeline** : ERNIE direct
- **Confiance** : Haute
- **Notes** : Pattern enfant + outil validé.

### Historic Inventions — Inventions historiques

- **ID** : `historic_inventions`
- **Feuilles** : 8
- **Classe** : Solo objet historique
- **Technique** : Solo + détails époque
- **Résolution** : `1024x1024`
- **Pipeline** : ERNIE direct
- **Confiance** : Haute
- **Notes** : Sujets bien représentés.

### Computing Illustrated — Informatique illustrée

- **ID** : `computing_illustrated`
- **Feuilles** : 8
- **Classe** : Solo objet ou Humain + entité
- **Technique** : Setup PC ou enfant à l'ordinateur
- **Résolution** : `1024x1024`
- **Pipeline** : ERNIE direct
- **Confiance** : Haute
- **Pièges** :
  - Code à l'écran : préciser 'simple symbolic code, no real text'
- **Notes** : Texte sur écran à éviter.

### Space Exploration — Exploration spatiale

- **ID** : `space_exploration`
- **Feuilles** : 10
- **Classe** : Solo objet ou humain en scaphandre
- **Technique** : Solo en pose + fond espace minimal
- **Résolution** : `848x1264`
- **Pipeline** : ERNIE direct
- **Confiance** : Haute
- **Pièges** :
  - Astronaute en flottement : posture explicite (Insight D)
- **Notes** : Posture flottement critique.

---

## Modern Themes and Trends — Thèmes et tendances modernes

**ID** : `modern_themes_and_trends`
**Sous-catégories** : 6
**Feuilles** : 51

### Kawaii and Chibi — Kawaii et chibi

- **ID** : `kawaii_and_chibi`
- **Feuilles** : 9
- **Classe** : Solo objet style kawaii
- **Technique** : Style kawaii avec gros yeux + visage
- **Résolution** : `1024x1024`
- **Pipeline** : ERNIE direct
- **Confiance** : Haute
- **Notes** : Style très représenté.

### Pixel Art and Retro Gaming — Pixel art et jeux vidéo rétro

- **ID** : `pixel_art_and_retro_gaming`
- **Feuilles** : 9
- **Classe** : Pattern pixelisé
- **Technique** : Style pixel art simple
- **Résolution** : `1024x1024`
- **Pipeline** : ERNIE direct
- **Confiance** : Moyenne
- **Pièges** :
  - Pixel art = grille pixels carrés. Préciser 'pixelated style'
- **Notes** : Style à valider.

### Social Media Illustrated — Réseaux sociaux illustrés

- **ID** : `social_media_illustrated`
- **Feuilles** : 9
- **Classe** : Variable
- **Technique** : Solo objet (smartphone) ou scène simple
- **Résolution** : `1024x1024`
- **Pipeline** : ERNIE direct
- **Confiance** : Moyenne
- **Pièges** :
  - Logos : remplacer par génériques
- **Notes** : IP risk pour logos.

### Sustainability and Eco Living — Développement durable et éco-vie

- **ID** : `sustainability_and_eco_living`
- **Feuilles** : 8
- **Classe** : Solo objet ou comparatif
- **Technique** : Solo objet OU before/after (X4)
- **Résolution** : `1024x1024`
- **Pipeline** : ERNIE direct
- **Confiance** : Haute
- **Notes** : Sujets contemporains, bien représentés.

### Diversity and Inclusion — Diversité et inclusion

- **ID** : `diversity_and_inclusion`
- **Feuilles** : 7
- **Classe** : Multi-sujets
- **Technique** : Frise 1×N (anti-pattern Z5b si > 3)
- **Résolution** : `1376x768`
- **Pipeline** : ERNIE direct
- **Confiance** : Moyenne
- **Pièges** :
  - Représentation respectueuse
- **Notes** : Frise plus respectueuse que entassement.

### Kid Mental Wellbeing — Bien-être mental des enfants

- **ID** : `kid_mental_wellbeing`
- **Feuilles** : 9
- **Classe** : Solo humain en pose
- **Technique** : Solo + pose calme/méditation
- **Résolution** : `848x1264`
- **Pipeline** : ERNIE direct
- **Confiance** : Haute
- **Notes** : Pattern yoga validé.

---

## Sous-catégories en pipeline alternatif

Sous-catégories nécessitant un pipeline non-ERNIE (SVG, composition PIL, hybride).

- **Basic Shapes** (`basic_shapes`) : ERNIE direct (test) / SVG paramétrique si imprécis
- **Geometric Solids** (`geometric_solids`) : SVG paramétrique / Pythreejs
- **Geometric Patterns** (`geometric_patterns`) : ERNIE direct (simples) / SVG paramétrique (complexes)
- **Symmetry and Tessellation** (`symmetry_and_tessellation`) : ERNIE direct (symétrie) / SVG (tessellation)
- **Illustrated Numbers** (`illustrated_numbers`) : ERNIE direct (1-9 avec grille) / Composition PIL (10+)
- **Angles and Measurements** (`angles_and_measurements`) : SVG paramétrique
- **French Alphabet Illustrated** (`french_alphabet_illustrated`) : ERNIE direct (lettres simples) / Hybride pour accents
- **Arabic Alphabet Illustrated** (`arabic_alphabet_illustrated`) : Hybride : SVG (lettre) + ERNIE (illustration) + composition PIL
- **Country Flags with Names** (`country_flags_with_names`) : ERNIE direct (simples) / SVG (complexes)
- **Outer Space** (`outer_space`) : ERNIE direct (objets) / Composition PIL (système)
- **Ramadan and Eid** (`ramadan_and_eid`) : ERNIE direct (objets) / Hybride (textes)
- **Diwali** (`diwali`) : ERNIE direct (simples) / SVG (Rangoli complexe)
- **World Decorative Patterns** (`world_decorative_patterns`) : ERNIE direct (simples) / SVG (zellige, kufique)

---

## Sous-catégories à confiance Faible — à valider en priorité

- **National Teams and Iconic Clubs** (`national_teams_and_clubs`) : Logos officiels = IP. Privilégier scènes sans logos identifiables.

---

**Fin du document.**
