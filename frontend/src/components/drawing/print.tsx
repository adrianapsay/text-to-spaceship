// V2 WS6 engineering drawings: the sheet as a stand-alone SVG file (true size in millimetres, rendered views embedded
// as PNG), and printing through the browser's dialog (Print / Save as PDF): only the sheets are printed, one per page,
// at true scale on the template's page size.

import { flushSync } from 'react-dom';
import { createRoot } from 'react-dom/client';
import { DrawingSheet } from './SheetSvg';
import type { SheetTemplate } from './sheet';
import type { SheetData } from './sheetData';

const XLINK = 'http://www.w3.org/1999/xlink';

/** A clean copy of a sheet for files and printing: physical size, full sheet in view, no on-screen highlights or
 * keyboard focus targets. */
export function exportableSvg(svg: SVGSVGElement, t: SheetTemplate): string {
  const c = svg.cloneNode(true) as SVGSVGElement;
  c.setAttribute('xmlns', 'http://www.w3.org/2000/svg');
  c.setAttribute('xmlns:xlink', XLINK);
  c.setAttribute('width', `${t.width}mm`);
  c.setAttribute('height', `${t.height}mm`);
  c.setAttribute('viewBox', `0 0 ${t.width} ${t.height}`);
  c.removeAttribute('data-testid');
  for (const el of Array.from(c.querySelectorAll('.sel'))) el.classList.remove('sel');
  for (const el of Array.from(c.querySelectorAll('.selrow'))) {
    el.classList.remove('selrow');
    el.setAttribute('fill', '#fff');
  }
  for (const el of Array.from(c.querySelectorAll('[role="button"]'))) {
    el.removeAttribute('role');
    el.removeAttribute('tabindex');
  }
  for (const img of Array.from(c.querySelectorAll('image'))) {
    const href = img.getAttribute('href');
    if (href) img.setAttributeNS(XLINK, 'xlink:href', href);
  }
  return new XMLSerializer().serializeToString(c);
}

/** The exportable SVG markup of sheet data that is not on screen (rendered into a detached element). */
export function sheetMarkup(d: SheetData): string {
  const host = document.createElement('div');
  const root = createRoot(host);
  flushSync(() => root.render(<DrawingSheet data={d} />));
  const svg = host.querySelector('svg');
  const out = svg ? exportableSvg(svg, d.template) : '';
  root.unmount();
  return out;
}

export function downloadText(text: string, filename: string, type: string): void {
  const blob = new Blob([text], { type });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 5000);
}

export function downloadSvg(markup: string, filename: string): void {
  downloadText(`<?xml version="1.0" encoding="UTF-8"?>\n${markup}`, filename, 'image/svg+xml');
}

export const PRINT_ROOT = 't2s-print-root';

/** Print the given sheets (SVG markup) through the browser's dialog, one sheet per page at true scale. */
export function printSheets(markups: string[], t: SheetTemplate): void {
  document.getElementById(PRINT_ROOT)?.remove();
  document.getElementById(`${PRINT_ROOT}-style`)?.remove();
  const style = document.createElement('style');
  style.id = `${PRINT_ROOT}-style`;
  style.textContent = `
@page { size: ${t.page}; margin: 0; }
@media screen { #${PRINT_ROOT} { display: none !important; } }
@media print {
  html, body, #root { height: auto !important; background: #fff !important; }
  body > *:not(#${PRINT_ROOT}) { display: none !important; }
  #${PRINT_ROOT} { display: block !important; }
  #${PRINT_ROOT} svg { display: block; width: ${t.width}mm; height: ${t.height}mm; break-after: page; page-break-after: always; }
  #${PRINT_ROOT} svg:last-child { break-after: auto; page-break-after: auto; }
}`;
  const root = document.createElement('div');
  root.id = PRINT_ROOT;
  root.setAttribute('aria-hidden', 'true');
  root.innerHTML = markups.join('');
  document.head.appendChild(style);
  document.body.appendChild(root);
  let done = false;
  const cleanup = () => {
    if (done) return;
    done = true;
    root.remove();
    style.remove();
    window.removeEventListener('afterprint', cleanup);
  };
  window.addEventListener('afterprint', cleanup);
  window.print();
  // the dialog fires afterprint when it closes; the copy is hidden on screen anyway, and goes after a minute at most
  setTimeout(cleanup, 60000);
}
