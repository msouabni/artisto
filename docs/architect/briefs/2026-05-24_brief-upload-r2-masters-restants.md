# Brief court — Upload R2 des 131 masters PNG manquants

Date : 2026-05-24
Destinataire : claude-code (`artiste-coloriage`, exécution)
Estimation : ~15 min wall-clock dont ~10 min de upload réseau

## Contexte

Au 2026-05-23, R2 contient seulement 6/137 masters (firefighter-superhero + les 5 slugs ex-bug-B). Les 131 autres ont leurs MD pushés côté rimalab-v2 (branche `content/export-mep-v0` commit `6889870`) mais leurs URLs `imageSource/Web/Thumb/Pdf` retournent 404 côté `assets.alwanbooks.com`.

Conséquence visible : sur le site en preview, ~95 % des coloriages s'affichent en broken-link. Bloqueur pour le cutover J+30.

Creds Cloudflare R2 sont déjà en place côté `.env` (confirmé par utilisateur 2026-05-24).

## Objectif

Passer R2 de 6/137 à **137/137 masters** + leurs 3 variants chacun (webp, thumbs, pdf) = **548 fichiers attendus** sur le bucket.

L'idempotence ETag du pipeline garantit que les 6 masters déjà présents seront skipped (pas de re-upload inutile).

## Périmètre

Exécuter le pipeline en mode upload R2 réel + écriture MDs locale sans git push :

```powershell
cd D:\projets\artiste-coloriage
python scripts/alwanbooks_pipeline.py --no-git-push
```

Ce mode :
- Upload les 4 variants R2 pour chaque leaf (~131 × 4 = 524 nouveaux fichiers, + 6 × 4 = 24 skipped via ETag).
- Régénère les MD dans `D:\projets\rimalab-v2\src\content\posts\` (même contenu que ce qui est déjà sur la branche `content/export-mep-v0`, donc `git status` côté rimalab doit rester clean modulo une éventuelle normalisation CRLF→LF).
- **Ne fait aucun `git push`** côté rimalab.

## Critères d'acceptation

1. **Compteur upload final** dans la sortie du script :
   - `uploads ok: 524` (±5 selon idempotence exacte) ou équivalent
   - `failed: 0`
   - `skipped (etag match): 24` (ou ±)
2. **Vérification HTTP** post-upload sur 5 slugs aléatoires choisis hors des 6 historiques. Exemple :
   ```powershell
   curl -I https://assets.alwanbooks.com/coloriages/png/lion-in-the-savanna.png
   curl -I https://assets.alwanbooks.com/coloriages/webp/lion-in-the-savanna.webp
   ```
   Doit retourner `200 OK`, `Server: cloudflare`, `ETag` non vide.
3. **`git status` côté rimalab clean** après l'exécution. Si un diff inattendu apparaît dans `src/content/posts/`, **NE PAS commit** : reporter dans le rapport et investiguer.
4. **Aucun commit ni push** automatique. Le brief n'autorise pas de push.

## Reporting

Produire `docs/reports/2026-05-24_phase-upload-r2-masters-restants.md` (~30 lignes max) :

- **Contexte** (1 phrase)
- **Résultats** : compteurs upload exacts (ok / failed / skipped) + sample HTTP vérifié (5 slugs avec code retour)
- **Points d'attention** : diff inattendu côté rimalab, erreurs R2, timeout, etc. (si rien : "RAS")
- **Décision / Action suivante** : "R2 à 137/137 masters live, prêt pour le cutover" ou bloqueur identifié

## Hors-scope explicitement

- Pas de `git push` côté rimalab (même si tu vois des diffs).
- Pas de modification du code pipeline (le mode `--no-git-push` existe déjà).
- Pas de re-génération des images (les masters PNG existent déjà dans `data/images/` ou équivalent, lus par le pipeline).
- Pas de modification du `.env` ni des creds R2.
- Pas de touche aux categories ou themes.

## Sécurité

- Les creds R2 dans `.env` ne doivent JAMAIS apparaître dans le rapport ni dans aucun log committé.
- En cas d'erreur d'auth R2 (401/403) : NE PAS afficher les creds dans le diagnostic. Reporter "erreur auth R2" + vérifier que `CLOUDFLARE_R2_ACCESS_KEY_ID` et `CLOUDFLARE_R2_SECRET_ACCESS_KEY` sont présents (présence/absence uniquement, pas la valeur).
