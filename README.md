# Abelink : landing page

Vite + React + Motion, 100 % statique.

- Dev : `npm run dev` (127.0.0.1:5173). Sur un disque exFAT, installer avec `npm install --no-bin-links`.
- Prod : `docker compose up -d --build` (nginx sur le port 80 du conteneur).
- Le formulaire de démo envoie via FormSubmit (voir `src/DemoSheet.jsx`).
- Analytics PostHog et plan de marquage : [docs/ANALYTICS.md](docs/ANALYTICS.md).

## Déploiement et administration

- Consignes pour les agents : [AGENTS.md](AGENTS.md).
- Environnements, déploiements, DNS/TLS et maintenance : [guide d'exploitation](docs/DEPLOYMENT.md).
- `main` → production sur `abelink.app` ; `dev` → développement sur `dev.abelink.app`.
- Administration Dokploy : `https://dokploy.abelink.app`.

## Pages légales

- `/mentions-legales` et `/confidentialite` : informations légales et traitements du site.
- Informations à compléter avant finalisation : [docs/LEGAL.md](docs/LEGAL.md).
