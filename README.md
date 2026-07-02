# TorrentUploader (fork Upload-Assistant) — Upload custom YGG/C411 + Prowlarr anti-doublon

Ce dépôt est un fork/adaptation d’Upload-Assistant (L4G) avec un objectif précis :

- Conserver le Core de préparation (parsing release, MediaInfo/BDInfo, TMDb/IMDb, génération `.torrent` privé).
- Ajouter un mode “trackers custom” pour des formulaires d’upload web non-UNIT3D (multipart/form-data).
- Ajouter une étape anti-doublon via l’API Prowlarr avant de lancer la préparation.
- Offrir un système BBCode simple à adapter (templates YGG/C411, extensible).

## Ce que fait le script au quotidien (workflow)

Quand tu exécutes `upload.py` sur un fichier ou dossier :

1. (Optionnel) Vérifie si la release existe déjà sur le tracker cible via Prowlarr (anti-doublon).
2. Prépare les métadonnées :
   - détection type (MOVIE/TV), résolution, source, audio, etc.
   - récupération TMDb/IMDb (titre, année, synopsis, poster)
   - MediaInfo/BDInfo + screenshots + description de base
3. Génère un `.torrent` adapté au tracker (announce + source flag) et les fichiers de travail dans `tmp/<uuid>/`.
4. Génère une description BBCode spécifique au tracker (`[YGG]DESCRIPTION.txt`, `[C411]DESCRIPTION.txt`).
5. Upload via requête HTTP POST (multipart/form-data) :
   - `.torrent`
   - `.nfo` (si présent dans le dossier, sinon fallback)
   - champ description (BBCode)

## Architecture (les “grosses” fonctions / modules)

- `upload.py`
  - Point d’entrée CLI.
  - Orchestration complète : parsing args → pré-check Prowlarr → prep → upload trackers.
- `src/prep.py`
  - Cœur préparation : MediaInfo/BDInfo, nommage, screenshots, fetch TMDb/IMDb, création torrent, description de base.
- `src/trackers/COMMON.py`
  - Utilitaires partagés trackers, notamment :
    - `add_tracker_torrent(...)` : écrit le `.torrent` final avec announce + source flag.
    - `unit3d_edit_desc(...)` : pipeline de description côté trackers UNIT3D (conservé).
- `src/trackers/CUSTOM.py`
  - Trackers custom ajoutés :
    - `YGG` et `C411` (classes tracker plug-and-play côté `upload.py`)
  - Upload brut via `requests` :
    - cookies via env
    - CSRF optionnel (scraping d’un input hidden)
    - POST multipart/form-data
  - Génération BBCode via templates (YGG/C411).
- `src/prowlarr.py`
  - Dupe-check Prowlarr via `/api/v1/search` (header `X-Api-Key`).
- `src/bbcode.py`
  - Nettoyage BBCode historique + ajout d’un moteur template minimal :
    - `format_ygg(...)`, `format_c411(...)`
    - `BBCodeTemplateContext`

## Installation (prérequis)

- Python (idéalement 3.10+). Les dépendances sont dans `requirements.txt`.
- MediaInfo + ffmpeg installés (et `ffmpeg` dans le PATH sur Windows).
- (Optionnel) mono sous Linux si usage BDInfo.

Installation :

```bash
python -m pip install -U -r requirements.txt
```

Configuration Core Upload-Assistant :

- Copier `data/example-config.py` vers `data/config.py`
- Ajuster au minimum TMDb, image host, client torrent, etc.

## Configuration “custom trackers” (YGG / C411)

Le Core (TMDb, image host, etc.) reste dans `data/config.py`.
Les secrets et paramètres web des trackers custom passent par variables d’environnement (aucun secret en dur).

### Variables obligatoires par tracker

YGG :

- `YGG_ANNOUNCE_URL`
- `YGG_UPLOAD_URL`
- `YGG_COOKIE` (cookie header brut) ou `YGG_COOKIE_JSON` (JSON dict)

C411 :

- `C411_ANNOUNCE_URL`
- `C411_UPLOAD_URL`
- `C411_COOKIE` ou `C411_COOKIE_JSON`

### Variables optionnelles utiles

- `*_UPLOAD_PAGE_URL` : URL de la page d’upload (pour récupérer un token CSRF).
- `*_CSRF_FIELD_NAMES` : liste CSV des noms possibles (`csrf_token,_token,...`).
- `*_TORRENT_FIELD`, `*_NFO_FIELD`, `*_DESCRIPTION_FIELD` : noms des champs du formulaire.
- `*_FORM_FIELDS_JSON` : JSON dict de champs supplémentaires (catégories, flags, etc.).
- `*_SUCCESS_REGEX` : regex de validation si la réponse HTTP n’a pas un redirect explicite.
- `*_BBCODE_TEMPLATE` (texte inline) ou `*_BBCODE_TEMPLATE_PATH` (chemin fichier) : override template BBCode.

