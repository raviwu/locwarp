// Read-only view of the per-device WiFi-tunnel savedips list. The WRITER lives
// in useDevice.startWifiTunnel (it appends {ip,port,udid,lastUsed} after every
// successful tunnel, newest-first). This helper picks the entry to re-fire on
// a one-click Reconnect: prefer the entry matching the lost udid, else the
// most-recent (first) entry.
export interface SavedipEntry {
  ip: string
  port: number
  udid?: string
}

export function readSavedipEntry(udid: string | null): SavedipEntry | null {
  let raw: string | null = null
  try { raw = localStorage.getItem('locwarp.tunnel.savedips') } catch { return null }
  if (!raw) return null
  let list: unknown
  try { list = JSON.parse(raw) } catch { return null }
  if (!Array.isArray(list)) return null
  const entries = list.filter(
    (e): e is { ip: string; port?: number; udid?: string } =>
      !!e && typeof e.ip === 'string' && e.ip.trim().length > 0,
  )
  if (entries.length === 0) return null
  const toEntry = (e: { ip: string; port?: number; udid?: string }): SavedipEntry => ({
    ip: String(e.ip).trim(),
    port: Number(e.port) || 49152,
    udid: typeof e.udid === 'string' && e.udid ? e.udid : undefined,
  })
  if (udid) {
    const match = entries.find((e) => e.udid === udid)
    if (match) return toEntry(match)
  }
  return toEntry(entries[0])
}
