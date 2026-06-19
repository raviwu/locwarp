import React, { createContext, useContext } from 'react'
import type { ApiGateway } from '../contract/apiGateway'
import type { WsRouter } from '../ports/WsRouter'

export interface Services {
  api: ApiGateway
  ws: WsRouter
}

const ServicesContext = createContext<Services | null>(null)

export function ServicesProvider(
  { value, children }: { value: Services; children: React.ReactNode },
) {
  return <ServicesContext.Provider value={value}>{children}</ServicesContext.Provider>
}

export function useServices(): Services {
  const ctx = useContext(ServicesContext)
  if (ctx === null) {
    throw new Error('useServices must be used within a ServicesProvider')
  }
  return ctx
}
