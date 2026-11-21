import { motion } from 'motion/react'
import { initials } from './data.js'

export default function ContactResults({ scenario }) {
  const [firstContact, secondContact] = scenario.path
  const contacts = [
    {
      ...scenario.target,
      context: scenario.target.context,
      approach: 'Demandez à ' + firstContact.name + ' de vous présenter ' + secondContact.name + ', qui pourra ensuite vous mettre en relation.',
      label: 'Contact cible',
    },
    {
      ...firstContact,
      context: firstContact.why + '. Un premier point d’entrée pour parler de votre projet.',
      approach: 'Écrivez-lui en rappelant votre lien commun, puis demandez des conseils et une introduction auprès de ' + secondContact.name + '.',
      label: 'À contacter en premier',
    },
    {
      ...secondContact,
      context: secondContact.why + '. Ce contact peut vous rapprocher de ' + scenario.target.name + '.',
      approach: 'Passez par ' + firstContact.name + ' pour une présentation, puis expliquez votre démarche avant de demander une mise en relation.',
      label: 'Relais dans le réseau',
    },
  ]

  return (
    <motion.div className="contact-results" initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }}>
      <table className="contact-table">
        <caption className="sr-only">Contacts suggérés, contexte et conseils pour les contacter</caption>
        <thead><tr><th scope="col">Contact</th><th scope="col">Contexte & prise de contact</th></tr></thead>
        <tbody>
          {contacts.map((contact) => (
            <tr key={contact.name}>
              <th scope="row">
                <div className="contact-identity">
                  <span className="contact-avatar" aria-hidden="true">{initials(contact.name)}</span>
                  <div><strong>{contact.name}</strong><span className="contact-meta">{contact.meta}</span><span className="contact-label">{contact.label}</span></div>
                </div>
              </th>
              <td><p>{contact.context}</p><p className="contact-approach"><strong>Pour le contacter</strong> {contact.approach}</p></td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="contact-results-footer">{contacts.length} contacts · profils fictifs de démonstration</div>
    </motion.div>
  )
}
