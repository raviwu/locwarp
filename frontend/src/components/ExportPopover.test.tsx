import React from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, within } from '@testing-library/react'
import ExportPopover from './ExportPopover'

vi.mock('../i18n', () => ({
  useT: () => (key: string) => key,
}))

// Mock the URL builder so we can assert the options passed and control the href.
const { bookmarksExportUrl } = vi.hoisted(() => ({
  bookmarksExportUrl: vi.fn(
    (opts: { category_id?: string | null; format?: string } = {}) => {
      const p = new URLSearchParams()
      if (opts.category_id) p.set('category_id', opts.category_id)
      if (opts.format) p.set('format', opts.format)
      const qs = p.toString()
      return `http://test/api/bookmarks/export${qs ? `?${qs}` : ''}`
    },
  ),
}))
vi.mock('../contexts/ServicesContext', () => ({
  useServices: () => ({ api: { bookmarksExportUrl } }),
}))

const anchorRect = {
  top: 100, bottom: 120, left: 50, right: 80,
  width: 30, height: 20, x: 50, y: 100,
  toJSON: () => ({}),
} as DOMRect

const categories = [
  { id: 'cat-a', name: 'Alpha' },
  { id: 'cat-b', name: 'Beta' },
]

describe('ExportPopover', () => {
  beforeEach(() => {
    document.body.innerHTML = ''
    bookmarksExportUrl.mockClear()
  })

  it('renders nothing when closed', () => {
    const { container } = render(
      <ExportPopover open={false} anchorRect={anchorRect} categories={categories} onClose={() => {}} />,
    )
    expect(container.firstChild).toBeNull()
    expect(screen.queryByText('bm.export.title')).not.toBeInTheDocument()
  })

  it('renders nothing when anchorRect is null', () => {
    render(
      <ExportPopover open={true} anchorRect={null} categories={categories} onClose={() => {}} />,
    )
    expect(screen.queryByText('bm.export.title')).not.toBeInTheDocument()
  })

  it('renders title, both scopes, and all four format options when open', () => {
    render(
      <ExportPopover open={true} anchorRect={anchorRect} categories={categories} onClose={() => {}} />,
    )
    expect(screen.getByText('bm.export.title')).toBeInTheDocument()
    expect(screen.getByText('bm.export.scope_all')).toBeInTheDocument()
    expect(screen.getByText('bm.export.scope_one')).toBeInTheDocument()
    expect(screen.getByText('bm.export.format_json')).toBeInTheDocument()
    expect(screen.getByText('bm.export.format_markdown')).toBeInTheDocument()
    expect(screen.getByText('bm.export.format_geojson')).toBeInTheDocument()
    expect(screen.getByText('bm.export.format_csv')).toBeInTheDocument()
  })

  it('defaults to scope=all and format=json; download href has no category_id', () => {
    render(
      <ExportPopover open={true} anchorRect={anchorRect} categories={categories} onClose={() => {}} />,
    )
    expect(bookmarksExportUrl).toHaveBeenCalledWith({ category_id: null, format: 'json' })
    const link = screen.getByText('bm.export.download').closest('a')!
    expect(link).toHaveAttribute('href', 'http://test/api/bookmarks/export?format=json')
    expect(link).toHaveAttribute('download')
    // The category select is hidden while scope=all.
    expect(screen.queryByRole('combobox')).not.toBeInTheDocument()
  })

  it('shows the category select only when scope=one, and includes its category_id in the url', () => {
    render(
      <ExportPopover open={true} anchorRect={anchorRect} categories={categories} onClose={() => {}} />,
    )
    const scopeOne = screen.getByText('bm.export.scope_one').closest('label')!
    fireEvent.click(within(scopeOne).getByRole('radio'))

    // Now the select appears, defaulting to the first category.
    const select = screen.getByRole('combobox') as HTMLSelectElement
    expect(select.value).toBe('cat-a')
    expect(bookmarksExportUrl).toHaveBeenLastCalledWith({ category_id: 'cat-a', format: 'json' })

    const link = screen.getByText('bm.export.download').closest('a')!
    expect(link).toHaveAttribute('href', 'http://test/api/bookmarks/export?category_id=cat-a&format=json')
  })

  it('changing the selected category updates the export url', () => {
    render(
      <ExportPopover open={true} anchorRect={anchorRect} categories={categories} onClose={() => {}} />,
    )
    fireEvent.click(within(screen.getByText('bm.export.scope_one').closest('label')!).getByRole('radio'))
    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'cat-b' } })
    expect(bookmarksExportUrl).toHaveBeenLastCalledWith({ category_id: 'cat-b', format: 'json' })
    const link = screen.getByText('bm.export.download').closest('a')!
    expect(link).toHaveAttribute('href', 'http://test/api/bookmarks/export?category_id=cat-b&format=json')
  })

  const formats = ['json', 'markdown', 'geojson', 'csv'] as const
  formats.forEach((fmt) => {
    it(`selecting format=${fmt} rebuilds the url with that format`, () => {
      render(
        <ExportPopover open={true} anchorRect={anchorRect} categories={categories} onClose={() => {}} />,
      )
      const fmtLabel = screen.getByText(`bm.export.format_${fmt}`).closest('label')!
      fireEvent.click(within(fmtLabel).getByRole('radio'))
      expect(bookmarksExportUrl).toHaveBeenLastCalledWith({ category_id: null, format: fmt })
      const link = screen.getByText('bm.export.download').closest('a')!
      expect(link).toHaveAttribute('href', `http://test/api/bookmarks/export?format=${fmt}`)
    })
  })

  it('clicking the cancel button calls onClose', () => {
    const onClose = vi.fn()
    render(
      <ExportPopover open={true} anchorRect={anchorRect} categories={categories} onClose={onClose} />,
    )
    fireEvent.click(screen.getByText('generic.cancel'))
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('clicking the download link calls onClose', () => {
    const onClose = vi.fn()
    render(
      <ExportPopover open={true} anchorRect={anchorRect} categories={categories} onClose={onClose} />,
    )
    fireEvent.click(screen.getByText('bm.export.download'))
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('pressing Escape calls onClose', async () => {
    const onClose = vi.fn()
    render(
      <ExportPopover open={true} anchorRect={anchorRect} categories={categories} onClose={onClose} />,
    )
    // listeners attach on a setTimeout(0); flush it.
    await new Promise((r) => setTimeout(r, 0))
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('a pointerdown outside the popover calls onClose', async () => {
    const onClose = vi.fn()
    render(
      <ExportPopover open={true} anchorRect={anchorRect} categories={categories} onClose={onClose} />,
    )
    await new Promise((r) => setTimeout(r, 0))
    fireEvent.pointerDown(document.body)
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('a pointerdown inside the popover does NOT call onClose', async () => {
    const onClose = vi.fn()
    render(
      <ExportPopover open={true} anchorRect={anchorRect} categories={categories} onClose={onClose} />,
    )
    await new Promise((r) => setTimeout(r, 0))
    fireEvent.pointerDown(screen.getByText('bm.export.title'))
    expect(onClose).not.toHaveBeenCalled()
  })

  it('falls back to "default" category id when categories is empty (scope=one)', () => {
    render(
      <ExportPopover open={true} anchorRect={anchorRect} categories={[]} onClose={() => {}} />,
    )
    fireEvent.click(within(screen.getByText('bm.export.scope_one').closest('label')!).getByRole('radio'))
    expect(bookmarksExportUrl).toHaveBeenLastCalledWith({ category_id: 'default', format: 'json' })
  })
})
