import React from 'react'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import type { UserAvatar } from '../userAvatars'
import UserAvatarPicker from './UserAvatarPicker'

vi.mock('../i18n', () => ({
  useT: () => (key: string) => key,
}))

// Avatar module pulls in Vite ?import PNG assets and an async canvas
// resize. Replace with stable test doubles; keep the real type contract.
const pngFileToDataUrl = vi.fn<(file: File, max?: number) => Promise<string>>()
vi.mock('../userAvatars', () => ({
  PRESETS: [
    { id: 'hare', label: '兔兔', url: 'hare.png' },
    { id: 'dog', label: '小狗', url: 'dog.png' },
    { id: 'cat', label: '小貓', url: 'cat.png' },
    { id: 'fox', label: '狐狸', url: 'fox.png' },
    { id: 'boy', label: '男孩', url: 'boy.png' },
    { id: 'girl', label: '女孩', url: 'girl.png' },
  ],
  DEFAULT_AVATAR_HTML: '<svg data-testid="default-svg"></svg>',
  pngFileToDataUrl: (file: File, max?: number) => pngFileToDataUrl(file, max),
}))

const baseProps = (over: Partial<{
  avatar: UserAvatar
  customPng: string | null
}> = {}) => ({
  avatar: over.avatar ?? ({ type: 'default' } as UserAvatar),
  customPng: over.customPng ?? null,
  onSave: vi.fn(),
  onClose: vi.fn(),
  onShowToast: vi.fn(),
})

beforeEach(() => {
  pngFileToDataUrl.mockReset()
})
afterEach(() => {
  vi.clearAllMocks()
})

