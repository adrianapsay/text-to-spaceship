// CAD-style mouse for the 3D views, as in Fusion 360: hold the middle button (the wheel) and drag to pan — the view
// moves off the axis it was looking along — and add Shift to orbit instead. Left-drag orbits, right-drag pans and the
// wheel zooms, as before; F fits the layout again.
import { useEffect, type MouseEvent as ReactMouseEvent, type RefObject } from 'react';
import { CameraControlsImpl, type CameraControls } from '@react-three/drei';

export const MOUSE_HELP = 'Mouse: left-drag orbit, middle-drag pan, Shift + middle-drag orbit, right-drag pan, wheel zoom.';

/** camera-controls reads `mouseButtons` on every pointer event, so a capture listener on the window sets the middle
 * button's action (pan, or orbit with Shift) just before it does — also when Shift is pressed mid-drag. */
export function useCadMouse(controls: RefObject<CameraControls | null>): void {
  useEffect(() => {
    const { ROTATE, TRUCK } = CameraControlsImpl.ACTION;
    const set = (e: { shiftKey: boolean }) => {
      if (controls.current) controls.current.mouseButtons.middle = e.shiftKey ? ROTATE : TRUCK;
    };
    set({ shiftKey: false });
    window.addEventListener('pointerdown', set, true);
    window.addEventListener('pointermove', set, true);
    return () => {
      window.removeEventListener('pointerdown', set, true);
      window.removeEventListener('pointermove', set, true);
    };
  }, [controls]);
}

/** A middle-click in a 3D view must not start the browser's autoscroll (the Mounting Hardware tab scrolls). */
export function stopMiddleClickScroll(e: ReactMouseEvent): void {
  if (e.button === 1) e.preventDefault();
}
