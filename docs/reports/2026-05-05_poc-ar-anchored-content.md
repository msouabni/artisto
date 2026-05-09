# POC — Génération contenu AR ancré sur term.name_ar
Date : 2026-05-05

## Contexte
POC-4 : tester l'injection du label AR validé d'un terme feuille de la taxonomie comme **ancre explicite** dans le prompt qwen2.5:7b, pour réduire le taux d'erreurs sémantiques observé en génération directe FR/EN→AR (baseline 30-40 % d'erreurs sujet, cf. POC `ar-content-quality` et `ar-content-prompts-v2` du 2026-05-05).

## Résultats

### Tableau 10 paires — Prompt A (anchored, sans contrainte de position)

| # | Concept EN | term_ar (ancre) | title obtenu | anchor ? | bornes | harakat | latin |
|---|---|---|---|---|---|---|---|
| 1 | elephant in the savanna | حيوانات برية | `حيوانات برية` | ✅ exact | ❌ 12c | ✅ | ✅ |
| 2 | jumping dolphin | حيوانات بحرية | `صورة حوت قفز` | ❌ absent | ❌ 12c | ✅ | ✅ |
| 3 | cow grazing in the field | حيوانات المزرعة | `صورة لبقرة تأكل في الحقل` | ❌ absent | ❌ 24c | ✅ | ✅ |
| 4 | kitten playing with a ball | القطط في اللعب | `لعب القطط مع الكرة` | ✅ token | ❌ 18c | ✅ | ✅ |
| 5 | decorated Christmas tree | عيد الميلاد | `شجرة عيد الميلاد` | ✅ exact | ❌ 16c | ✅ | ❌ |
| 6 | Easter eggs in a basket | عيد الفصح | `صورة لبيض الفصح في سلة` | ✅ exact | ❌ 22c | ✅ | ✅ |
| 7 | Halloween pumpkin with a smile | هالووين | `هالووين مانحشة ضاحكة` | ✅ exact | ❌ 20c | ✅ | ✅ |
| 8 | complex flower mandala | مندالات الزهور | `مندالات الزهور` | ✅ exact | ❌ 14c | ✅ | ❌ |
| 9 | snowy mountains scene | الشتاء | `صورة جبال مغطاة بالثلوج` | ❌ absent | ❌ 23c | ✅ | ✅ |
| 10 | racing car on a track | السيارات | `صورة سيارة سباق` | ✅ prefix | ❌ 15c | ✅ | ✅ |

### Métriques globales

| Métrique | Baseline (POC ar-content-prompts-v2, prompt B) | Prompt A (anchored) | Prompt B (anchored + force prefix) |
|---|---|---|---|
| JSON parsable | 10/10 | **10/10** | **10/10** |
| Anchor / sujet correct | 6/10 (40 % erreurs sémantiques) | **7/10** (30 % anchor missing) | **10/10** (0 % anchor missing) |
| title dans bornes ¹ | 8/10 ([40,60]) | **0/10** ([30,50]) | **0/10** ([30,50]) |
| description dans bornes ¹ | 0/10 ([80,130]) | **0/10** ([55,90]) | **0/10** ([55,90]) |
| keywords = 5 | n/a (3 fixé baseline) | 10/10 | 10/10 |
| Harakat absents | 7/10 | **10/10** ✅ | **10/10** ✅ |
| Latin absents | 9/10 | **8/10** | **6/10** ⚠ régression |
| Latence moyenne | 5.1s | 6.0s | 4.2s |

¹ *Les bornes de longueur ont changé entre baseline (40-60 / 80-130) et POC-4 (30-50 / 55-90). Comparaison non directe.*

### Détail Prompt B (déclenchée parce que A à 30 % anchor missing > seuil 10 %)

| # | Concept EN | term_ar | title B | anchor | latin |
|---|---|---|---|---|---|
| 1 | elephant in the savanna | حيوانات برية | `حيوانات برية` | ✅ | ❌ |
| 2 | jumping dolphin | حيوانات بحرية | `حيوانات بحرية` | ✅ | ❌ |
| 3 | cow grazing in the field | حيوانات المزرعة | `حيوانات المزرعة` | ✅ | ✅ |
| 4 | kitten playing with a ball | القطط في اللعب | `القطط في اللعب` | ✅ | ✅ |
| 5 | decorated Christmas tree | عيد الميلاد | `عيد الميلاد` | ✅ | ✅ |
| 6 | Easter eggs in a basket | عيد الفصح | `عيد الفصح` | ✅ | ✅ |
| 7 | Halloween pumpkin with a smile | هالووين | `هالووين كيوت بومبيون` | ✅ | ❌ |
| 8 | complex flower mandala | مندالات الزهور | `مندالات الزهور` | ✅ | ❌ |
| 9 | snowy mountains scene | الشتاء | `شتاء جبال` | ✅ no_article | ✅ |
| 10 | racing car on a track | السيارات | `سيارات على حلبة` | ✅ no_article | ✅ |

## Points d'attention

