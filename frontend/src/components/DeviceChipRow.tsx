import { DeviceChip, type DeviceLetter } from './DeviceChip'
import { useT } from '../i18n'
import type { DeviceInfo } from '../hooks/useDevice'
import type { RuntimesMap } from '../hooks/useSimulation'

export const MAX_DEVICES = 3
const LETTERS: DeviceLetter[] = ['A', 'B', 'C']

interface Props {
  devices: DeviceInfo[]           // connected devices in order (max 3)
  trustRequired?: DeviceInfo[]
  runtimes: RuntimesMap
  onAdd: () => void               // opens add-device picker
  onDisconnect: (udid: string) => void
  onForget: (udid: string) => void
  onRestoreOne: (udid: string) => void
  onReTrust?: (udid: string) => void
  onEnableDev?: (udid: string) => void
}

export function DeviceChipRow({ devices, trustRequired = [], runtimes, onAdd, onDisconnect, onForget, onRestoreOne, onReTrust, onEnableDev }: Props) {
  const t = useT()
  const atMax = (devices.length + trustRequired.length) >= MAX_DEVICES

  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: 4,
      padding: '6px 10px 8px',
      flexWrap: 'wrap',
    }}>
      {devices.slice(0, MAX_DEVICES).map((d, i) => {
        const letter = LETTERS[i]
        return (
          <DeviceChip
            key={d.udid}
            letter={letter}
            device={d}
            runtime={runtimes[d.udid]}
            onDisconnect={() => onDisconnect(d.udid)}
            onForget={() => onForget(d.udid)}
            onRestoreOne={() => onRestoreOne(d.udid)}
            onEnableDev={onEnableDev ? () => onEnableDev(d.udid) : undefined}
          />
        )
      })}
      {trustRequired.slice(0, MAX_DEVICES).map((d, i) => {
        // Wrap with % instead of clamping with Math.min so two trust chips
        // never collapse onto the same letter. E.g. 2 connected + 2 trust:
        // Math.min(2,2) → 'C', Math.min(3,2) → 'C' (collision);
        // (2+0)%3 → 'C', (2+1)%3 → 'A' (distinct).
        const letter = LETTERS[(devices.length + i) % LETTERS.length]
        return (
          <DeviceChip
            key={d.udid}
            letter={letter}
            device={d}
            variant="trust_required"
            onReTrust={() => onReTrust?.(d.udid)}
            onDisconnect={() => onDisconnect(d.udid)}
            onForget={() => onForget(d.udid)}
            onRestoreOne={() => onRestoreOne(d.udid)}
          />
        )
      })}
      {!atMax && (
        <button
          onClick={onAdd}
          title={devices.length === 0 ? t('device.add_device') : t('device.add_device')}
          style={{
            height: 24, minWidth: 24, padding: '0 8px',
            borderRadius: 12,
            border: '1px dashed rgba(255,255,255,0.25)',
            background: 'rgba(255,255,255,0.04)',
            color: 'rgba(255,255,255,0.75)',
            fontSize: 11, cursor: 'pointer',
            display: 'inline-flex', alignItems: 'center', gap: 4,
          }}
        >
          <span style={{ fontSize: 14, lineHeight: 1 }}>+</span>
          {devices.length === 0 && <span>{t('device.add_device')}</span>}
        </button>
      )}
    </div>
  )
}