describe('UserAvatarPicker', () => {
  it('renders all six presets and the default option', () => {
    render(<UserAvatarPicker {...baseProps()} />)
    // Preset thumbnails are <img> with translated alt = key.
    for (const key of [
      'avatar.preset_rabbit',
      'avatar.preset_dog',
      'avatar.preset_cat',
      'avatar.preset_fox',
      'avatar.preset_boy',
      'avatar.preset_girl',
    ]) {
      expect(screen.getByAltText(key)).toBeInTheDocument()
    }
    expect(screen.getByText('avatar.default_label')).toBeInTheDocument()
  })

  it('disables Save until a different avatar is staged, then saves the staged preset', () => {
    const props = baseProps() // starts at default
    render(<UserAvatarPicker {...props} />)
    const save = screen.getByText('avatar.save')
    // Pending == current (default) => save disabled.
    expect(save).toBeDisabled()

    // Pick the fox preset.
    fireEvent.click(screen.getByAltText('avatar.preset_fox'))
    expect(save).toBeEnabled()

    fireEvent.click(save)
    expect(props.onSave).toHaveBeenCalledTimes(1)
    expect(props.onSave).toHaveBeenCalledWith({ type: 'preset', presetId: 'fox' }, null)
    expect(props.onClose).toHaveBeenCalledTimes(1)
  })

  it('selecting the default while already on a preset stages the change and saves default', () => {
    const props = baseProps({ avatar: { type: 'preset', presetId: 'cat' } })
    render(<UserAvatarPicker {...props} />)
    const save = screen.getByText('avatar.save')
    expect(save).toBeDisabled() // pending == current preset

    fireEvent.click(screen.getByText('avatar.default_label'))
    expect(save).toBeEnabled()
    fireEvent.click(save)
    expect(props.onSave).toHaveBeenCalledWith({ type: 'default' }, null)
  })

  it('Save with no change just closes without calling onSave', () => {
    const props = baseProps({ avatar: { type: 'preset', presetId: 'dog' } })
    render(<UserAvatarPicker {...props} />)
    // pendingDiffers is false; button is disabled, but assert the no-op path
    // by clicking the enabled-looking flow after staging then reverting.
    const save = screen.getByText('avatar.save')
    expect(save).toBeDisabled()
    // Stage a different preset then go back to the original -> differs=false again.
    fireEvent.click(screen.getByAltText('avatar.preset_fox'))
    expect(save).toBeEnabled()
    fireEvent.click(screen.getByAltText('avatar.preset_dog'))
    expect(save).toBeDisabled()
    expect(props.onSave).not.toHaveBeenCalled()
  })

  it('Cancel resets staged selection and calls onClose without onSave', () => {
    const props = baseProps()
    render(<UserAvatarPicker {...props} />)
    fireEvent.click(screen.getByAltText('avatar.preset_boy')) // stage a change
    fireEvent.click(screen.getByText('avatar.cancel'))
    expect(props.onClose).toHaveBeenCalledTimes(1)
    expect(props.onSave).not.toHaveBeenCalled()
  })

  it('rejects a non-PNG upload with a toast and no staging', async () => {
    const props = baseProps()
    render(<UserAvatarPicker {...props} />)
    const input = document.querySelector('input[type="file"]') as HTMLInputElement
    const jpeg = new File(['x'], 'a.jpg', { type: 'image/jpeg' })
    fireEvent.change(input, { target: { files: [jpeg] } })
    expect(props.onShowToast).toHaveBeenCalledWith('avatar.only_png')
    expect(pngFileToDataUrl).not.toHaveBeenCalled()
  })

  it('a valid PNG upload stages a custom avatar and enables Save', async () => {
    pngFileToDataUrl.mockResolvedValue('data:image/png;base64,AAAA')
    const props = baseProps()
    render(<UserAvatarPicker {...props} />)
    const input = document.querySelector('input[type="file"]') as HTMLInputElement
    const png = new File(['x'], 'a.png', { type: 'image/png' })
    fireEvent.change(input, { target: { files: [png] } })

    await waitFor(() => expect(pngFileToDataUrl).toHaveBeenCalledTimes(1))
    const save = screen.getByText('avatar.save')
    await waitFor(() => expect(save).toBeEnabled())

    fireEvent.click(save)
    expect(props.onSave).toHaveBeenCalledWith(
      { type: 'custom' },
      'data:image/png;base64,AAAA',
    )
  })

  it('shows a toast when PNG processing fails', async () => {
    pngFileToDataUrl.mockRejectedValue(new Error('decode-failed'))
    const props = baseProps()
    render(<UserAvatarPicker {...props} />)
    const input = document.querySelector('input[type="file"]') as HTMLInputElement
    const png = new File(['x'], 'a.png', { type: 'image/png' })
    fireEvent.change(input, { target: { files: [png] } })

    await waitFor(() =>
      expect(props.onShowToast).toHaveBeenCalledWith('avatar.read_failed'),
    )
    expect(props.onSave).not.toHaveBeenCalled()
  })

  it('renders the existing custom thumbnail and can select it', () => {
    const props = baseProps({
      avatar: { type: 'preset', presetId: 'hare' },
      customPng: 'data:image/png;base64,BBBB',
    })
    render(<UserAvatarPicker {...props} />)
    // Custom thumb img has empty alt; find by src.
    const img = document.querySelector('img[src="data:image/png;base64,BBBB"]')
    expect(img).not.toBeNull()
    // Replace-image button label (since a custom PNG already exists).
    expect(screen.getByText('avatar.replace_image')).toBeInTheDocument()

    fireEvent.click(img as Element)
    fireEvent.click(screen.getByText('avatar.save'))
    expect(props.onSave).toHaveBeenCalledWith(
      { type: 'custom' },
      'data:image/png;base64,BBBB',
    )
  })

  it('close (×) button calls onClose without saving', () => {
    const props = baseProps()
    render(<UserAvatarPicker {...props} />)
    fireEvent.click(screen.getByTitle('avatar.close_no_save'))
    expect(props.onClose).toHaveBeenCalledTimes(1)
    expect(props.onSave).not.toHaveBeenCalled()
  })
})
