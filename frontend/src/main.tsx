import React from 'react'
import ReactDOM from 'react-dom/client'
import 'leaflet/dist/leaflet.css'
import App from './App'
import './styles.css'
import { I18nProvider } from './i18n'
import { ServicesProvider } from './contexts/ServicesContext'
import { useWsRouter } from './adapters/ws/useWsRouter'
import * as api from './services/api'

// Thin wrapper that calls useWsRouter() (a hook) to get the live router, then
// provides it app-wide via ServicesProvider. Keeps main.tsx free of hooks
// while ensuring ServicesProvider wraps the entire tree including App.
function ServicesRoot({ children }: { children: React.ReactNode }) {
  const { router, sendMessage, connected } = useWsRouter()
  return (
    <ServicesProvider value={{ api, ws: router, sendMessage, connected }}>
      {children}
    </ServicesProvider>
  )
}

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <I18nProvider>
      <ServicesRoot>
        <App />
      </ServicesRoot>
    </I18nProvider>
  </React.StrictMode>
)
