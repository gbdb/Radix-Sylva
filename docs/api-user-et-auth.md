# Utilisateur Django et authentification API — Radix Sylva

Ce document décrit comment le modèle **`User`** de Django s’intègre au projet, et comment l’**API REST** contrôle (ou non) l’accès. Radix n’expose **pas** d’API « login utilisateur » ni de JWT : l’accès public en lecture est ouvert, et les routes sensibles reposent sur une **clé partagée** optionnelle.

---

## Modèle `User` (Django standard)

- **`AUTH_USER_MODEL`** n’est **pas** surchargé dans `radixsylva/settings.py` : Radix utilise le modèle par défaut **`django.contrib.auth.models.User`**.
- Tables PostgreSQL habituelles : `auth_user`, `auth_group`, `auth_permission`, tables de liaison, `django_session`, etc.

Champs utiles à connaître sur `User` (résumé) :

| Champ | Rôle |
|--------|------|
| `username` | Identifiant unique |
| `password` | Hash (jamais en clair) |
| `email` | Optionnel |
| `is_staff` | Accès à l’**interface d’administration** Django (`/admin/`) |
| `is_superuser` | Tous les droits dans l’admin |
| `is_active` | Compte désactivé si `False` |

Création des comptes : **`createsuperuser`**, l’admin Django, ou scripts — il n’y a pas d’endpoint API public d’inscription dans ce dépôt.

---

## Où le `User` intervient dans Radix (hors API REST)

### 1. Administration Django (`/admin/`)

- Authentification **session** classique : formulaire login Django, cookie de session.
- Seuls les utilisateurs avec **`is_staff=True`** (en pratique souvent un superuser) accèdent à l’admin.
- L’admin enregistre les modèles botaniques (`Organism`, `DataImportRun`, etc.) — voir `botanique/admin.py`.

### 2. Modèle métier `DataImportRun`

- Champ optionnel **`user`** : `ForeignKey` vers `AUTH_USER_MODEL`, `null=True`, `on_delete=SET_NULL`.
- Sert à **tracer** qui a lancé un import ou une opération lorsque cette information est renseignée (ex. depuis l’admin ou une commande qui passerait l’utilisateur).
- **`related_name`** : `radix_data_import_runs`.

Les commandes de management qui créent un `DataImportRun` peuvent laisser `user` vide si aucun contexte utilisateur n’est disponible.

---

## Authentification de l’API REST (`/api/v1/`)

### Configuration globale (`radixsylva/settings.py`)

- **`REST_FRAMEWORK['DEFAULT_PERMISSION_CLASSES']`** : **`AllowAny`** — par défaut, les vues n’exigent **pas** un utilisateur Django authentifié.
- **`DEFAULT_AUTHENTICATION_CLASSES`** n’est **pas** redéfinie : Django REST Framework utilise ses classes par défaut (**SessionAuthentication**, **BasicAuthentication**). Elles ne sont utiles que si une vue exige une authentification utilisateur ; ce n’est **pas** le cas des vues actuelles documentées ci-dessous.

Il n’y a **pas** dans le dépôt de : Token DRF, JWT, OAuth, ou clé API liée au modèle `User`.

---

## Contrôle d’accès par endpoint

### Lecture publique (sans clé, sans `User`)

Ces vues déclarent explicitement **`AllowAny`** :

| Ressource | Chemin (sous `/api/v1/`) | Auth |
|-----------|--------------------------|------|
| Organismes | `organisms/`, `organisms/<pk>/` | Aucune |
| Cultivars | `cultivars/`, … | Aucune |
| Amendements | `amendments/`, … | Aucune |

Comportement : tout client HTTP peut lire les données (pagination DRF, etc.).

### Routes « sync » et demande d’espèce — clé **`X-Radix-Sync-Key`** (pas le `User`)

Les vues suivantes utilisent **`HasSyncAPIKey`** (`botanique/permissions.py`) :

- `GET` **`sync/meta/`**, **`sync/amendments/`**, **`sync/organisms/`**, **`sync/cultivars/`**, **`sync/companions/`**, **`sync/deleted/`**
- `POST` **`organism-request/`**

Logique :

1. Lire la variable d’environnement **`RADIX_SYLVA_SYNC_API_KEYS`** (liste de chaînes, souvent une seule clé, séparées par des virgules dans `.env`).
2. Si la liste est **vide** : **`HasSyncAPIKey` autorise tout le monde** (pratique en développement local uniquement ; **à éviter en production exposée**).
3. Si la liste est **non vide** : le client doit envoyer l’en-tête HTTP  
   **`X-Radix-Sync-Key: <une des clés configurées>`**  
   Sinon : refus (message du type *« Clé sync manquante ou invalide »*).

Cette clé est **indépendante** du modèle `User` : aucun `Authorization: Bearer`, aucun couple user/mot de passe Django n’est requis pour ces routes.

---

## Récapitulatif

| Question | Réponse |
|----------|---------|
| L’API utilise-t-elle `User` pour protéger les lectures publiques ? | **Non** (`AllowAny`). |
| Comment sécuriser sync / `organism-request` en prod ? | Définir **`RADIX_SYLVA_SYNC_API_KEYS`** et envoyer **`X-Radix-Sync-Key`**. |
| Y a-t-il un endpoint « token utilisateur » pour l’API ? | **Non** dans ce dépôt. |
| À quoi sert `User` ? | **Admin Django** (`is_staff`), et **optionnellement** traçabilité sur **`DataImportRun.user`**. |

---

## Références code

- `radixsylva/settings.py` — `INSTALLED_APPS` (`django.contrib.auth`), `REST_FRAMEWORK`, `RADIX_SYLVA_SYNC_API_KEYS`
- `botanique/permissions.py` — `HasSyncAPIKey`
- `botanique/api_views.py` — `AllowAny` vs `HasSyncAPIKey`
- `botanique/sync_views.py` — endpoints sync + `HasSyncAPIKey`
- `botanique/models.py` — `DataImportRun.user`
- `README.md` et `docs/env-et-deploiement.md` — variable `RADIX_SYLVA_SYNC_API_KEYS` et en-tête côté client (ex. BIOT)
