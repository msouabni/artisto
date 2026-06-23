# Fix — BingWebmasterProvider.inspect (smoke-test API réelle)
Date : 2026-06-23

## Contexte

Un smoke-test de `BingWebmasterProvider.inspect()` (`src/services/index_providers.py`,
branche `feat/cockpit-git-indexer`) contre l'API Bing Webmaster **réelle** a révélé
2 bugs latents :

1. **POST → HTTP 405 Method Not Allowed.** L'endpoint `GetUrlInfo` est en réalité
   un **GET** avec query params (`apikey` + `siteUrl` + `url`), pas un POST avec body JSON.
2. **`DocumentStatus` inexistant.** Le code lisait `info.get("DocumentStatus")` →
   champ absent de la réponse réelle → `coverage_state` toujours `unknown`. La réponse
   réelle (HTTP 200) est un objet unique sous `d`, sans état de couverture textuel ;
   il faut le **dériver** des champs bruts.

## Résultats

### Contrat réel observé (HTTP 200)
```json
{"d":{"__type":"UrlInfo:#Microsoft.Bing.Webmaster.Api",
      "AnchorCount":0,"DiscoveryDate":"/Date(-62135568000000-0800)/",
      "DocumentSize":0,"HttpStatus":0,"IsPage":true,
      "LastCrawledDate":"/Date(-62135568000000-0800)/",
      "TotalChildUrlCount":0,
      "Url":"https://alwanbooks.com/fr/coloriages/cahier-des-mers/baleine"}}
```
Dates au format .NET `/Date(<ms>±offset)/` ; `/Date(-62135568000000-0800)/` =
`DateTime.MinValue` = jamais crawlé/découvert.

### Corrections apportées (UNIQUEMENT `inspect` + helpers Bing)
- **GET** url-encodé via `urllib.parse.urlencode({apikey, siteUrl, url})` au lieu du POST.
- Nouveau helper module-level **`_parse_dotnet_date(raw) -> str|None`** : parse
  `/Date(<ms>[±offset])/`, ignore l'offset (UTC), retourne `None` sur sentinel négatif /
  absent / malformé. Ne lève jamais.
- Nouveau helper module-level pur **`_bing_coverage_from_info(info) -> str`** (extrait
  pour testabilité sans réseau ; appelé par `inspect`). Règle de dérivation :
  - `LastCrawledDate` réelle ET `HttpStatus == 200` → `indexed`
  - `LastCrawledDate` réelle ET `HttpStatus` non-200 (≠0) → `crawled_not_indexed`
  - `DiscoveryDate` réelle ET `LastCrawledDate` au sentinel → `discovered`
  - tout au sentinel / `HttpStatus == 0` → `unknown`
- `last_crawl` désormais converti .NET → ISO8601 UTC (`_parse_dotnet_date`), `None` si sentinel.
- Suppression de `_map_bing_coverage` / `_BING_COVERAGE_MAP` (devenus inutiles ; aucun
  autre référent dans le repo).
- **Sécurité clé API** : la query string (qui contient `apikey`) n'est **jamais loguée** ;
  seuls `url` et le code HTTP apparaissent dans les warnings.
- Conservés : gating `if not self.available(): return {}`, back-off 3 essais, mapping
  de tout non-200 / `HTTPError` → `{coverage_state: unknown, last_crawl: None}`, passage
  final par `_validate_result(self.engine, out)`, `# pragma: no cover` sur `inspect`.

### Tests
Nouveau fichier `tests/cockpit/test_bing_provider.py` (12 tests, purs — aucun réseau, aucune DB) :
- `_parse_dotnet_date` : date réelle → ISO (+ offset ignoré), sentinel → None, vide/malformé → None.
- `_bing_coverage_from_info` : les 4 états (indexed / crawled_not_indexed / discovered /
  unknown) + info vide + HttpStatus non-numérique.
- `provider_is_live("bing")` : True avec `BING_WEBMASTER_API_KEY`, False sans.

**pytest `tests/cockpit/` : 145 passed, 0 failed** (16.3 s, Postgres éphémère docker).
Fichier seul : 12 passed.

## Points d'attention

- **Site pas encore live.** Tant qu'Alwan Books n'est pas crawlé par Bing, la réponse
  réelle restera au sentinel (`HttpStatus == 0`) → `coverage_state = unknown`. C'est
  attendu et correct ; les états réels n'apparaîtront qu'**après le premier crawl
  post-lancement**.
- Le smoke-test confirme **clé API valide + site vérifié** dans Bing Webmaster (HTTP 200,
  objet `UrlInfo` bien formé). Le branchement réel est donc prêt côté creds.
- `_bing_coverage_from_info` reste prudent sur le cas rare « crawlé mais `HttpStatus == 0` » :
  `discovered` si découvert, sinon `unknown` (un crawl réel porte normalement un status).

## Décision / Action suivante

Correction prête et testée. Aucun commit/push effectué (à la main de l'architecte).
Action suivante : merge sur feu vert ; re-vérifier `coverage_state` réel après le premier
crawl Bing post-lancement (le `unknown` actuel n'est pas un bug).
