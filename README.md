# Abelink

Le dépôt contient une vitrine Vite/React/Motion et une application alumni avec
un backend Python FastAPI : recherche hybride PostgreSQL/pgvector, graphe
NetworkX, enrichissement web et agent conversationnel connecté à Vertex AI.

## Structure et développement local

- `src/` : frontend et interface connectée sous `/app`.
- `backend/` : API REST, streaming SSE, serveur MCP, services IA et tests Python.
- `docker-compose.yml` : déploiement de la vitrine seule, via nginx.
- `docker-compose.backend.dev.yml` : définition du service backend dev.
- `docker-compose.dev.yml` : stack complète frontend + backend pour les pushes
  sur `dev` ; sa présence ne signifie pas que le backend est déjà déployé.

Frontend : `npm ci`, puis `npm run dev` sur `127.0.0.1:5173`.
Validation : `npm run build`. Aucun script npm de test ou de lint.

Pour une démo locale sans fournisseurs externes, créer le venv du backend et
installer ses dépendances, puis lancer le script depuis la racine :

```bash
python3 -m venv backend/.venv
backend/.venv/bin/python -m pip install -e "./backend[dev]"
bash backend/run_local_demo.sh
```

Le script démarre FastAPI sur `127.0.0.1:8000` et Vite sur `127.0.0.1:5173`.
Les tests backend sont configurés dans `backend/pyproject.toml` ; les tests live
sont exclus par défaut. La configuration locale générale est décrite par
`backend/.env.example` ; ne pas copier ses valeurs de démonstration dans Dokploy.

Le formulaire de demande de démo utilise FormSubmit (`src/DemoSheet.jsx`).
Analytics et plan de marquage : [docs/ANALYTICS.md](docs/ANALYTICS.md).

## Déploiement et administration