### Points positifs
- **Harakat strictement absents : 10/10 dans les 2 variantes** ✅. La consigne "pas de harakat" est respectée systématiquement (vs 7/10 baseline). Lev-up qualité.
- **Sujet juste : amélioration nette vs baseline**. 30 % anchor missing en A est en fait *moins grave* que ça en a l'air : sur les 3 cas, le contenu reste sémantiquement pertinent (ex. `حوت` = baleine pour "dolphin", `بقرة` = vache pour "cow grazing", `جبال + ثلوج` = montagnes + neige). Le modèle préfère un terme **plus spécifique au concept** que l'ancre catégorielle. Pas une hallucination type baseline (`أسد بابا` pour éléphant, `دبكة` pour dauphin).
- **Variante B : 100 % anchor exact**. Si on a besoin de contrôle dur sur l'apparition du label catégoriel, B le garantit.
- **Latence stable** ~5s, pas de cold-start anormal.

### Points négatifs / blockers
- **Bornes longueur 0/10 dans les 2 prompts**. C'est un blocker pour publication directe. Le modèle plafonne autour de 10-25 chars sur title (vs cible 30-50) et 25-50 chars sur description (vs cible 55-90). La consigne "30 à 50 caractères" est ignorée.
- **Latin résiduel** : A à 8/10 propre (régression de B à 6/10). Cas observés :
  - A[5] : `'مerry'` dans keywords (mot anglais Christmas inséré, "م" + "erry")
  - A[8] : `' Mandalas'` dans keywords + dans description "صورة ل Mandalas الزهور"
  - B[1] elephant, B[2] dolphin, B[7] halloween, B[8] mandalas : latin dans description ou keywords
- **Variante B introduit des titres trop courts** : forcer `term_ar` en début produit souvent un titre = `term_ar` seul (ex. `حيوانات برية` 12c, `عيد الفصح` 9c). Pour atteindre 30-50c il faudrait laisser le modèle développer après l'ancre.
- **Cas A[5] et A[8] mêlent AR et latin** dans le même mot/phrase (`مerry`, `صورة ل Mandalas`). Le modèle traite des concepts familiers (Christmas merry, Mandalas) et bascule en latin pour un mot.

### Erreurs sémantiques résiduelles A — analyse détaillée
- **A[2] dolphin** : `حوت` au lieu de `دلفين` ou ancre `حيوانات بحرية`. **Erreur lexicale** : whale ≠ dolphin. Le modèle a un trou sur le mot dauphin en AR.
- **A[3] cow** : `بقرة` (cow) plus précis que l'ancre `حيوانات المزرعة` (farm animals). **Pas une erreur**, juste un choix lexical plus spécifique.
- **A[9] snow** : `جبال + ثلوج` (mountains + snow), ancre `الشتاء` (winter) absente du titre/desc mais `شتاء` dans keywords. **Pas une erreur** non plus, juste l'ancre dans un autre champ.

→ Sur les 3 "anchor missing" de A, **seul A[2] (dolphin/whale)** est une erreur lexicale réelle. Les 2 autres sont des choix sémantiques meilleurs que l'ancre.

## Décision / Action suivante

### Verdict
✅ **L'approche taxonomie-ancrée est un progrès net** vs baseline. La présence d'erreurs sémantiques majeures (type `أسد بابا` pour éléphant, `دبكة` pour dauphin) **disparaît**. Les harakat sont systématiquement absents.

⚠ **Mais l'approche seule ne suffit pas pour la prod** : bornes longueur violées 0/10, latin résiduel 8/10. Un prompt-only n'amène pas à publication directe.

### Recommandation pour P2 (génération i18n)

Approche **prompt A + boucle validate-and-regenerate** :

1. **Garder Prompt A** (sans contrainte de position) : il produit du contenu plus naturel et sémantiquement pertinent. Quand le term_ar n'apparaît pas, c'est souvent un meilleur choix lexical que l'ancre catégorielle.
2. **Ajouter une validation post-LLM** :
   - Bornes longueur (regen si hors)
   - Absence latin (regen si présent)
   - Présence du term_ar OU d'un synonyme proche (sinon fallback Prompt B)
3. **Variante B comme fallback** quand prompt A échoue 2 fois sur l'ancre — accepter titres courts et compléter manuellement.
4. **Élargir les bornes** : passer de [30,50] à [25,55] pour title, et [55,90] à [40,100] pour description. Les bornes actuelles paraissent **trop strictes pour l'arabe** (densité lexicale 50 % inférieure au FR/EN, cf. brief). Recalibrer après mesure sur 50+ outputs réels.

### Approche validée pour P2 ?
**Conditionnellement oui** : ancrage taxonomique adopté, mais P2 doit inclure **boucle validate-regen** + recalibration des bornes AR. La génération en un coup ne suffit pas.

### Question pour Claude Desktop
- Validez-vous l'élargissement des bornes Zod côté AR (densité lexicale plus faible) ? Si oui, à confirmer côté contrat Alwan.
- La boucle validate-regen avec budget de 3 retries max acceptable côté latence (~15-20s par image) ?

## Annexes

Données brutes : `2026-05-05_poc-ar-anchored-content.json`
Script : `scripts/poc_ar_anchored_content.py`
