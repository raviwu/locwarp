import { useState, useEffect, useRef } from 'react'
import type { ApiGateway } from '../contract/apiGateway'

// Reverse-geo / timezone / weather enrichment for the status bar, extracted out
// of App.tsx. Mirrors the useRoutes/useBookmarks `useX(api)` shape — the backend
// `api` is injected (App sources it from useServices()) so the hook never imports
// services/api directly and stays inside the hexagon-lite layering gate.
//
// Inputs:
//   position  — the current virtual location (sim.currentPosition), or null.
//   simState  — the sim status state string (sim.status?.state), defaulting to
//               'idle' when absent.
//
// The lookup is GATED so it only fires on discrete user-initiated moves
// (teleport, bookmark tap, manual coord entry). During active navigate / loop /
// multi-stop / random-walk the simulation engine emits a position update every
// tick, which used to spam Nominatim + TimezoneDB every second and contend with
// the USB DVT channel — it contributed to users seeing random walk 'freeze' (see
// backend log 2026-04-16 user report).
//
// Rule (PRESERVED EXACTLY from App.tsx): only look up when the sim state is
// idle / teleporting / disconnected (i.e. no route animation in flight), AND the
// position actually moved >=100m from the last looked-up point (lastLookedUpPosRef
// suppresses redundant lookups when jitter nudges the coordinate but the user
// hasn't actually moved).

export interface LocMeta {
  countryCode: string
  // Reverse-geocoded city / POI / road name (whatever Photon-or-Nominatim's
  // short_name returns). Used by the timezone-detail modal in StatusBar to print
  // "Country City" alongside the IANA zone, and may be empty if the lookup failed
  // or the spot is mid-ocean.
  cityName: string
  timezoneZone: string | null
  gmtOffsetSeconds: number | null
  // Weather at the current virtual location. Fetched from Open-Meteo when the
  // position moves >=100m and the sim is quiescent (same gate as reverse-geocode
  // + timezone). Null = unknown / not yet fetched.
  weatherCode: number | null
  tempC: number | null
}

export function useLocationMeta(
  api: ApiGateway,
  position: { lat: number; lng: number } | null | undefined,
  simState: string | null | undefined,
): { locMeta: LocMeta } {
  // Reverse-geo-derived state used by the status bar: country-code flag and
  // (later) timezone tag. Populated debounced from the position so we don't hit
  // Nominatim/Photon every position_update tick.
  const [locMeta, setLocMeta] = useState<LocMeta>({
    countryCode: '', cityName: '', timezoneZone: null, gmtOffsetSeconds: null,
    weatherCode: null, tempC: null,
  })
  // Last position we successfully looked up reverse-geo/timezone for. Used to
  // suppress redundant lookups when jitter nudges the coordinate but the user
  // hasn't actually moved.
  const lastLookedUpPosRef = useRef<{ lat: number; lng: number } | null>(null)

  useEffect(() => {
    const pos = position
    if (!pos) return
    const state = simState ?? 'idle'
    const isQuiescent = state === 'idle' || state === 'teleporting' || state === 'disconnected'
    if (!isQuiescent) return
    // Skip redundant lookups when the user stays at the same spot (jitter
    // within 100m of the last resolved position).
    const last = lastLookedUpPosRef.current
    if (last) {
      const dLat = (pos.lat - last.lat) * 111320
      const dLng = (pos.lng - last.lng) * 111320 * Math.cos(pos.lat * Math.PI / 180)
      if (dLat * dLat + dLng * dLng < 100 * 100) return
    }
    let cancelled = false
    const tid = setTimeout(async () => {
      lastLookedUpPosRef.current = { lat: pos.lat, lng: pos.lng }
      let geoRes: any = null
      try {
        geoRes = await api.reverseGeocode(pos.lat, pos.lng)
        if (cancelled) return
        const cc = String(geoRes?.country_code ?? '').toLowerCase()
        const city = String(geoRes?.short_name ?? '').trim()
        setLocMeta((prev) =>
          (prev.countryCode === cc && prev.cityName === city)
            ? prev
            : { ...prev, countryCode: cc, cityName: city }
        )
      } catch { /* offline / rate-limited — keep previous */ }
      try {
        const tz = await api.lookupTimezone(pos.lat, pos.lng)
        if (cancelled || !tz) return
        setLocMeta((prev) => ({ ...prev, timezoneZone: tz.zone, gmtOffsetSeconds: tz.gmt_offset_seconds }))
      } catch { /* ignore */ }
      try {
        const wx = await api.lookupWeather(pos.lat, pos.lng)
        if (cancelled || !wx) return
        setLocMeta((prev) => prev.weatherCode === wx.code && prev.tempC === wx.tempC
          ? prev
          : { ...prev, weatherCode: wx.code, tempC: wx.tempC })
      } catch { /* ignore */ }
    }, 600)
    return () => { cancelled = true; clearTimeout(tid) }
  }, [api, position?.lat, position?.lng, simState])

  return { locMeta }
}