Exemple PowerShell (session courante) :

```powershell
$env:YGG_ANNOUNCE_URL="https://tracker.tld/announce.php?passkey=xxxx"
$env:YGG_UPLOAD_URL="https://tracker.tld/upload.php"
$env:YGG_COOKIE="uid=123; pass=abcdef; ...;"
```

## Configuration Prowlarr (anti-doublon)

Variables globales (valables pour tous les trackers) :

- `PROWLARR_URL` (ex: `http://127.0.0.1:9696`)
- `PROWLARR_API_KEY`

Optionnels :

- `PROWLARR_INDEXER_IDS` (CSV d’IDs indexers)
- `PROWLARR_CATEGORIES` (CSV)
- `PROWLARR_SEARCH_TYPE` (par défaut `search`)

Overrides par tracker possibles :

- `YGG_PROWLARR_URL`, `YGG_PROWLARR_API_KEY`, etc.
- `C411_PROWLARR_URL`, `C411_PROWLARR_API_KEY`, etc.

Arguments CLI :

- `--skip-prowlarr` : désactive le dupe-check Prowlarr.
- `--prowlarr-query "..."` : force la query envoyée à Prowlarr.

## Utilisation quotidienne (CLI)

Uploader vers YGG :

```bash
python upload.py "D:\Downloads\Ma.Release.1080p" --trackers ygg --unattended
```

Uploader vers C411 :

```bash
python upload.py "D:\Downloads\Ma.Release.1080p" --trackers c411 --unattended
```

Conseils :

- `--unattended` pour une exécution non interactive (utile via qBittorrent).
- `--skip-dupe-check` garde le comportement historique “je force l’upload malgré dupe”.
- La sortie de préparation est dans `tmp/<uuid>/` (torrent final, description, mediainfo…).

## Intégration qBittorrent (External Program) — Windows

Dans qBittorrent → Options → Téléchargements → “Exécuter un programme externe…” :

```text
powershell -NoProfile -ExecutionPolicy Bypass -Command "if ('%L' -match '^(YGG|ygg)$') { python 'C:\Users\angel\Desktop\DEV\TorrentUploader\upload.py' '%F' --trackers ygg --unattended } elseif ('%L' -match '^(C411|c411)$') { python 'C:\Users\angel\Desktop\DEV\TorrentUploader\upload.py' '%F' --trackers c411 --unattended }"
```

- `%F` = chemin du contenu
- `%L` = catégorie/label (mets le torrent en catégorie `YGG` ou `C411`)

## Ajouter un autre tracker “custom” (autre que YGG/C411)

Le mode custom est volontairement modulaire :

1. Duplique le modèle de classe dans `src/trackers/CUSTOM.py` :
   - ajouter une nouvelle classe `MONTRACKER(_CUSTOM_BASE)` avec un `tracker="MONTRACKER"`.
2. Dans `upload.py` :
   - ajouter `MONTRACKER` au mapping `tracker_class_map`
   - ajouter `MONTRACKER` dans `http_trackers`
   - (optionnel) dans le pré-check Prowlarr, autoriser `MONTRACKER`
3. Définir les variables d’environnement :
   - `MONTRACKER_ANNOUNCE_URL`
   - `MONTRACKER_UPLOAD_URL`
   - `MONTRACKER_COOKIE` (ou JSON)
   - et ajuster les champs de formulaire : `MONTRACKER_TORRENT_FIELD`, etc.

En pratique, le seul travail “spécifique tracker” est :

- Identifier les noms exacts des champs du formulaire HTML.
- Définir les champs additionnels (catégories / options) via `MONTRACKER_FORM_FIELDS_JSON`.
- Gérer CSRF si nécessaire (`MONTRACKER_UPLOAD_PAGE_URL` + `MONTRACKER_CSRF_FIELD_NAMES`).

## Sécurité (principes)

- Aucun secret n’est stocké dans le code : cookies, passkeys, clés API uniquement via variables d’environnement.
- Les logs évitent volontairement d’imprimer des cookies/passkeys.
- Recommandation : utiliser des cookies de session dédiés et renouvelables.

## Dépannage rapide

- Upload échoue (403/401) :
  - cookie expiré ou CSRF manquant → renseigner `*_UPLOAD_PAGE_URL` + `*_CSRF_FIELD_NAMES`.
- Le formulaire n’accepte pas les fichiers :
  - champs `*_TORRENT_FIELD` / `*_NFO_FIELD` incorrects.
- Prowlarr ne trouve rien :
  - vérifier `PROWLARR_URL`, `PROWLARR_API_KEY` et (si ID-based) ajuster `PROWLARR_SEARCH_TYPE`.
