/*
 * Set minimo de iconos con UN SOLO lenguaje visual (trazo tipo Lucide: 24x24,
 * stroke-width 1.8-2, sin relleno, esquinas redondeadas). Se usa en el sidebar
 * y el header -- el chrome global que se ve en TODA la app -- para que esa
 * parte, la mas visible, tenga iconografia 100% consistente en vez de mezclar
 * emojis y simbolos unicode como antes.
 */
const PATHS = {
  dashboard: '<rect x="3" y="3" width="7" height="9" rx="1.5"/><rect x="14" y="3" width="7" height="5" rx="1.5"/><rect x="14" y="12" width="7" height="9" rx="1.5"/><rect x="3" y="16" width="7" height="5" rx="1.5"/>',
  "arrow-down-to-line": '<path d="M12 3v12"/><path d="m7 10 5 5 5-5"/><path d="M5 21h14"/>',
  "arrow-up-from-line": '<path d="M12 21V9"/><path d="m7 14 5-5 5 5"/><path d="M5 3h14"/>',
  grid: '<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/>',
  box: '<path d="M21 8l-9-5-9 5v8l9 5 9-5V8z"/><path d="M3 8l9 5 9-5"/><path d="M12 13v8"/>',
  repeat: '<path d="m17 2 4 4-4 4"/><path d="M3 11v-1a4 4 0 0 1 4-4h14"/><path d="m7 22-4-4 4-4"/><path d="M21 13v1a4 4 0 0 1-4 4H3"/>',
  "check-square": '<rect x="3" y="3" width="18" height="18" rx="2"/><path d="m9 12 2 2 4-4"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 3"/>',
  "clipboard-list": '<rect x="6" y="3" width="12" height="4" rx="1"/><path d="M8 3a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2"/><rect x="4" y="5" width="16" height="17" rx="2"/><path d="M9 12h6M9 16h6M9 8h1"/>',
  "bar-chart": '<path d="M3 3v18h18"/><rect x="7" y="12" width="3" height="6"/><rect x="12" y="8" width="3" height="10"/><rect x="17" y="5" width="3" height="13"/>',
  activity: '<path d="M22 12h-4l-3 9L9 3l-3 9H2"/>',
  users: '<path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/>',
  user: '<circle cx="12" cy="8" r="4"/><path d="M4 21v-1a6 6 0 0 1 6-6h4a6 6 0 0 1 6 6v1"/>',
  tag: '<path d="M12 2H2v10l9.29 9.29a1 1 0 0 0 1.41 0l8.29-8.29a1 1 0 0 0 0-1.41L12 2Z"/><circle cx="7" cy="7" r="1.5"/>',
  upload: '<path d="M12 3v12"/><path d="m7 8 5-5 5 5"/><rect x="3" y="17" width="18" height="4" rx="1"/>',
  search: '<circle cx="11" cy="11" r="7"/><path d="m21 21-4.3-4.3"/>',
  "file-search": '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h9"/><path d="M14 2v6h6"/><circle cx="16" cy="17" r="3"/><path d="m21 21-1.5-1.5"/>',
  logout: '<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><path d="M16 17l5-5-5-5"/><path d="M21 12H9"/>',
  bell: '<path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9"/><path d="M10.3 21a2 2 0 0 0 3.4 0"/>',
  menu: '<path d="M3 6h18"/><path d="M3 12h18"/><path d="M3 18h18"/>',
  x: '<path d="M18 6 6 18"/><path d="m6 6 12 12"/>',
};

/** Devuelve el markup SVG de un icono. size en px (16/18/20/24). Hereda color
 * via `stroke:currentColor` salvo que el CSS del contenedor lo pise. */
export function icon(name, size = 18) {
  const body = PATHS[name];
  if (!body) return "";
  return `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">${body}</svg>`;
}
