import React from 'react'
import { describe, it, expect, vi } from 'vitest'
import { render } from '@testing-library/react'
import { DeviceChipRow } from './DeviceChipRow'
import type { RuntimesMap } from '../hooks/useSimulation'

vi.mock('../i18n', () => ({ useT: () => (key: string) => key }))

const emptyRuntimes: RuntimesMap = {}

describe('DeviceChipRow is React.memo (D3)', () => {
  it('named export is wrapped in React.memo', () => {
    const REACT_MEMO_TYPE = Symbol.for('react.memo')
    expect((DeviceChipRow as any).$$typeof).toBe(REACT_MEMO_TYPE)
  })

  it('does not re-render when the parent re-renders with identical props', () => {
    const props = {
      devices: [] as any[],
      runtimes: emptyRuntimes,
      onAdd: vi.fn(),
      onDisconnect: vi.fn(),
      onForget: vi.fn(),
      onRestoreOne: vi.fn(),
    }

    // Count renders by intercepting the inner function of the memo wrapper.
    const inner = (DeviceChipRow as any).type as React.FC<any>
    let renderCount = 0
    const originalInner = inner
    const SpiedInner = function SpiedDeviceChipRow(p: any) {
      renderCount++
      return originalInner(p)
    }
    ;(DeviceChipRow as any).type = SpiedInner

    function Parent({ tick }: { tick: number }) {
      return <DeviceChipRow {...props} />
    }

    const { rerender } = render(<Parent tick={0} />)
    const afterMount = renderCount
    expect(afterMount).toBeGreaterThan(0)

    rerender(<Parent tick={1} />)
    expect(renderCount).toBe(afterMount)

    // Restore the original inner function.
    ;(DeviceChipRow as any).type = originalInner
  })
})
