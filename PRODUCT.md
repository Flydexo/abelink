# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

- **Alumni et associations alumni (contributeurs principaux de la base et acheteurs B2B)** : anciens élèves et responsables d’associations alumni d’écoles en France, qui fournissent et alimentent la base de données du réseau (parcours, expériences, liens de proximité, disponibilité) tout en valorisant leur communauté.
- **Étudiants (utilisateurs bénéficiaires avec inscription directe)** : étudiants (ex. en recherche de stage de césure, d’exploration métier ou de conseils pour lancer un projet) qui peuvent s’inscrire eux-mêmes pour accéder à la base, formuler leur recherche et profiter du réseau sans passer des heures à cold-messager sur LinkedIn.

## Product Purpose

Abelink met en relation étudiants et alumni en s’appuyant sur une base de données réseau alimentée par les alumni (et leurs associations), tout en permettant aux étudiants de s’inscrire directement pour en profiter.

À partir d’une recherche formulée en langage naturel, Abelink repère les alumni pertinents, identifie le chemin d’introduction le plus court via des liens partagés (club, promotion, mentorat, incubateur), et propose un plan d’action en trois étapes avec un message d’introduction prêt à envoyer.

Sur la vitrine actuelle, l’objectif est de faire voir ce mécanisme dès l’accueil et de convertir les responsables alumni vers une demande de démo sur leur réseau.

## Positioning

Contrairement aux annuaires alumni statiques et aux recherches manuelles sur LinkedIn qui laissent l’étudiant seul face à des inconnus à démarcher à froid, Abelink combine une base alimentée côté alumni (avec consentement et contrôle de partage) et un accès ouvert par inscription côté étudiants pour tracer automatiquement un **chemin d’introduction chaud** plutôt qu’une simple liste de contacts froids.

## Operating Context

- **Périmètre actuel du dépôt** : vitrine 100 % statique (`https://abelink.app` en production sur `main`, `https://dev.abelink.app` sur `dev`), intégrant une démonstration interactive côté client et une modale de demande de démo via FormSubmit.
- **MVP et parcours complet** : le MVP opérationnel (application connectée avec alimentation de la base côté alumni, inscription directe des étudiants, backend et parcours de paiement) est en cours de construction ou géré séparément de cette vitrine ; `HACKATHON_TODO.md` suit les jalons à couvrir (multi-pages, chemin vers le paiement, pages légales, traction).
- **Marché et langue** : offre et communication 100 % en français, ancrées dans les usages des écoles et grandes écoles françaises (césure, 2A, promotions, clubs étudiants, mentorat).

## Capabilities and Constraints

- **Capacités visibles dans la vitrine** : saisie libre ou sélection de scénarios types, simulation d’exploration multi-sources (LinkedIn, réseau alumni, expériences passées), affichage du contact cible, du chemin d’introduction étape par étape et de chemins alternatifs, plan d’action daté (aujourd’hui / sous 3 jours / sous 7 jours), message d’introduction copiable, et formulaire de demande de démo (`nom`, `email professionnel`, `réseau alumni`).
- **Inscription étudiants (objectif produit confirmé)** : les étudiants doivent pouvoir s’inscrire directement pour profiter du réseau alimenté par les alumni ; aucun parcours d’inscription étudiant n’est encore implémenté dans cette vitrine statique.
- **Contraintes techniques** : aucun backend ni base de données dans ce dépôt ; la démonstration repose sur des données statiques locales (`src/data.js`).
- **Contraintes de confidentialité et analytics** : PostHog est configuré via `https://t.abelink.app` avec autocapture, enregistrement de session, page-leave et profils personnels désactivés ; aucune donnée saisie par l’utilisateur (nom, email, nom du réseau, recherche libre ou presse-papiers) ne doit être envoyée dans la télémétrie (`docs/ANALYTICS.md`).
- **Éléments explicitement non décidés ou absents** : modalités exactes de tarification et de paiement (B2B associations vs accès étudiant), informations légales et politique de confidentialité définitives (les liens du footer renvoient actuellement vers `#top`), et intégration réelle avec un annuaire ou LinkedIn.

## Brand Commitments

- **Nom** : Abelink (`abelink.app`).
- **Langue et registre** : français uniquement (`lang="fr"`), vouvoiement professionnel et clair sur la vitrine, vocabulaire concret issu de la vie étudiante et associative française.
- **Respect des alumni** : les alumni alimentent volontairement la base et gardent la main sur ce qu’ils acceptent de partager ; chaque mise en relation passe par un contact de proximité et jamais par du démarchage non consenti.

## Evidence on Hand

- **Scénarios de démonstration (`src/data.js`)** : 4 scénarios complets (stage de césure énergie, product manager santé, quant en banque d’investissement, lancement startup fintech) utilisant des personas et métriques **100 % fictifs** (aucune personne réelle).
- **Absences à ne pas fabriquer** : aucun témoignage client réel, aucun logo d’école ou d’association partenaire confirmé, aucune étude de cas, aucun chiffre de traction publique ni grille tarifaire validée.

## Product Principles

- **La base vit par les alumni, la valeur circule vers les étudiants** : inciter les alumni à alimenter le réseau en respectant leur contrôle, tout en permettant aux étudiants de s’inscrire simplement pour en bénéficier.
- **La chaleur avant le volume** : un chemin d’introduction court et légitime (club, promo, mentorat) vaut mieux qu’une longue liste de profils inconnus à contacter à froid.
- **Actionnable immédiatement** : chaque recherche débouche sur un plan concret et un message prêt à envoyer plutôt que sur une impasse de profils.
- **Rigueur factuelle et sobriété sur les données** : ne jamais inventer de clients, de chiffres ou de profils réels, et ne collecter aucune donnée personnelle dans la télémétrie.
