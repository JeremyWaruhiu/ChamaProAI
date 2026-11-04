import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'

// The address volunteers are given is /signup; the app itself routes on the hash.
if (window.location.pathname.replace(/\/$/, '') === '/signup') window.location.replace('/#/signup')

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
