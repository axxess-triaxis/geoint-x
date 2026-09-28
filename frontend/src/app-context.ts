import { createContext, useContext } from 'react'
import type { Meta, Role } from './types'

export interface AppCtx {
  meta: Meta | null
  role: Role
  user: string
  setRole: (r: Role) => void
  /** Bumped after any mutation so views refetch. */
  version: number
  bump: () => void
}

export const Ctx = createContext<AppCtx | null>(null)

export function useApp(): AppCtx {
  const c = useContext(Ctx)
  if (!c) throw new Error('AppCtx missing')
  return c
}

export const DEMO_USERS: Record<Role, string> = {
  analyst: 'a.sharma (GIS analyst)',
  reviewer: 'r.das (Circle Officer)',
  supervisor: 's.bora (District supervisor)',
}
