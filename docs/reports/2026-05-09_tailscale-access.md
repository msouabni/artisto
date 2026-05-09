# Accès Tailscale — API + ComfyUI bind 0.0.0.0
Date : 2026-05-09

## Contexte

Rendre l'API FastAPI (port 8000) et ComfyUI (port 8188) accessibles depuis d'autres machines sur le réseau Tailscale (et plus généralement depuis toute interface réseau), sans changer le comportement local. Avant le fix, les deux services bindaient `127.0.0.1` exclusivement, donc inaccessibles depuis un autre nœud Tailscale.

## Fichiers modifiés

| Fichier | Nature de la modification |
|---|---|
| `start.py` | bind host configurable pour uvicorn et ComfyUI |
| `CLAUDE.md` | section "Key environment variables" : ajout `ARTISTE_API_HOST` et `COMFYUI_HOST` |
| `.env.example` | **non modifié** (le fichier n'existe pas — le user a un `.env` réel non touché par cette tâche) |

## Diff avant / après

### `start.py` — bloc API

**Avant** (bind hardcodé loopback) :
```python
api_host = "127.0.0.1"
api_port = args.api_port
api_base = f"http://{api_host}:{api_port}"
...
if _tcp_open(api_host, api_port):
    if _is_artiste_api(api_base): ...
...
uvicorn_args = [..., "--host", api_host, "--port", str(api_port)]
```

**Après** (bind = `ARTISTE_API_HOST` env, défaut `0.0.0.0` ; les health checks restent sur `127.0.0.1` pour fiabilité) :
```python
api_host = os.environ.get("ARTISTE_API_HOST", "0.0.0.0").strip() or "0.0.0.0"
api_port = args.api_port
api_probe_host = "127.0.0.1"
api_base = f"http://{api_probe_host}:{api_port}"
...
if _tcp_open(api_probe_host, api_port):
    if _is_artiste_api(api_base): ...
...
uvicorn_args = [..., "--host", api_host, "--port", str(api_port)]
```

Pourquoi séparer `api_host` et `api_probe_host` : `connect(0.0.0.0)` n'est pas portable (succès sur Linux, échec sur Windows ou sémantique floue). Les sondes TCP/HTTP ciblent toujours `127.0.0.1` qui est garanti routable, le bind reste `0.0.0.0` pour exposer toutes les interfaces.

### `start.py` — bloc ComfyUI

**Avant** (pas de flag `--listen`, ComfyUI bind `127.0.0.1` par défaut) :
```python
proc = _popen("ComfyUI", [comfy_exe, str(home / "main.py")], cwd=home)
```

**Après** (flag `--listen <COMFYUI_HOST>`, défaut `0.0.0.0`) :
```python
comfy_bind_host = os.environ.get("COMFYUI_HOST", "0.0.0.0").strip() or "0.0.0.0"
comfy_args = [comfy_exe, str(home / "main.py"), "--listen", comfy_bind_host]
print(f"[comfy] Bind  : --listen {comfy_bind_host} (env COMFYUI_HOST)", flush=True)
proc = _popen("ComfyUI", comfy_args, cwd=home)
```

### `CLAUDE.md` — Key environment variables

Ajout dans la liste à plat :
```diff
- ARTISTE_LOG_TO_FILE · ARTISTE_API_PORT, ARTISTE_API_BASE … COMFYUI_HOME / COMFYUI_ROOT, COMFYUI_PYTHON
+ ARTISTE_LOG_TO_FILE · ARTISTE_API_HOST (default 0.0.0.0 — bind interface uvicorn ; mettre 127.0.0.1 pour limiter au loopback), ARTISTE_API_PORT, ARTISTE_API_BASE … COMFYUI_HOME / COMFYUI_ROOT, COMFYUI_PYTHON, COMFYUI_HOST (default 0.0.0.0 — bind interface ComfyUI passé à --listen)
```

## Vérification

### IP Tailscale du nœud courant

```
$ tailscale ip -4
100.114.117.104
```

### Bind effectif uvicorn après fix

Lancement validé : `python start.py --no-comfy --no-reload`

Logs observés :
```
[start] uvicorn: …\python.exe -m uvicorn api.main:app --host 0.0.0.0 --port 8000
INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
```

### Tests HTTP

| URL | Code | Résultat |
|---|---|---|
| `http://127.0.0.1:8000/` | 200 | `{"message":"Artiste Coloriage API",...}` |
| `http://100.114.117.104:8000/` (Tailscale) | 200 | `{"message":"Artiste Coloriage API",...}` ✅ |
| `http://100.114.117.104:8000/docs` | 200 | Swagger accessible ✅ |

### ComfyUI — état au moment du rapport

Le ComfyUI actuellement actif a été lancé **avant** le fix (cmdline observée : `python.exe main.py --listen 127.0.0.1 --port 8188`). Tests :

| URL | Code | Note |
|---|---|---|
| `http://127.0.0.1:8188/` | 200 | OK localhost (avant fix) |
| `http://100.114.117.104:8188/` | 000 | Connect refused — bind 127.0.0.1 ⚠️ |

→ **Action requise pour activer ComfyUI sur Tailscale** : redémarrer ComfyUI via `start.py` (sans `--no-comfy`) **après l'avoir arrêté manuellement**. Le prochain lancement passera `--listen 0.0.0.0` automatiquement. Une fois redémarré : `curl http://100.114.117.104:8188/` doit retourner 200.

## URLs Tailscale à utiliser

```
API + Swagger + annotateurs HTML :
  http://100.114.117.104:8000
  http://100.114.117.104:8000/docs
  http://100.114.117.104:8000/data/benchmark-annotator.html?dir=poc-scale-benchmark

ComfyUI (après redémarrage) :
  http://100.114.117.104:8188
```

## Points d'attention

### 1. `.env.example` absent — recommandation
Le user a un `.env` réel mais pas de `.env.example` versionné. Si l'équipe en crée un futur, ajouter :
```
ARTISTE_API_HOST=0.0.0.0
ARTISTE_API_PORT=8000
COMFYUI_HOST=0.0.0.0
```
Non fait dans cette tâche par souci de respecter "Si le fichier existe".

### 2. Comportement local inchangé
- Toutes les sondes (`_tcp_open`, `_is_artiste_api`, `_wait_api_ready`) ciblent `127.0.0.1` — la logique de détection "API déjà active" et de timeout reste identique.
- Le `api_base` utilisé pour les checks reste `http://127.0.0.1:8000` — pas de régression sur les tests internes.

### 3. Sécurité — surface d'attaque élargie
Bind `0.0.0.0` = exposé à tous les nœuds Tailscale (et au LAN si pas de firewall). L'API et ComfyUI n'ont pas d'authentification. Tailscale ACL recommandée si plusieurs utilisateurs sur le tailnet. Pour usage strictement local : `ARTISTE_API_HOST=127.0.0.1` et `COMFYUI_HOST=127.0.0.1` dans `.env` restaurent l'ancien comportement.

### 4. Singleton lock préservé
Le mécanisme `start.lock` (`logs/start.lock`) reste en place. Une seule instance de `start.py` à la fois — y compris pour les tests Tailscale.

### 5. Reload uvicorn et bind
`--reload` peut interagir avec `--host 0.0.0.0` sur certains setups Windows (worker watcher peut binder localhost). Si besoin : forcer `--no-reload` en prod ou utiliser `ARTISTE_API_HOST=127.0.0.1`. Validation actuelle faite en `--no-reload`.

### 6. Pas de proxy / TLS
L'API est servie en HTTP nu. Pour de la prod hors Tailscale, ajouter un reverse proxy (caddy / nginx) avec TLS + auth.

## Décision / Action suivante

✅ Fix appliqué et validé sur l'API : `http://100.114.117.104:8000/` répond 200.

❓ ComfyUI nécessite un restart pour activer `--listen 0.0.0.0`. À faire avec :
```
# Stopper ComfyUI manuel (Task Manager / kill PID 44076 ou 44824)
# Puis relancer toute la stack via :
python start.py --no-reload
```

Le user peut aussi tester côté autre machine Tailscale :
```
curl http://100.114.117.104:8000/         # API
curl http://100.114.117.104:8188/         # ComfyUI (après restart)
curl http://100.114.117.104:8000/docs     # Swagger
```

## Annexes

- **Code modifié** : `start.py` lignes ~389-394 (api_host) + ~457-466 (comfy_args)
- **Doc** : `CLAUDE.md` section "Key environment variables"
- **Logs vérification** : `logs/api.log` (recherche "Uvicorn running on http://0.0.0.0:8000")
- **Tailscale CLI** : `C:\Program Files\Tailscale\tailscale.exe ip -4`
