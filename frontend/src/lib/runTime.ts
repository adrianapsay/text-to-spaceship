// V2: the search runs until the user presses Pause. The status bar and the Optimization tab show how long it has been
// searching for the current inputs and, where one was measured, the recommended minimum ("recommended minimum
// 99 min · running 12 min"); the tooltip says what the recommendation is based on.
import type { ProgressPayload } from '../api/types';

/** Whole minutes of searching, "less than 1 min" before the first one. */
export function minutesText(s: number): string {
  return s < 60 ? 'less than 1 min' : `${Math.floor(s / 60)} min`;
}

export function runTime(p: ProgressPayload | null | undefined, runStatus?: string): { text: string; title: string } | null {
  if (!p || runStatus === 'IDLE' || p.elapsed_s == null || !Number.isFinite(p.elapsed_s)) return null;
  const running = `running ${minutesText(p.elapsed_s)}${runStatus === 'PAUSED' ? ' (paused)' : ''}`;
  const rec = p.recommended_min_s;
  if (rec == null || !Number.isFinite(rec)) {
    return { text: running, title: p.recommended_note || 'No recommended minimum has been measured for this CubeSat size yet.' };
  }
  return {
    text: `recommended minimum ${Math.ceil(rec / 60)} min · ${running}`,
    title: `${p.recommended_note || 'Search-based and provisional.'} The search goes on until you press Pause.`,
  };
}
