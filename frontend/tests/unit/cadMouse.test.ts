import { describe, expect, it } from 'vitest';
import { renderHook } from '@testing-library/react';
import { CameraControlsImpl } from '@react-three/drei';
import { useCadMouse } from '../../src/components/viewport/cadMouse';

describe('CAD-style mouse in the 3D views (Fusion 360)', () => {
  const { ROTATE, TRUCK, DOLLY } = CameraControlsImpl.ACTION;

  it('middle-drag pans, Shift + middle-drag orbits; the other buttons are unchanged', () => {
    const controls = { current: { mouseButtons: { left: ROTATE, middle: DOLLY, right: TRUCK, wheel: DOLLY } } };
    const { unmount } = renderHook(() => useCadMouse(controls as never));
    expect(controls.current.mouseButtons.middle).toBe(TRUCK);
    window.dispatchEvent(new MouseEvent('pointerdown', { shiftKey: true }));
    expect(controls.current.mouseButtons.middle).toBe(ROTATE);
    window.dispatchEvent(new MouseEvent('pointermove', { shiftKey: false }));   // Shift let go mid-drag: pan again
    expect(controls.current.mouseButtons.middle).toBe(TRUCK);
    expect(controls.current.mouseButtons).toMatchObject({ left: ROTATE, right: TRUCK, wheel: DOLLY });
    unmount();
    window.dispatchEvent(new MouseEvent('pointerdown', { shiftKey: true }));   // listener gone with the view
    expect(controls.current.mouseButtons.middle).toBe(TRUCK);
  });

  it('a view whose controls are not mounted yet is set at the first pointer event', () => {
    const controls: { current: { mouseButtons: { middle: number } } | null } = { current: null };
    const { unmount } = renderHook(() => useCadMouse(controls as never));
    controls.current = { mouseButtons: { middle: DOLLY } };
    window.dispatchEvent(new MouseEvent('pointerdown', { shiftKey: false }));
    expect(controls.current.mouseButtons.middle).toBe(TRUCK);
    unmount();
  });
});
