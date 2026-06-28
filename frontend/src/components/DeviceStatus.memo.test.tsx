import React from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render } from '@testing-library/react'

vi.mock('../i18n', () => ({ useT: () => (key: string) => key }))
vi.mock('../contexts/ServicesContext', () => ({
  useServices: () => ({
    api: {
      wifiTunnelDiscover: vi.fn().mockResolvedValue({ devices: [] }),
      wifiTunnelFindPort: vi.fn().mockResolvedValue({ ports: [] }),
      wifiRepair: vi.fn().mockResolvedValue({ name: 'iPhone', ios_version: '17.0' }),
    },
  }),
}))

import DeviceStatus from './DeviceStatus'

describe('DeviceStatus is React.memo (D3)', () => {
  beforeEach(() => { localStorage.clear() })

  it('default export is wrapped in React.memo', () => {
    // React.memo wraps the component in a special object with $$typeof = REACT_MEMO_TYPE.
    // This is the canonical way to check memoization without running render.
    const REACT_MEMO_TYPE = Symbol.for('react.memo')
    expect((DeviceStatus as any).$$typeof).toBe(REACT_MEMO_TYPE)
  })

  it('does not re-render when the parent re-renders with identical props', () => {
    // Referentially-stable props (declared once, reused across both parent renders).
    const props = {
      device: null,
      devices: [] as any[],
      isConnected: false,
      onScan: vi.fn(),
      onSelect: vi.fn(),
    }

    // Count renders by intercepting the inner component via the .type property
    // of the memo wrapper. We wrap DeviceStatus.type (the inner fn) in a spy.
    const inner = (DeviceStatus as any).type as React.FC<any>
    let renderCount = 0
    const originalInner = inner
    const SpiedInner = function SpiedDeviceStatus(p: any) {
      renderCount++
      return originalInner(p)
    }
    ;(DeviceStatus as any).type = SpiedInner

    function Parent({ tick }: { tick: number }) {
      // `tick` forces Parent to re-render but is NOT forwarded to DeviceStatus.
      return <DeviceStatus {...props} />
    }

    const { rerender } = render(<Parent tick={0} />)
    const afterMount = renderCount
    expect(afterMount).toBeGreaterThan(0) // mounted once

    // Re-render the parent with the SAME props object passed to DeviceStatus.
    rerender(<Parent tick={1} />)

    // memo should bail out → inner spy not called again.
    expect(renderCount).toBe(afterMount)

    // Restore the original inner function.
    ;(DeviceStatus as any).type = originalInner
  })
})
