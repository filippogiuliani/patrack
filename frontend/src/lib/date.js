// Dates as local ISO strings (YYYY-MM-DD), never through UTC; names in the chosen language
import { language, t } from './i18n.svelte.js';

const pad = (n) => String(n).padStart(2, '0');
export const iso = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
export const parse = (s) => { const [y, m, d] = s.split('-').map(Number); return new Date(y, m - 1, d); };
export const today = () => iso(new Date());
export const addDays = (s, n) => { const d = parse(s); d.setDate(d.getDate() + n); return iso(d); };
export const daysBetween = (a, b) => Math.round((parse(a) - parse(b)) / 86400000);

const fmt = (s, options) => new Intl.DateTimeFormat(language.locale, options).format(parse(s));
export const fmtLong = (s) => fmt(s, { weekday: 'long', day: 'numeric', month: 'long' });
export const fmtShort = (s) => fmt(s, { day: 'numeric', month: 'short' });
export const fmtDate = (s) => fmt(s, { day: '2-digit', month: '2-digit', year: 'numeric' });
export function relative(s) {
  const n = daysBetween(today(), s);
  if (n === 0) return t('date.today');
  if (n === 1) return t('date.yesterday');
  if (n > 1 && n < 7) return t('date.days_ago', { n });
  return null;
}
export function fmtRange(start, end) {
  const a = parse(start), b = parse(end);
  if (a.getMonth() === b.getMonth()) return `${a.getDate()} – ${fmt(end, { day: 'numeric', month: 'long' })}`;
  return `${fmtShort(start)} – ${fmtShort(end)}`;
}
/** Age in months (for children) */
export function ageInMonths(birth) {
  if (!birth) return null;
  const a = parse(birth), b = new Date();
  return (b.getFullYear() - a.getFullYear()) * 12 + b.getMonth() - a.getMonth() - (b.getDate() < a.getDate() ? 1 : 0);
}
/** Weekday with Monday = 0 … Sunday = 6 (as in the weekly plan) */
export const weekdayOf = (s) => (parse(s).getDay() + 6) % 7;
/** Weekday name (0 = Monday); 1 January 2024 was a Monday */
export const weekdayName = (i, style = 'long') =>
  new Intl.DateTimeFormat(language.locale, { weekday: style }).format(new Date(2024, 0, 1 + i));

/** Days from today to `s` (negative = in the past) */
export const daysFromToday = (s) => daysBetween(s, today());
export const fmtDayMonth = (s) => fmt(s, { weekday: 'short', day: 'numeric', month: 'short' });
export const fmtFull = (s) => fmt(s, { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' });
export const fmtMonth = (s) => fmt(s, { month: 'long', year: 'numeric' });
/** "oggi", "domani", "tra 5 giorni", "3 giorni fa", "tra 2 mesi" … */
export function fromNow(s) {
  const n = daysFromToday(s);
  if (n === 0) return t('date.today');
  if (n === 1) return t('date.tomorrow');
  if (n === -1) return t('date.yesterday');
  const abs = Math.abs(n);
  let v;
  if (abs < 45) v = t(abs === 1 ? 'date.n_day' : 'date.n_days', { n: abs });
  else if (abs < 365 * 1.5) { const m = Math.round(abs / 30.4); v = t(m === 1 ? 'date.n_month' : 'date.n_months', { n: m }); }
  else { const y = Math.round((abs / 365.25) * 10) / 10; v = t(y === 1 ? 'date.n_year' : 'date.n_years', { n: y }); }
  return n > 0 ? t('date.in', { v }) : t('date.ago', { v });
}
