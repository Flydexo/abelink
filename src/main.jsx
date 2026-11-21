import { createRoot } from 'react-dom/client'
import { MotionConfig } from 'motion/react'
import App from './App.jsx'
import { initializeAnalytics } from './analytics.js'
import './styles.css'

initializeAnalytics()

createRoot(document.getElementById('root')).render(
  <MotionConfig reducedMotion="user" transition={{ type: 'spring', bounce: 0, duration: 0.5 }}>
    <App />
  </MotionConfig>,
)
