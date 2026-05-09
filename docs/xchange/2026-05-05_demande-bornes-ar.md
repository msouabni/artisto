# Demande d'ajustement — Bornes de validation contenu arabe
Date : 2026-05-05  
De : Artiste Coloriage  
Pour : Équipe plateforme Alwan Books

---

## Contexte

Dans le cadre de la mise en production de la génération de contenu multilingue (FR / EN / AR), nous avons mené une série de tests sur la génération automatique de contenu éditorial arabe (titre, title_card, description, mots-clés).

Nous avons constaté que les bornes de validation actuelles du contrat (définies sur le contenu EN/FR) ne sont **pas adaptées à l'arabe**, pour une raison linguistique structurelle.

---

## Le problème : densité lexicale de l'arabe

L'arabe standard (fusha/MSA) est **morphologiquement dense** : un mot arabe exprime en moyenne ce que 1,5 à 2 mots expriment en français ou en anglais. Un titre arabe de 20 caractères peut contenir autant d'information sémantique qu'un titre français de 40 caractères.

**Conséquence concrète sur nos tests (10 contenus AR générés et validés) :**

| Champ | Borne actuelle (EN/FR) | Contenu AR produit | Résultat |
|---|---|---|---|
| `title` | 40 – 60 caractères | 15 – 30 caractères typiques | ❌ Rejeté systématiquement |
| `title_card` | ≤ 30 caractères | 10 – 25 caractères | ✅ OK |
| `description` | 80 – 130 caractères | 45 – 75 caractères typiques | ❌ Rejeté systématiquement |

Des titres arabes comme `حيوانات برية في الغابة` (25 caractères, "Animaux sauvages dans la forêt") ou `شجرة عيد الميلاد المزينة` (24 caractères, "Sapin de Noël décoré") sont sémantiquement riches et naturels, mais rejetés par les bornes actuelles.

---

## Notre demande

Appliquer des **bornes spécifiques à la locale AR** dans le schéma de validation Zod :

| Champ | Borne EN/FR (inchangée) | Borne AR proposée |
|---|---|---|
| `title` | 40 – 60 caractères | **25 – 55 caractères** |
| `title_card` | ≤ 30 caractères | **≤ 25 caractères** |
| `description` | 80 – 130 caractères | **40 – 100 caractères** |
| `keywords` | 5 mots-clés | **5 mots-clés** (inchangé) |

Ces bornes ont été calibrées sur nos données de test pour couvrir la production naturelle en arabe standard tout en maintenant un niveau de qualité éditorial équivalent.

---

## Impact côté plateforme

La modification est localisée au schéma Zod de validation du frontmatter, uniquement pour les fichiers de la locale `ar/`. Elle n'affecte pas les locales `fr/` et `en/`.

Si une validation par locale n'est pas possible dans l'architecture actuelle, une alternative serait d'élargir les bornes globales à :
- `title` : 25 – 60 caractères
- `description` : 40 – 130 caractères

Mais la solution par locale est préférable pour maintenir la rigueur sur FR et EN.

---

## Questions

1. Est-il techniquement possible d'avoir des bornes Zod différentes par locale ?
2. Si oui, quel est le délai pour mettre à jour le schéma de validation côté plateforme ?
3. En attendant, comment souhaitez-vous qu'on gère le contenu AR qui dépasse les bornes actuelles (publication bloquée, warning non-bloquant, ou autre) ?

Nous restons disponibles pour en discuter.
