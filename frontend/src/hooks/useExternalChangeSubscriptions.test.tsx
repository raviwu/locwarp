import { describe, it, expect, vi } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { createWsRouter } from '../adapters/ws/router'
import { useExternalChangeSubscriptions } from './useExternalChangeSubscriptions'

describe('useExternalChangeSubscriptions on WsRouter', () => {
  it('bookmarks_changed triggers refresh + toast', () => {
    const ws = createWsRouter()
    const onBookmarks = vi.fn()
    const onRoutes = vi.fn()
    renderHook(() => useExternalChangeSubscriptions(ws, { onBookmarks, onRoutes }))
    act(() => { ws.dispatch({ type: 'bookmarks_changed', reason: 'external_update' }) })
    expect(onBookmarks).toHaveBeenCalledTimes(1)
    expect(onRoutes).not.toHaveBeenCalled()
  })

  it('routes_changed triggers the routes callback only', () => {
    const ws = createWsRouter()
    const onBookmarks = vi.fn()
    const onRoutes = vi.fn()
    renderHook(() => useExternalChangeSubscriptions(ws, { onBookmarks, onRoutes }))
    act(() => { ws.dispatch({ type: 'routes_changed', reason: 'external_update' }) })
    expect(onRoutes).toHaveBeenCalledTimes(1)
    expect(onBookmarks).not.toHaveBeenCalled()
  })
})
