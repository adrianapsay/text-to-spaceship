/** A file-name-safe version of a design name (as the backend's model.slug). */
export function slug(text: string, n = 32): string {
  const s = String(text)
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '');
  return s.slice(0, n).replace(/-+$/, '') || 'mission';
}
