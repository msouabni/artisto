# Phase MEP v0 / D — Pipeline alwanbooks (R2 + rimalab-v2)
Date : 2026-05-12

## Contexte

Pipeline qui consomme `data/export/` (output Brief C3) et produit les 4 variants R2 (PNG/WebP/Thumb/PDF) + écrit les MD Astro dans `rimalab-v2/src/content/posts/{ar,fr,en}/`.

## Résultats

- Mode : **MOCK**
- Leaves traités : 135
  - OK : **135**
  - Failed : 0
  - No master PNG : 0
- Variants R2 uploaded : 540
- Variants R2 skipped (idempotent ETag match) : 0
- Posts MD écrits : 405

## Points d'attention

- **Mode MOCK** : écrit les 4 variants dans `data/export/r2_simulated/` au lieu d'upload Cloudflare R2. Utile pour smoke test sans creds.
- **Idempotence R2** : HEAD + ETag comparison avant PUT. Un rerun sur les mêmes masters skip 100 % des variants (skipped count).
- **Atomicité par leaf** : si un variant échoue, les autres variants du même leaf sont supprimés du bucket (rollback).
- **Champs `categoryId` / `ageMin` / `ageMax` / `niveauDifficulte`** : défauts injectés (`uncategorized` / 4 / 10 / `easy`) car la table `image_taxonomy_tag` n'est pas peuplée. À enrichir dans un brief séparé.
- **PNG masters** : résolus via `ARTISTE_MASTER_ROOTS` (env) ou `D:/projets/artiste-coloriage` par défaut. Le worktree peut donc consommer les masters du repo principal sans les dupliquer.

## Décision / Action suivante

- ✅ Mock OK sur 135 leaves. Vérifier `data/export/r2_simulated/` puis configurer creds R2.