import { useEffect } from 'react'

const CONTACT = 'gaspardobert70@gmail.com'

function LegalLink({ to, children, onNavigate }) {
  return <a href={to} onClick={(event) => { if (!event.metaKey && !event.ctrlKey && !event.shiftKey && !event.altKey && event.button === 0) { event.preventDefault(); onNavigate(to) } }}>{children}</a>
}

export default function LegalPage({ kind, onNavigate }) {
  const privacy = kind === 'privacy'
  const title = privacy ? 'Politique de confidentialité' : 'Mentions légales'
  useEffect(() => {
    const previousTitle = document.title
    document.title = title + ' — Abelink'
    return () => { document.title = previousTitle }
  }, [title])

  return (
    <main className="legal-page">
      <div className="wrap legal-layout">
        <aside className="legal-sidebar">
          <LegalLink to="/" onNavigate={onNavigate}>← Retour à l’accueil</LegalLink>
          <nav aria-label="Informations légales">
            <LegalLink to="/mentions-legales" onNavigate={onNavigate}>Mentions légales</LegalLink>
            <LegalLink to="/confidentialite" onNavigate={onNavigate}>Confidentialité</LegalLink>
          </nav>
          <span>Mis à jour le 21 novembre 2026</span>
        </aside>
        <article className="legal-content">
          <span className="section-kicker">En toute transparence</span>
          <h1>{title}</h1>
          <p className="legal-intro">{privacy ? 'Comprendre quelles données circulent lorsque vous visitez ce site, demandez une démo ou rejoignez la waitlist.' : 'Les informations relatives au site abelink.app et à son utilisation.'}</p>
          {privacy ? <>
            <section><h2>01. À qui s’adresser ?</h2><p>Le responsable du traitement est Matheo Andre Maurice Le Devehat, entrepreneur individuel. Son établissement est situé au 32 rue de la Tombe-Issoire, 75014 Paris. Pour toute question relative aux données personnelles ou pour exercer vos droits, écrivez à <a href={'mailto:' + CONTACT}>{CONTACT}</a>.</p><p>Ses informations d’identification figurent dans les <LegalLink to="/mentions-legales" onNavigate={onNavigate}>mentions légales</LegalLink>.</p></section>
            <section><h2>02. Les données utilisées sur ce site</h2>
              <dl className="privacy-data">
                <div><dt>Demande de démo</dt><dd>Votre nom, votre email professionnel et le nom de votre réseau alumni sont demandés pour recevoir votre demande et vous répondre. Ces champs sont nécessaires à l’envoi du formulaire. Le service FormSubmit transmet la demande par email.</dd></div>
                <div><dt>Waitlist élèves</dt><dd>L’email saisi sur cette page est optionnel. Il est transmis à Stripe pour préremplir la page de paiement. Stripe collecte les informations nécessaires au paiement selon sa propre politique. Le site Abelink ne reçoit pas vos coordonnées de carte bancaire.</dd></div>
                <div><dt>Démo interactive</dt><dd>Les recherches et profils de la démo sont simulés dans votre navigateur. Aucun compte LinkedIn n’est connecté et aucun message n’est envoyé aux personnes présentées. Le texte de votre recherche n’est pas transmis à l’outil de mesure d’audience.</dd></div>
                <div><dt>Navigation et interactions</dt><dd>PostHog est initialisé au chargement du site pour mesurer les visites et certaines actions : ouverture du formulaire, utilisation de la démo et clic vers la waitlist. Il peut traiter des identifiants techniques, le contexte de navigation et les caractéristiques du navigateur. Les noms, emails et contenus des formulaires ne sont pas ajoutés à ces événements par le site.</dd></div>
              </dl>
            </section>
            <section><h2>03. Stockage local et mesure d’audience</h2><p>La configuration actuelle de PostHog utilise le stockage local du navigateur. L’enregistrement de sessions, la capture automatique des interactions et les profils de personnes sont désactivés. Les paramètres et fragments sont retirés de l’adresse de page envoyée dans les événements.</p><p>La mesure d’audience démarre actuellement sans écran de consentement. Cette description du fonctionnement ne constitue pas une déclaration d’exemption : les conditions d’utilisation des traceurs et, le cas échéant, un mécanisme de consentement doivent être validés par l’éditeur.</p></section>
            <section><h2>04. Destinataires et prestataires</h2><p>Les demandes de démo sont destinées à l’équipe Abelink et transitent par FormSubmit et la messagerie de réception. Stripe prend en charge le paiement de la waitlist. PostHog traite les événements de mesure d’audience via le domaine t.abelink.app. L’infrastructure du site repose sur Hetzner, avec Cloudflare en frontal.</p><p>Les lieux de traitement, les sous-traitants ultérieurs et les garanties applicables à d’éventuels transferts hors de l’Espace économique européen doivent encore être confirmés auprès de ces prestataires.</p></section>
            <section><h2>05. Bases légales et conservation</h2><p>Les finalités sont la réponse aux demandes de démo, la gestion de l’accès anticipé et du paiement, ainsi que la compréhension de l’utilisation du site. Les bases légales de chaque traitement et les durées de conservation dans les services et messageries concernés restent à documenter par l’éditeur. Aucune durée chiffrée non vérifiée n’est annoncée ici.</p></section>
            <section><h2>06. Vos droits</h2><p>Selon les conditions applicables à chaque traitement, vous pouvez demander l’accès à vos données, leur rectification, leur effacement, la limitation du traitement, leur portabilité ou vous opposer à leur utilisation. Lorsqu’un traitement repose sur votre consentement, vous pouvez le retirer.</p><p>Adressez votre demande à <a href={'mailto:' + CONTACT}>{CONTACT}</a>, en précisant le contexte de votre démarche. Vous pouvez également déposer une réclamation auprès de la Commission nationale de l’informatique et des libertés (CNIL).</p></section>
          </> : <>
            <section><h2>01. Éditeur du site</h2><p>Le site Abelink est édité par Matheo Andre Maurice Le Devehat, entrepreneur individuel.</p><dl className="privacy-data"><div><dt>Adresse de l’établissement</dt><dd>32 rue de la Tombe-Issoire, 75014 Paris, France</dd></div><div><dt>Immatriculation</dt><dd>SIREN : 947 473 880 · SIRET du siège : 947 473 880 00021</dd></div><div><dt>Activité</dt><dd>Conseil en systèmes et logiciels informatiques · APE 62.02A</dd></div><div><dt>Directeur de la publication</dt><dd>Matheo Andre Maurice Le Devehat</dd></div><div><dt>Contact</dt><dd><a href={'mailto:' + CONTACT}>{CONTACT}</a></dd></div></dl><div className="legal-notice"><strong>Informations restant à confirmer</strong><p>Le numéro de téléphone de l’éditeur et son numéro de TVA, s’il est applicable, ne figurent pas dans le document de situation Sirene du 17 septembre 2024. Ils ne sont donc pas indiqués ici.</p></div></section>
            <section><h2>02. Hébergement</h2><p>Le site est hébergé sur une infrastructure Hetzner, avec Cloudflare en frontal. La dénomination complète, l’adresse et le téléphone de l’hébergeur contractuel doivent être confirmés et renseignés par l’éditeur.</p></section>
            <section><h2>03. Contenus et illustrations</h2><p>Les textes, éléments graphiques et illustrations du site sont présentés pour faire découvrir le projet Abelink. Toute réutilisation doit respecter les droits applicables. Les marques et noms d’entreprises cités restent ceux de leurs titulaires ; leur présence dans une démonstration ne signifie pas qu’ils sont partenaires d’Abelink.</p></section>
            <section><h2>04. Démonstration du service</h2><p>La démo interactive est une simulation utilisant des profils fictifs et des scénarios prédéfinis. Elle n’effectue pas de recherche réelle sur LinkedIn, ne se connecte pas à votre réseau et n’envoie aucune sollicitation. Les résultats ne constituent pas une promesse de stage, d’emploi ou d’introduction.</p></section>
            <section><h2>05. Données personnelles</h2><p>Le fonctionnement des formulaires, du paiement et de la mesure d’audience est décrit dans notre <LegalLink to="/confidentialite" onNavigate={onNavigate}>politique de confidentialité</LegalLink>.</p></section>
            <section><h2>06. Nous contacter</h2><p>Pour signaler un problème ou poser une question sur le site : <a href={'mailto:' + CONTACT}>{CONTACT}</a>.</p></section>
          </>}
        </article>
      </div>
    </main>
  )
}
