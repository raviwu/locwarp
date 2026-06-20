import React from 'react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';

vi.mock('../i18n', () => ({
  useT: () => (key: string) => key,
}));

import JoystickPad from './JoystickPad';

// onMove/onRelease fire synchronously inside the keyboard handler's update().
// The visual handle uses requestAnimationFrame, which we stub to a no-op so no
// frames stay pending and the callback assertions are deterministic.
function press(key: string) {
  fireEvent.keyDown(window, { key });
}
function release(key: string) {
  fireEvent.keyUp(window, { key });
}

describe('JoystickPad', () => {
  beforeEach(() => {
    vi.spyOn(window, 'requestAnimationFrame').mockReturnValue(1 as unknown as number);
    vi.spyOn(window, 'cancelAnimationFrame').mockImplementation(() => {});
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('renders the four direction labels and the idle hint', () => {
    render(<JoystickPad direction={0} intensity={0} onMove={vi.fn()} onRelease={vi.fn()} />);
    // Compass labels around the pad (north/east/south/west keys).
    expect(screen.getByText('joy.north')).toBeInTheDocument();
    expect(screen.getByText('joy.east')).toBeInTheDocument();
    expect(screen.getByText('joy.south')).toBeInTheDocument();
    expect(screen.getByText('joy.west')).toBeInTheDocument();
    // intensity 0 → show the idle "drag or keys" hint.
    expect(screen.getByText('joy.drag_or_keys')).toBeInTheDocument();
  });

  it('shows direction label + percentage when intensity > 0', () => {
    render(<JoystickPad direction={90} intensity={0.5} onMove={vi.fn()} onRelease={vi.fn()} />);
    // 90deg compass = east. getDirectionLabel(90) -> joy.east; 0.5 -> 50%.
    // The info text combines the label + percentage in one node; the idle hint
    // must be gone. (joy.east also appears as a compass label around the pad,
    // so we assert on the combined "| %" info line specifically.)
    expect(screen.queryByText('joy.drag_or_keys')).not.toBeInTheDocument();
    // The info line combines label + percentage across text fragments in one
    // div; match the element whose OWN text (not a child's) is "joy.east | 50%".
    const infoLine = screen.getByText((_, el) => {
      if (!el) return false;
      const own = Array.from(el.childNodes)
        .filter((n) => n.nodeType === Node.TEXT_NODE)
        .map((n) => n.textContent)
        .join('');
      return own.replace(/\s+/g, ' ').trim() === 'joy.east | 50%';
    });
    expect(infoLine).toBeInTheDocument();
  });

  it('fires onMove with compass 0 (north) at full intensity on W / up press', () => {
    const onMove = vi.fn();
    render(<JoystickPad direction={0} intensity={0} onMove={onMove} onRelease={vi.fn()} />);

    press('w');
    expect(onMove).toHaveBeenLastCalledWith(0, 1);
  });

  it('fires onMove with compass 90 (east) on D / right press', () => {
    const onMove = vi.fn();
    render(<JoystickPad direction={0} intensity={0} onMove={onMove} onRelease={vi.fn()} />);

    press('d');
    expect(onMove).toHaveBeenLastCalledWith(90, 1);
  });

  it('fires onMove with compass 180 (south) on S / down press', () => {
    const onMove = vi.fn();
    render(<JoystickPad direction={0} intensity={0} onMove={onMove} onRelease={vi.fn()} />);

    press('s');
    expect(onMove).toHaveBeenLastCalledWith(180, 1);
  });

  it('fires onMove with compass 270 (west) on A / left press', () => {
    const onMove = vi.fn();
    render(<JoystickPad direction={0} intensity={0} onMove={onMove} onRelease={vi.fn()} />);

    press('a');
    expect(onMove).toHaveBeenLastCalledWith(270, 1);
  });

  it('combines W + D into a 45deg (north-east) vector', () => {
    const onMove = vi.fn();
    render(<JoystickPad direction={0} intensity={0} onMove={onMove} onRelease={vi.fn()} />);

    press('w');
    press('d');
    expect(onMove).toHaveBeenLastCalledWith(45, 1);
  });

  it('supports arrow keys as aliases (ArrowUp = north)', () => {
    const onMove = vi.fn();
    render(<JoystickPad direction={0} intensity={0} onMove={onMove} onRelease={vi.fn()} />);

    press('ArrowUp');
    expect(onMove).toHaveBeenLastCalledWith(0, 1);
  });

  it('calls onRelease when the last held key is released', () => {
    const onMove = vi.fn();
    const onRelease = vi.fn();
    render(<JoystickPad direction={0} intensity={0} onMove={onMove} onRelease={onRelease} />);

    press('w');
    expect(onMove).toHaveBeenCalled();
    onRelease.mockClear();

    release('w');
    expect(onRelease).toHaveBeenCalledTimes(1);
  });

  it('ignores key events that originate from an input element', () => {
    const onMove = vi.fn();
    render(
      <div>
        <input data-testid="field" />
        <JoystickPad direction={0} intensity={0} onMove={onMove} onRelease={vi.fn()} />
      </div>,
    );

    const field = screen.getByTestId('field');
    fireEvent.keyDown(field, { key: 'w' });
    expect(onMove).not.toHaveBeenCalled();
  });
});