- Consignes pour les agents : [AGENTS.md](AGENTS.md).
- Environnements, déploiements, DNS/TLS et maintenance : [guide d'exploitation](docs/DEPLOYMENT.md).
- `main` → production sur `abelink.app` ; `dev` → développement sur `dev.abelink.app`.
- Administration Dokploy : `https://dokploy.abelink.app`.

### Backend dev : variables à fournir dans Dokploy

La cible est le Compose existant `web` du projet `abelink`, environnement `dev`,
branche `dev`, configuré pour utiliser `./docker-compose.dev.yml`. Cette stack
contient les services `web`, `backend` et `database` (PostgreSQL avec pgvector) ;
les secrets restent côté serveur et ne sont pas transmis au frontend. Ne pas les ajouter à la production.
Vérifier la ressource et son environnement avant toute écriture.

**Les valeurs réelles doivent être enregistrées dans le champ d’environnement
(`env`) du Compose `web` de dev dans Dokploy.** Un `.env` local ou un fichier exemple
dans Git ne configure pas le serveur. Le modèle public à consulter est
[`backend/deploy/dev.env.example`](backend/deploy/dev.env.example) ; ne jamais
le remplir avec des secrets.

| Variable à enregistrer dans Dokploy | Valeur attendue |
| --- | --- |
| `POSTGRES_PASSWORD` | Obligatoire : mot de passe PostgreSQL dev généré en privé (32 octets aléatoires encodés en hexadécimal) ; conserver sa valeur après initialisation du volume. |
| `GOOGLE_CLOUD_PROJECT` | Obligatoire : identifiant du projet Google Cloud autorisé. |
| `GOOGLE_CLOUD_LOCATION` | `global` par défaut, à adapter aux modèles autorisés. |
| `GEMMA_MODEL` | Obligatoire : identifiant du modèle génératif disponible dans ce projet. |
| `EMBEDDING_MODEL` | Obligatoire : modèle acceptant une sortie de 768 dimensions. |
| `GOOGLE_APPLICATION_CREDENTIALS_JSON` | Obligatoire pour ce Compose : JSON complet des credentials Google, compact, entre apostrophes dans le document dotenv, avec les échappements JSON conservés. |
| `AUTH_SECRET` | Obligatoire : secret JWT aléatoire propre au dev ; à générer en privé si absent, sans remplacer un secret existant. |
| `LINKCS_IMPORT_TOKEN` | Facultative en dev public, où elle n’est pas utilisée ; à conserver pour un futur mode protégé. |
| `TAVILY_API_KEY` | Facultative : clé Tavily pour le recours à la recherche payante. |
| `PREFER_FREE_SEARCH` | `true` par défaut : recherche gratuite avant Tavily. |
| `LINKEDIN_LI_AT` | Facultative : laisser vide ; le cookie ne sert que de recours pour certaines photos, pas à la recherche générale. |

Le Compose déploie sa propre base PostgreSQL 16 avec pgvector, sans port publié,
et conserve ses données dans le volume nommé `postgres_data` du projet Compose.
Le backend attend que la base soit prête, puis applique ses migrations au démarrage.
`DATABASE_URL` est construit automatiquement vers `database:5432/abelink_dev` :
aucune base externe ni URL de connexion à fournir pour ce déploiement.
Ne jamais supprimer le volume ni changer `POSTGRES_PASSWORD` après initialisation
sans une procédure de sauvegarde et de rotation SQL autorisée.

Le Compose injecte les variables applicatives dans le conteneur. Le JSON Google
est transmis par un secret Compose, injecté sous `/run/secrets/google-adc.json` ;
`GOOGLE_APPLICATION_CREDENTIALS` pointe vers ce fichier. Ce chemin seul ne
remplace pas le contenu JSON à fournir dans Dokploy.

Les valeurs suivantes sont fixées dans le Compose, et non à fournir à nouveau :
`DEMO_MODE=false`, `ALLOW_DEMO_AUTH=false`, `ALLOW_PUBLIC_ACCESS=true`, `EMBEDDING_DIM=768`,
`CORS_ORIGINS=https://dev.abelink.app`, `PUBLIC_API_URL=https://dev.abelink.app`
et `ENRICHMENT_CACHE_PATH` vide. Les ajouter au champ `env` ne remplace pas les
valeurs littérales du Compose.

### Consignes de configuration pour les agents

1. Lire `AGENTS.md`, le runbook et le [guide backend dev](backend/deploy/README.md).
2. Demander les valeurs manquantes via la saisie privée de secrets, jamais dans
   le chat ; ne pas afficher les credentials ou le document dotenv complet.
3. Lorsque la configuration est autorisée, retrouver le Compose `web` dans
   `abelink` → `dev`, lire son environnement en privé et y fusionner les clés
   fournies, sans effacer les autres variables ni faire tourner les secrets.
4. Enregistrer le document obtenu dans le champ `env` de cette ressource Dokploy,
   puis vérifier uniquement les noms et la présence des clés requises. Vérifier
   aussi que le JSON Google peut être transmis au secret Compose.
5. Ne déclarer « variables configurées » que si elles ont réellement été
   sauvegardées dans Dokploy. Sinon, indiquer ce qui manque. Une modification
   de documentation ne vaut pas autorisation de configurer ou de déployer.

Le routage proposé réutilise `dev.abelink.app` pour `/api`, `/health`, `/mcp`
et `/openapi.json`, sans publier le port 8000. La procédure complète et les
limites du mode public sont dans le guide backend : données partagées, coûts
des fournisseurs, données initiales et cohérence des embeddings.
Sauvegarder les variables ne lance pas le déploiement. Une fois les variables
requises enregistrées, un push sur `dev` déclenche automatiquement la stack
complète ; `main` conserve `./docker-compose.yml`, sans backend. Les agents ne
doivent ni pousser ni lancer un déploiement manuel sans demande correspondante.

## Importer un export Abelink ou LinkCS

Ouvrir `/app/import-linkcs` ou l’onglet **Import de données** de l’application :

1. Sélectionner le `.json` original créé par `scripts.export_import_bundle export`
   (`version: 1`, `profiles`, `edges`), ou une liste d’objets LinkCS.
2. Saisir la clé privée `LINKCS_IMPORT_TOKEN` pour un export Abelink, même en dev
   public. Seules les listes LinkCS restent accessibles sans clé en dev public.
3. Confirmer que vous êtes autorisé à importer ces données, puis lancer l’import.

Les exports Abelink jusqu’à 1 Gio sont transférés par blocs de 4 Mio puis lus
par lots dans une transaction PostgreSQL. Les profils et relations existants
ne sont pas remplacés ; les relations fournies sont importées directement sans
en inférer de nouvelles. Ce format ne restaure pas les jetons ni le schéma SQL.

Pour les listes LinkCS, le backend accepte jusqu’à 10 Mio, 5 000 entrées et
100 000 relations générées. Les champs
usuels LinkCS sont reconnus : `login`, `nom_complet` ou `prenom`/`nom`,
`promotion`, emails, associations, clubs, biographie et réseaux sociaux.
Il ajoute les nouveaux profils et liens sans écraser les données existantes,
puis recharge le graphe. Le bilan affiche les ajouts et doublons ignorés.
L’import ne lance aucun appel IA payant et ne conserve pas le fichier brut.
PostgreSQL applique l’import dans une transaction ; le mode mémoire est
explicitement signalé, car ses données sont perdues au redémarrage.

L’API LinkCS est `POST /api/v1/linkcs/import`, multipart avec `file`,
`confirmed=true` et, uniquement en mode protégé, `X-LinkCS-Import-Token`.
Les transferts par blocs utilisent `/api/v1/linkcs/bundle`.

## Accès public en dev

À la demande du propriétaire, le Compose dev active `ALLOW_PUBLIC_ACCESS=true` :
chat, recherche, annuaire, import LinkCS et MCP sont accessibles sans compte,
cookie ni Bearer token. Un profil `Visiteur public` partagé est créé au démarrage
pour que le chat fonctionne aussi sur une base vide. Choisir un autre profil
change le contexte de recherche, pas une identité authentifiée. Sans relations
réelles dans le graphe, aucun chemin personnel ne peut être garanti.

Le MCP est disponible sur `/mcp` sans en-tête `Authorization` ; l’onglet
Claude & ChatGPT fournit la configuration sans token. Les routes de gestion
des tokens personnels ne sont pas exposées en mode public.

**Toute personne connaissant l’URL peut consulter et modifier les données via
les imports et déclencher des appels IA/recherche facturés au propriétaire.**
Il n’y a pas d’isolation privée par visiteur ni de quota anonyme ajouté ici.
Ne pas importer de données confidentielles. Hors du Compose dev, le mode public
reste désactivé par défaut ; la production n’est pas modifiée.

## Pages légales

- `/mentions-legales` et `/confidentialite` : informations légales et traitements du site.
- Informations à compléter avant finalisation : [docs/LEGAL.md](docs/LEGAL.md).
