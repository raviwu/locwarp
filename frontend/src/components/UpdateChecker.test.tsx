import React from 'react'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { useUpdateCheck } from './UpdateChecker'

// Tiny probe that surfaces the hook's state into the DOM for assertions.
function Probe() {
  const { current, latest, releaseUrl } = useUpdateCheck()
  return (
    <div>
      <span data-testid="current">{current}</span>
      <span data-testid="latest">{latest === null ? 'NONE' : latest}</span>
      <span data-testid="url">{releaseUrl === null ? 'NONE' : releaseUrl}</span>
    </div>
  )
}

function mockFetchOnce(body: unknown, ok = true) {
  return vi.fn().mockResolvedValue({
    ok,
    json: async () => body,
  })
}

describe('useUpdateCheck', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('reports up-to-date (latest=null) when GitHub tag is not newer', async () => {
    // package.json version is 0.3.0; same tag is not newer.
    vi.stubGlobal(
      'fetch',
      mockFetchOnce({ tag_name: 'v0.3.0', html_url: 'https://example/r' }),
    )
    render(<Probe />)

    // current is always populated immediately.
    expect(screen.getByTestId('current')).toHaveTextContent('0.3.0')
    // Give the effect a chance to run; latest stays null (up-to-date).
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(1))
    expect(screen.getByTestId('latest')).toHaveTextContent('NONE')
    expect(screen.getByTestId('url')).toHaveTextContent('NONE')
  })

  it('surfaces an available update (latest + releaseUrl) for a newer tag', async () => {
    vi.stubGlobal(
      'fetch',
      mockFetchOnce({
        tag_name: 'v9.9.9',
        html_url: 'https://github.com/raviwu/locwarp/releases/tag/v9.9.9',
      }),
    )
    render(<Probe />)

    await waitFor(() =>
      expect(screen.getByTestId('latest')).toHaveTextContent('v9.9.9'),
    )
    expect(screen.getByTestId('url')).toHaveTextContent(
      'https://github.com/raviwu/locwarp/releases/tag/v9.9.9',
    )
  })

  it('falls back to the generic releases URL when html_url is missing', async () => {
    vi.stubGlobal('fetch', mockFetchOnce({ tag_name: 'v9.9.9' }))
    render(<Probe />)

    await waitFor(() =>
      expect(screen.getByTestId('latest')).toHaveTextContent('v9.9.9'),
    )
    expect(screen.getByTestId('url')).toHaveTextContent(
      'https://github.com/raviwu/locwarp/releases/latest',
    )
  })

  it('stays up-to-date when the GitHub response is not ok', async () => {
    vi.stubGlobal(
      'fetch',
      mockFetchOnce({ tag_name: 'v9.9.9' }, /* ok */ false),
    )
    render(<Probe />)

    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(1))
    expect(screen.getByTestId('latest')).toHaveTextContent('NONE')
  })

  it('stays silent (latest=null) when fetch rejects (offline)', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('offline')))
    render(<Probe />)

    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(1))
    expect(screen.getByTestId('latest')).toHaveTextContent('NONE')
    expect(screen.getByTestId('url')).toHaveTextContent('NONE')
  })

  it('ignores a response with no tag_name', async () => {
    vi.stubGlobal('fetch', mockFetchOnce({ html_url: 'https://x' }))
    render(<Probe />)

    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(1))
    expect(screen.getByTestId('latest')).toHaveTextContent('NONE')
  })

  it('routes the release check through the raviwu fork repo slug', async () => {
    const fetchMock = mockFetchOnce({ tag_name: 'v9.9.9' })
    vi.stubGlobal('fetch', fetchMock)
    render(<Probe />)

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1))
    // The hook must hit the raviwu fork's releases API (DMG home), not upstream.
    expect(fetchMock).toHaveBeenCalledWith(
      'https://api.github.com/repos/raviwu/locwarp/releases/latest',
      expect.anything(),
    )
    // The generic-fallback URL (no html_url) must also be the raviwu fork.
    expect(screen.getByTestId('url')).toHaveTextContent(
      'https://github.com/raviwu/locwarp/releases/latest',
    )
  })
})
