# Brief — Fix copie prompt sur origine non-sécurisée

Date : 2026-05-10
Auteur : architecte / PMO
Destinataire : claude-code dev
Sévérité : moyenne — bloque un workflow utilisateur (test manuel des prompts via copie + collage ComfyUI), mais workaround existe (loopback localhost).

## Symptôme

Bouton "Copier prompt" / "Copier négatif" de `data/benchmark-annotator.html` plante avec :

```
Échec copie : Cannot read properties of undefined (reading 'writeText')
```

…dès que l'annotateur est ouvert via une IP Tailscale (HTTP plain). Sur loopback `127.0.0.1` (origine sécurisée), tout fonctionne.

## Cause racine

`navigator.clipboard.writeText()` n'est **disponible que sur origines sécurisées** (HTTPS ou `http://localhost` / `http://127.0.0.1`). Sur Tailscale en HTTP plain (`http://100.x.x.x:8000/...`), l'objet `navigator.clipboard` est `undefined` → l'appel à `.writeText` lève l'erreur ci-dessus.

C'est un comportement **navigateur**, pas un bug de notre code. Le code actuel (à `data/benchmark-annotator.html:1413` environ) suppose la disponibilité de l'API Clipboard sans fallback.

## Fix attendu

### 1. Helper `copyToClipboard(text): Promise<boolean>`

Centraliser la logique de copie dans une fonction utilitaire (les boutons "Copier prompt" et "Copier négatif" appellent la même chose).

```js
async function copyToClipboard(text) {
  // Path 1 : API moderne, origine sécurisée
  if (navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch (e) {
      // continue vers fallback
    }
  }
  // Path 2 : fallback execCommand sur textarea hors-écran
  try {
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.setAttribute("readonly", "");
    ta.style.position = "fixed";
    ta.style.top = "-9999px";
    ta.style.left = "0";
    document.body.appendChild(ta);
    ta.select();
    ta.setSelectionRange(0, ta.value.length);
    const ok = document.execCommand("copy");
    document.body.removeChild(ta);
    if (ok) return true;
  } catch (e) {
    // continue vers fallback
  }
  // Path 3 : modale avec textarea pré-sélectionnée pour copie manuelle Ctrl+C
  showManualCopyDialog(text);
  return false;
}
```

### 2. Modale de fallback ultime `showManualCopyDialog(text)`

Si tous les paths échouent, ouvrir une modale simple (cohérente avec la cheat-sheet `?` déjà en place) avec :
- titre `Copier manuellement`
- une `<textarea>` lecture seule, sélectionnée automatiquement (`.select()` au mount)
- une consigne `Ctrl+C / ⌘C pour copier · Échap pour fermer`
- bouton `Fermer` ou Échap

C'est très rare — ne devrait se déclencher que sur des navigateurs très anciens.

### 3. Branchement

Modifier les handlers actuels des boutons "Copier prompt" et "Copier négatif" pour appeler `copyToClipboard(text)` à la place de l'appel direct à `navigator.clipboard.writeText`.

Conserver le feedback visuel actuel (`btn.classList.add("copied")` etc.) et l'afficher uniquement si `copyToClipboard` retourne `true`. Si `false`, ne pas afficher "copié" — la modale aura déjà fait office de feedback.

## Critères d'acceptation

- [ ] Bouton "Copier prompt" et "Copier négatif" fonctionnent en HTTP plain (testé via Tailscale ou via une IP réseau locale en HTTP)
- [ ] Aucune régression sur loopback `127.0.0.1` (path navigator.clipboard inchangé en pratique — le code passe par le path 1 quand il est dispo)
- [ ] Modale de fallback s'affiche correctement quand `execCommand` échoue (vérifiable en désactivant manuellement `navigator.clipboard` ET en interceptant `document.execCommand` pour retourner `false`)
- [ ] Pas de nouvelle dépendance JS / lib
- [ ] Code centralisé dans `copyToClipboard()` — les deux boutons appellent la même fonction

## Hors-scope

- Bascule de l'API en HTTPS (cert auto-signé / Tailscale Funnel / Caddy reverse-proxy) — c'est un sujet infra qui dépasse cet annotateur et impacte tout le projet. À aborder dans un cycle dédié si on multiplie les origines non-sécurisées.
- Refonte du système de modales (la cheat-sheet `?` peut servir de modèle pour la modale de fallback ; pas besoin d'introduire un framework).

## Fichiers concernés

- `data/benchmark-annotator.html` — modif uniquement (helper + handlers + modale)

Aucun fichier back, aucun test back impacté.

## Estimation dev

- Helper `copyToClipboard` + modale : ~20 min
- Branchement boutons + tests manuels (loopback + IP réseau) : ~10 min
- **Total ~30 min**

## Livrable

- Commit unique avec un message clair (ex `fix(annotator): fallback execCommand pour copie hors origine sécurisée`)
- Pas de nouveau rapport `docs/reports/` — c'est un fix mineur ; ajouter une **note de bas de page** dans `docs/reports/2026-05-09_phase-annotateur-v2.md` mentionnant le fix et son contexte (Tailscale)

## Points d'attention

- **`document.execCommand('copy')` est marqué obsolète** dans les specs modernes mais reste universellement supporté par tous les navigateurs cibles (Chrome / Firefox / Edge / Safari). C'est exactement le pattern recommandé pour le fallback non-sécurisé. Ne pas s'embarrasser de la dépréciation — il n'y a pas de remplaçant standard pour les origines non-sécurisées.
- **`textarea` hors-écran plutôt que `display:none`** : `display:none` ou `visibility:hidden` empêchent la sélection et la copie. Utiliser `position:fixed; top:-9999px` (ou `opacity:0` si tu préfères mais évite `display:none`).
- **Pas de boucle de retry** : si tous les paths échouent, montrer la modale et stop. Ne pas re-tenter.
- **Tests manuels suffisent** — pas de test automatique pour le presse-papier (ils sont fragiles côté CI).
