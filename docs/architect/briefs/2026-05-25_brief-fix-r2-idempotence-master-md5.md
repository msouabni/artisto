# Mini-brief — Fix idempotence R2 via custom metadata `master-md5`

Date : 2026-05-25
Destinataire : claude-code (`artiste-coloriage`, exécution)
Estimation : ~1h30-2h dev (au-dessus du seuil ~1h30 voulu, mais une seule fonctionnalité cohérente — découper artificiellement n'aurait pas de sens)
Document de référence : `docs/reports/2026-05-24_phase-niveau-1-multi-sites-add-only.md` §"R2 variants : 540 uploadés / 0 skipped" + `docs/reports/2026-05-24_phase-upload-r2-masters-restants.md` (point d'écart à comprendre)

## Contexte

Au smoke 1 du brief Niveau 1 (livré 2026-05-24), le pipeline a uploadé **540 variants R2 avec 0 skipped** — alors que le run précédent (brief upload R2 du même jour) avait correctement skip 405/540 grâce à l'idempotence ETag.

Diagnostic archi : les variants WebP/Thumb/PDF ne sont pas déterministes au sens byte. Pillow et img2pdf insèrent des metadata variables (timestamps de génération, IDs uniques) qui rendent les bytes différents à chaque run, même si le master PNG source est identique. Conséquence : `md5(variant_new) ≠ ETag(variant_R2)` → upload systématique.

Le code actuel `_upload_variants_real` (`scripts/alwanbooks_pipeline.py:390`) compare `existing_etag == _md5(body)`. Si on régénère le variant à la volée et que les bytes diffèrent → l'ETag ne matche plus → ré-upload inutile.

Conséquence opérationnelle : ~200 MB ré-uploadés par run (en mode `--site alwanbooks` sans `--mock`). Pas bloquant mais gaspillage croissant si on multiplie les lots.

## Objectif

Remplacer la comparaison "ETag byte-par-byte du variant" par une comparaison "md5 du master source PNG (déterministe)" via une custom metadata R2 `x-amz-meta-master-md5`.

Logique cible :
1. À l'upload d'un variant : ajouter une metadata `master-md5 = md5(master_png_bytes)` à l'objet R2.
2. Au check idempotence : HEAD le variant R2, lire la metadata `master-md5`, comparer au md5 du master local. Si match → skip les 4 variants du leaf. Si miss ou metadata absente → upload (fallback comportement actuel par compat).

Avantage : le master PNG est déterministe (lu byte-pour-byte du fichier source), donc le md5 est stable entre runs.

## État réel à vérifier AVANT de coder (règle archi)

Exécuter ces commandes et reporter les valeurs observées dans le rapport phase (section "État réel vérifié") :

```powershell
# 1. Confirmer creds R2 chargées (présence uniquement, JAMAIS la valeur)
python -c "import os; print('R2 access key present:', bool(os.environ.get('CLOUDFLARE_R2_ACCESS_KEY_ID')))"

# 2. Localiser la fonction cible (peut avoir bougé suite à refactor)
python -c "import scripts.alwanbooks_pipeline as p; print('_upload_variants_real:', p._upload_variants_real.__code__.co_firstlineno); print('R2Client:', p.R2Client.__module__, p.R2Client.head.__code__.co_firstlineno)"

# 3. Inspecter 1 objet R2 existant pour voir la structure de retour HEAD
python -c "
import scripts.alwanbooks_pipeline as p
r2 = p._r2_client_from_env()
assert r2, 'creds R2 absentes'
result = r2.head('coloriages/png/firefighter-superhero.png')
print('HEAD result keys:', list(result.keys()) if result else 'NOT FOUND')
print('Metadata field:', result.get('Metadata') if result else None)
print('ETag:', result.get('ETag') if result else None)
"

# 4. Confirmer compteurs anormaux du smoke 1 Niveau 1
grep -A3 "R2 variants" docs/reports/2026-05-24_phase-niveau-1-multi-sites-add-only.md
```

**Critère blocant** : si la commande #3 ne retourne pas `Metadata` dans les keys (alors que boto3 le documente), demander avant de coder — peut-être que `boto3.client('s3').head_object` ne renvoie pas la metadata par défaut et qu'il faut un attribut séparé.

## Périmètre détaillé

### 1. Étendre `R2Client.put()` (ligne ~349)

Ajouter un paramètre optionnel `metadata: dict[str, str] | None = None` :

```python
def put(self, key: str, body: bytes, content_type: str, metadata: dict[str, str] | None = None) -> str:
    """Upload un objet, retourne l'ETag."""
    kwargs = {
        "Bucket": self.bucket, "Key": key, "Body": body, "ContentType": content_type,
    }
    if metadata:
        kwargs["Metadata"] = metadata
    resp = self._s3.put_object(**kwargs)
    return resp.get("ETag", "").strip('"')
```

Aucune régression : appels existants sans `metadata` continuent à fonctionner.

### 2. Vérifier `R2Client.head()` (ligne ~340) retourne bien la metadata

Le `head_object` boto3 retourne déjà `Metadata` dans le dict — mais à vérifier explicitement en commande #3 ci-dessus. Si la clé `Metadata` est présente, aucune modif nécessaire. Si absente : ajouter un cast `result['Metadata'] = result.get('Metadata', {})` pour garantir la clé.

### 3. Modifier `_upload_variants_real()` (ligne ~390)

Refactor de la logique idempotence :

```python
def _upload_variants_real(
    r2: R2Client, slug: str, variants: dict[str, bytes], master_md5: str,
) -> tuple[dict[str, str], dict[str, str]]:
    """Upload réel. Retourne ``(uploaded, skipped)`` keyed par variant.

    Idempotence : HEAD chaque variant, lire metadata 'master-md5'.
    - Si présent et == master_md5 local → skip (master inchangé, variants OK)
    - Si présent et != master_md5 → upload (master a changé)
    - Si absent (legacy upload) → fallback comparaison ETag == md5(body) du variant
    """
    uploaded: dict[str, str] = {}
    skipped: dict[str, str] = {}
    rollback_keys: list[str] = []
    try:
        for variant, body in variants.items():
            key = R2_PATHS[variant].format(slug=slug)
            existing = r2.head(key)
            if existing is not None:
                existing_master_md5 = (existing.get("Metadata") or {}).get("master-md5", "")
                if existing_master_md5 == master_md5:
                    skipped[variant] = key
                    continue
                # Fallback legacy : ETag == md5(body)
                if not existing_master_md5:
                    existing_etag = existing.get("ETag", "").strip('"')
                    if existing_etag == _md5(body):
                        skipped[variant] = key
                        continue
            # Upload avec metadata master-md5
            r2.put(key, body, _CONTENT_TYPES[variant], metadata={"master-md5": master_md5})
            uploaded[variant] = key
            rollback_keys.append(key)
    except Exception:
        for k in rollback_keys:
            r2.delete(k)
        raise
    return uploaded, skipped
```

**Note** : ajout du paramètre `master_md5: str` — la signature change. Identifier les appelants (probablement 1 seul dans `push --site`) et passer `_md5(master_png_bytes)` calculé en amont (le master PNG est lu pour générer les variants, son md5 est trivial à calculer une fois).

### 4. Identifier l'appelant et propager `master_md5`

Le caller appelle `_upload_variants_real(r2, r2_slug_v, variants)` (rapport mentionne ligne 1406). Modifier :

```python
master_md5 = _md5(master_bytes)  # master_bytes déjà chargé en amont pour générer les variants
uploaded, skipped = _upload_variants_real(r2, r2_slug_v, variants, master_md5)
```

Identique côté mock : ajouter le paramètre `master_md5` à `_upload_variants_mock` (peut être ignoré, mais cohérence de signature).

### 5. Tests dédiés (`tests/test_r2_idempotence_master_md5.py` nouveau)

Mocker `R2Client` via un fake objet en mémoire (un dict `{key: {"body": bytes, "metadata": dict, "etag": str}}`).

| Test | Vérifie |
|---|---|
| `test_first_upload_writes_master_md5_metadata` | Upload initial : variant écrit avec `Metadata={"master-md5": "abc..."}`. |
| `test_second_upload_same_master_skips_all_variants` | 2e run avec même master PNG : 4/4 variants skipped. |
| `test_master_changed_triggers_full_reupload` | Master différent (md5 différent) : 4/4 variants uploaded. |
| `test_legacy_object_without_metadata_falls_back_to_etag` | Variant uploadé en ancien format (sans `master-md5` metadata) : fallback `ETag == md5(body)` → skip si match, upload sinon. |
| `test_legacy_object_after_first_reupload_gets_master_md5` | Après fallback legacy skip, l'objet R2 garde son ancien ETag et n'a toujours pas de master-md5 metadata → run suivant re-fallback OK. |
| `test_rollback_on_partial_failure_preserves_skipped` | Si upload 3/4 réussit et 4e échoue : les 3 uploaded sont rollback, les skipped restent intacts. |

### 6. Smoke comparatif obligatoire (post-livraison, dans le rapport phase)

Après livraison :
1. Lancer `python scripts/alwanbooks_pipeline.py --site alwanbooks --no-git-push` une fois.
2. Lancer `python scripts/alwanbooks_pipeline.py --site alwanbooks --no-git-push` une 2e fois.
3. **Critère d'acceptation** : au 2e run, **`variants_skipped >= 400`** (idéalement 540). Si < 100 → bug persistant, ne pas clôturer le brief.

Reporter les 2 outputs récap deployment dans le rapport phase.

## Critères d'acceptation

1. **Tests** : suite globale verte (`pytest --ignore=tests/test_content_generator.py`) après ajout des 6 nouveaux tests. Compteur attendu : 669 → 675.
2. **Smoke comparatif** : `variants_skipped >= 400` au 2e run (cf. §6).
3. **Rétrocompatibilité** : les objets R2 uploadés avant ce fix (sans `master-md5` metadata) doivent toujours être skip-ables via fallback ETag (cf. test `test_legacy_object_without_metadata_falls_back_to_etag`).
4. **Aucune perte de fonctionnalité** : rollback atomique préservé, contraintes Content-Type préservées.
5. **État réel vérifié reporté** : section dédiée en tête du rapport phase.

## Reporting

Produire `docs/reports/2026-05-25_phase-fix-r2-idempotence-master-md5.md` :

- **Contexte** (1-2 phrases)
- **État réel vérifié** : valeurs observées des 4 commandes de check
- **Livrables** : fichiers modifiés/créés (paths)
- **Tests** : pytest count final + 6 nouveaux tests
- **Smoke comparatif** : 2 outputs récap deployment copy-pastés. Souligner la valeur `variants_skipped` au 2e run.
- **Points d'attention** : edge cases identifiés (ex: handling de Metadata None vs dict vide selon version boto3)
- **Décision / Action suivante** : "Fix R2 idempotence livré, 2e run skip 540/540 attendu, dette technique 2026-05-25 close" ou bloqueur identifié

## Hors-scope explicitement

- **Migration des objets R2 existants** (ajouter master-md5 metadata aux 540 variants déjà sur R2). Pas nécessaire — le fallback ETag les gère, et un futur run avec master inchangé re-uploadera (perdra l'idempotence 1 fois) puis bénéficiera du master-md5 à partir du 3e run. Acceptable.
- **Optimisation R2 (multi-part upload, parallélisation HEAD)** : hors-scope, le bug actuel est l'idempotence, pas la perf.
- **Refactor de la génération des variants** (rendre Pillow/img2pdf déterministes) : alternative écartée — moins robuste long terme.

## Sécurité

- Les creds R2 ne doivent JAMAIS apparaître dans les logs ni dans le rapport (vérification présence uniquement, pas la valeur).
- Aucun push git côté rimalab durant ce brief (`--no-git-push` partout).
