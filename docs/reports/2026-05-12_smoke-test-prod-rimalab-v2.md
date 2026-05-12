# Smoke test prod rimalab-v2 — état 2026-05-12
Date : 2026-05-12
Auteur : claude-code (`artiste-coloriage`)

## Contexte

Suite à l'arbitrage rimalab-v2 ("on lance le smoke test sur firefighter, je dois recharger l'image sur R2 et lancer un build pour observer le résultat") :

- 2 nouvelles Categories `general_humans` + `objects_things` créées sur `rimalab-v2/main`. ✅
- `firefighter-superhero.png` annoncé sur R2 par rimalab-v2. ⚠️ vérifié à 404 (cf. ci-dessous).
- Branche `content/export-mep-v0` créée dans `rimalab-v2` avec les 405 MDs propres post-patches. ✅
- **Pas de push automatique** vers `origin/rimalab-v2` (sécurité, à valider explicitement).

## État R2 (vérifié par `curl -I`)

| Path R2 | HTTP | État |
|---|:---:|---|
| `coloriages/png/firefighter-superhero.png` | **404** | ⚠️ Annoncé live par rimalab-v2 mais pas trouvé |
| `coloriages/png/firefighter_superhero.png` (underscore) | 404 | (test alternative naming) |
| `coloriages/png/pompier-super-heros.png` (FR slug) | 404 | (test alternative naming) |
| `coloriages/png/itfayy-btl-kharq.png` (AR slug) | 404 | (test alternative naming) |
| `coloriages/png/lion-savane.png` | 404 | |
| `coloriages/png/cat-library.png` | **200** | ✅ Seul master live (image historique du contrat) |

**Conclusion** : il y a un malentendu ou un upload qui n'a pas abouti. Le claude rimalab pense que l'image est sur R2 mais elle n'est pas accessible publiquement.

Hypothèses :
1. Upload R2 fait sur un autre bucket que `assets.alwanbooks.com` (par exemple staging).
2. Upload fait dans un sous-chemin différent (pas `coloriages/png/<slug>.png`).
3. Custom domain `assets.alwanbooks.com` mal câblé vers le bucket.
4. Upload non encore exécuté.

## Branche rimalab-v2 préparée (locale, pas push)

Commit `03b05a7` sur branche `content/export-mep-v0` :

```
feat(content): export 135 coloriages depuis artiste-coloriage MEP v0
- 135 leaves x 3 locales = 405 MDs
- categoryId valides
- Slugs ASCII kebab strict
- URLs R2 predites
```

Path local : `D:/projets/rimalab-v2/src/content/posts/{ar,fr,en}/*.md` (405 fichiers).

Pour pusher quand validé :

```bash
git -C D:/projets/rimalab-v2 push -u origin content/export-mep-v0
# Puis ouvrir une PR sur GitHub vers main
```

## Bloqueurs résiduels

### B1 — Master PNG pas accessible sur R2

Sans master accessible publiquement, `npm run build` côté rimalab-v2 va passer (URLs sont juste des strings dans le frontmatter Zod) mais **l'image s'affichera en broken-link icon sur le site déployé**. Voir contrat §8 "Build pass mais image cassée".

Actions possibles :
1. Le claude rimalab vérifie/refait l'upload de `firefighter-superhero.png` sur R2 `coloriages/png/firefighter-superhero.png`.
2. Ou bien je configure les creds Cloudflare R2 côté `artiste-coloriage` et j'upload moi-même les 135 masters (~10 secondes pour 1 leaf, ~15 min pour 135 avec conversions).

### B2 — Creds Cloudflare R2 pas configurées côté `artiste-coloriage`

Vérifié : aucune variable d'env `CLOUDFLARE_R2_*` ni fichier `.env` côté pipeline. Tant que pas configuré, mode `--mock` uniquement (écrit dans `data/export/r2_simulated/`).

Doc setup : `docs/cloudflare-r2-setup.md` (créée Brief D).

### B3 — 51 leaves animaux non-chats tombent en `animals_cats`

Voir rapport audit v2. Sémantique imparfaite, débloque le build mais review humaine va flag. Préconisation : créer Category `animals_generic` (ou granularité fine `animals_wild` + `animals_birds` + `animals_marine` + `animals_pets`).

## Conformité finale (force du mock 2026-05-12)

| Check | Résultat |
|---|---|
| Pytest pipeline | 608 passed |
| MDs générés | 405/405 OK |
| HARD caps Zod | 405/405 ✅ |
| `categoryId` valide | 4 valeurs utilisées (`animals_cats`, `general_humans`, `objects_things`, `letters_arabic`) ✅ |
| `_pipeline`/`r2_slug` résiduels | 0/405 ✅ |
| Slugs ASCII kebab | 405/405 ✅ |
| Mock R2 variants | 540 fichiers dans `data/export/r2_simulated/` ✅ |

## Décision / Action suivante

- ➡️ **rimalab-v2** : clarifier état réel de R2 (le master `firefighter-superhero.png` est-il bien uploadé ? sur quel bucket ? quel path exact ?).
- ➡️ **artiste-coloriage** (utilisateur) : configurer creds Cloudflare R2 si on prend en charge l'upload côté pipeline.
- ➡️ **rimalab-v2** : pousser la branche `content/export-mep-v0` quand validé et lancer `npm run build` local pour vérifier que Zod accepte les 405 Posts.
- ⏳ **Si rimalab-v2 confirme avoir uploadé firefighter sur R2** : faire un `npm run build` puis push de la branche → site live en 30 s.
- ⏳ **Si on prend en charge l'upload** : 15 min de setup creds + 15 min pour upload 135 masters + push branche → site live en ~45 min.
