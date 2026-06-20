import React from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, within } from '@testing-library/react'
import RouteEngineSelector, { RouteEngine } from './RouteEngineSelector'

// Passthrough i18n: t(key) -> key, so assertions can target real keys.
vi.mock('../i18n', () => ({
  useT: () => (key: string) => key,
}))

describe('RouteEngineSelector', () => {
  beforeEach(() => {
    document.body.innerHTML = ''
  })

  it('renders the trigger with the active engine label', () => {
    render(<RouteEngineSelector value="valhalla" onChange={() => {}} />)
    // Active engine label shown next to the route_engine key.
    expect(screen.getByText('panel.route_engine')).toBeInTheDocument()
    expect(screen.getByText(/Valhalla/)).toBeInTheDocument()
  })

  it('does not open the modal until the trigger is clicked', () => {
    render(<RouteEngineSelector value="osrm" onChange={() => {}} />)
    expect(screen.queryByText('panel.route_engine_title')).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /panel.route_engine/ }))
    expect(screen.getByText('panel.route_engine_title')).toBeInTheDocument()
  })

  it('does not open when disabled', () => {
    render(<RouteEngineSelector value="osrm" onChange={() => {}} disabled />)
    const trigger = screen.getByRole('button')
    expect(trigger).toBeDisabled()
    fireEvent.click(trigger)
    expect(screen.queryByText('panel.route_engine_title')).not.toBeInTheDocument()
  })

  it('renders one radio per engine when open, with the active one checked', () => {
    render(<RouteEngineSelector value="brouter" onChange={() => {}} />)
    fireEvent.click(screen.getByRole('button', { name: /panel.route_engine/ }))
    const radios = screen.getAllByRole('radio')
    expect(radios).toHaveLength(4)
    const checked = radios.filter((r) => (r as HTMLInputElement).checked)
    expect(checked).toHaveLength(1)
    // The BRouter option's radio is the checked one.
    const brouterLabel = screen.getByText('BRouter').closest('label')!
    expect(within(brouterLabel).getByRole('radio')).toBeChecked()
  })

  const cases: { label: string; engine: RouteEngine }[] = [
    { label: 'OSRM demo', engine: 'osrm' },
    { label: 'OSRM FOSSGIS', engine: 'osrm_fossgis' },
    { label: 'Valhalla', engine: 'valhalla' },
    { label: 'BRouter', engine: 'brouter' },
  ]

  cases.forEach(({ label, engine }) => {
    it(`clicking the "${label}" option fires onChange("${engine}")`, () => {
      const onChange = vi.fn()
      // start on a different engine so the click is a real change target
      const start: RouteEngine = engine === 'osrm' ? 'valhalla' : 'osrm'
      render(<RouteEngineSelector value={start} onChange={onChange} />)
      fireEvent.click(screen.getByRole('button', { name: /panel.route_engine/ }))
      const optLabel = screen.getByText(label).closest('label')!
      fireEvent.click(optLabel)
      expect(onChange).toHaveBeenCalledWith(engine)
    })
  })

  it('the radio input onChange also fires onChange with the engine', () => {
    const onChange = vi.fn()
    render(<RouteEngineSelector value="osrm" onChange={onChange} />)
    fireEvent.click(screen.getByRole('button', { name: /panel.route_engine/ }))
    const valhallaLabel = screen.getByText('Valhalla').closest('label')!
    const radio = within(valhallaLabel).getByRole('radio')
    // firing native change on the radio
    fireEvent.click(radio)
    expect(onChange).toHaveBeenCalledWith('valhalla')
  })

  it('closes the modal via the × button without firing onChange', () => {
    const onChange = vi.fn()
    render(<RouteEngineSelector value="osrm" onChange={onChange} />)
    fireEvent.click(screen.getByRole('button', { name: /panel.route_engine/ }))
    fireEvent.click(screen.getByLabelText('close'))
    expect(screen.queryByText('panel.route_engine_title')).not.toBeInTheDocument()
    expect(onChange).not.toHaveBeenCalled()
  })

  it('closes the modal via the confirm button', () => {
    render(<RouteEngineSelector value="osrm" onChange={() => {}} />)
    fireEvent.click(screen.getByRole('button', { name: /panel.route_engine/ }))
    fireEvent.click(screen.getByText('generic.confirm'))
    expect(screen.queryByText('panel.route_engine_title')).not.toBeInTheDocument()
  })

  it('closes when clicking the backdrop overlay (target === currentTarget)', () => {
    render(<RouteEngineSelector value="osrm" onChange={() => {}} />)
    fireEvent.click(screen.getByRole('button', { name: /panel.route_engine/ }))
    // Overlay = the fixed full-screen portal div with zIndex 9000.
    const overlay = Array.from(document.body.querySelectorAll('div')).find(
      (d) => d.style.position === 'fixed' && d.style.zIndex === '9000',
    )!
    // Clicking the overlay itself (not a child) closes; the handler checks
    // e.target === e.currentTarget, which fireEvent satisfies when dispatched
    // directly on the overlay element.
    fireEvent.click(overlay)
    expect(screen.queryByText('panel.route_engine_title')).not.toBeInTheDocument()
  })

  it('does NOT close when clicking inside the modal card', () => {
    render(<RouteEngineSelector value="osrm" onChange={() => {}} />)
    fireEvent.click(screen.getByRole('button', { name: /panel.route_engine/ }))
    // Click the title (a child of the card) — target !== overlay, stays open.
    fireEvent.click(screen.getByText('panel.route_engine_title'))
    expect(screen.getByText('panel.route_engine_title')).toBeInTheDocument()
  })
})
