/** Small formatting helpers. No dates library — one is not worth 30 KB here. */

const MONTHS = [
  "Jan", "Feb", "Mar", "Apr", "May", "Jun",
  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
];

/** `2026-06-30T01:02:30Z` -> `30 Jun 2026`. Falls back to the raw string. */
export function formatDate(iso) {
  const d = parse(iso);
  if (!d) return iso || "";
  return `${d.getDate()} ${MONTHS[d.getMonth()]} ${d.getFullYear()}`;
}

/** `2026-06-30T01:02:30Z` -> `30 Jun 2026, 01:02`. */
export function formatDateTime(iso) {
  const d = parse(iso);
  if (!d) return iso || "";
  const hh = String(d.getHours()).padStart(2, "0");
  const mm = String(d.getMinutes()).padStart(2, "0");
  return `${formatDate(iso)}, ${hh}:${mm}`;
}

/** `2026-06-30T01:02:30Z` -> `2026-06`. Used for grouping. */
export function monthKey(iso) {
  const d = parse(iso);
  if (!d) return "";
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

/** `2026-06-30T01:02:30Z` -> `Jun 2026`. */
export function monthLabel(iso) {
  const d = parse(iso);
  if (!d) return "";
  return `${MONTHS[d.getMonth()]} ${d.getFullYear()}`;
}

export function formatCount(n) {
  return Number(n || 0).toLocaleString();
}

export function formatBytes(n) {
  const value = Number(n || 0);
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / (1024 * 1024)).toFixed(1)} MB`;
}

function parse(iso) {
  if (!iso) return null;
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? null : d;
}
