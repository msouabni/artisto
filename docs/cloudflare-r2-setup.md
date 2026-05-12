# Configuration Cloudflare R2 — guide setup

Date : 2026-05-12
Pour : `scripts/alwanbooks_pipeline.py` (Brief MEP-v0/D)

## Pré-requis

- Compte Cloudflare actif avec R2 activé (page **Workers & Pages > Plans**).
- Domaine `alwanbooks.com` géré dans Cloudflare (pour le bucket public).
- Bucket R2 existant (sinon : `Cloudflare Dashboard > R2 > Create bucket`).

## Étapes pour générer les creds

### 1. Récupérer le `CLOUDFLARE_R2_ACCOUNT_ID`

1. Va sur https://dash.cloudflare.com
2. Sélectionne ton compte (sidebar gauche).
3. **Account ID** affiché dans le panneau de droite ("API" section).
4. Copie la valeur (format `abc123def456...`, 32 hex chars).

### 2. Créer un token API R2 dédié

1. Dashboard Cloudflare → **R2** (sidebar).
2. Bouton **Manage R2 API Tokens** (en haut à droite).
3. **Create API Token** :
   - **Token name** : `alwanbooks-pipeline-rw` (descriptif).
   - **Permissions** : `Object Read & Write` (lecture + écriture sur les objets).
   - **Specify bucket(s)** : `Apply to specific buckets only` → ton bucket
     (ex. `alwanbooks-assets`).
   - **TTL** : optionnel mais recommandé (90 jours puis rotation).
4. Bouton **Create API Token**.
5. **IMPORTANT** : Cloudflare affiche **une seule fois** :
   - `Access Key ID`
   - `Secret Access Key`
   - Endpoint URL (`https://<account_id>.r2.cloudflarestorage.com`)
6. Sauvegarder dans un gestionnaire de mots de passe (1Password / Bitwarden /
   Vault) **immédiatement**.

### 3. Configurer les variables d'environnement

Crée (ou édite) `.env` à la racine du projet `artiste-coloriage` :

```env
CLOUDFLARE_R2_ACCOUNT_ID=abc123def456...
CLOUDFLARE_R2_ACCESS_KEY_ID=xxxx
CLOUDFLARE_R2_SECRET_KEY=yyyy
CLOUDFLARE_R2_BUCKET=alwanbooks-assets
CLOUDFLARE_R2_PUBLIC_BASE=https://assets.alwanbooks.com
```

**Sécurité** : `.env` est déjà dans `.gitignore` (vérifié, ligne 13).

Pour charger les vars dans le shell (PowerShell) :

```powershell
Get-Content .env | ForEach-Object {
  if ($_ -match '^([A-Z_]+)=(.+)$') {
    [Environment]::SetEnvironmentVariable($matches[1], $matches[2], 'Process')
  }
}
```

Ou pour bash/Git Bash :

```bash
set -a; source .env; set +a
```

### 4. Configurer le domaine public

Pour que les URLs `https://assets.alwanbooks.com/coloriages/png/<slug>.png`
fonctionnent réellement :

1. Dashboard R2 → ton bucket → onglet **Settings**.
2. **Custom Domains** → **Connect Domain** → entre `assets.alwanbooks.com`.
3. Cloudflare ajoute automatiquement le CNAME requis (DNS proxifié orange
   cloud).
4. Vérifier : `curl -I https://assets.alwanbooks.com/test-file` retourne
   un 404 R2 (et non un 404 Cloudflare générique).

## Vérification finale

```bash
# 1. Smoke test mock (pas de creds requis)
python scripts/alwanbooks_pipeline.py --mock --leaf-id firefighter_superhero
# → 1 leaf OK, écrit data/export/r2_simulated/

# 2. Smoke test 1 leaf en réel (avec creds)
python scripts/alwanbooks_pipeline.py --leaf-id firefighter_superhero --no-git-push
# → 1 leaf, 4 variants uploadés sur R2, MDs écrits dans rimalab-v2

# 3. Vérifier accessibilité publique
curl -I https://assets.alwanbooks.com/coloriages/png/firefighter-superhero.png
# → HTTP/2 200 + content-type: image/png

# 4. Production complète 135 leaves + push rimalab-v2
python scripts/alwanbooks_pipeline.py
```

## Rotation des creds

- Tous les 90 jours (par TTL ou manuellement).
- Pour rotater : créer un nouveau token, mettre à jour `.env`, **puis**
  révoquer l'ancien token.
- Le code est idempotent : la rotation ne casse aucun objet déjà uploadé.

## Troubleshooting

| Erreur | Cause probable | Fix |
|---|---|---|
| `Creds R2 absents (...)` | Variables d'env non chargées | `source .env` puis vérifier `$env:CLOUDFLARE_R2_ACCESS_KEY_ID` |
| `403 Forbidden` au PUT | Token sans permission Write | Recréer avec `Object Read & Write` |
| `404 NoSuchBucket` | Bucket name incorrect | Vérifier `CLOUDFLARE_R2_BUCKET` matche exactement le nom Cloudflare |
| `SignatureDoesNotMatch` | Secret key tronqué | Recopier depuis le gestionnaire de mots de passe |
| URL publique 404 | Custom domain pas configuré | Étape 4 ci-dessus |

## Coût indicatif

- Stockage R2 : 0.015 $ / Go / mois (10 Go ≈ 0.15 $/mois).
- Class A operations (PUT) : 4.50 $ / million.
- Class B operations (GET) : 0.36 $ / million.
- **Egress gratuit** (différenciateur R2 vs S3).

Pour 135 leaves × 4 variants = 540 PUT initiaux = négligeable.

## Références

- Doc officielle : https://developers.cloudflare.com/r2/
- API tokens : https://developers.cloudflare.com/r2/api/s3/tokens/
- Custom domains : https://developers.cloudflare.com/r2/buckets/public-buckets/
