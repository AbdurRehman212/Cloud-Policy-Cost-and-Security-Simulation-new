/** Date formatting that follows the user's saved date format (Settings → Appearance). */
const pad = (n) => String(n).padStart(2, '0');

// The API returns naive UTC timestamps (no "Z"); treat them as UTC.
export const parseApiDate = (value) => {
  if (!value) return null;
  if (value instanceof Date) return value;
  const text = String(value);
  const date = new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(text) ? text : `${text}Z`);
  return Number.isNaN(date.getTime()) ? null : date;
};

export const formatDate = (value, format = 'YYYY-MM-DD') => {
  const date = parseApiDate(value);
  if (!date) return '—';
  const y = date.getFullYear();
  const m = pad(date.getMonth() + 1);
  const d = pad(date.getDate());
  if (format === 'DD/MM/YYYY') return `${d}/${m}/${y}`;
  if (format === 'MM/DD/YYYY') return `${m}/${d}/${y}`;
  return `${y}-${m}-${d}`;
};

export const formatDateTime = (value, format = 'YYYY-MM-DD') => {
  const date = parseApiDate(value);
  if (!date) return '—';
  return `${formatDate(date, format)} ${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`;
};

export const humanize = (value) =>
  String(value || '')
    .replace(/[_:]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
    .replace(/^./, (c) => c.toUpperCase());
