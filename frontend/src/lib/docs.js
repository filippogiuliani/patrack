// Documents: categories, suggested types, formatting of sizes and amounts.
import { language, t } from './i18n.svelte.js';
import { daysFromToday, fmtDate } from './date.js';

export const CATEGORIES = ['identity', 'health', 'child', 'home', 'car', 'tax', 'work', 'purchases', 'bank', 'insurance', 'other'];
export const categoryName = (c) => (c ? t('cat.' + c) : t('cat.none'));

// Typical documents of each category, offered while typing the type (the family's own types come first)
const TYPES = {
  it: {
    identity: ["Carta d'identità", 'Passaporto', 'Patente', 'Tessera sanitaria', 'Codice fiscale', 'Permesso di soggiorno', 'Certificato di nascita', 'Stato di famiglia'],
    health: ['Referto', 'Esami del sangue', 'Ricetta', 'Certificato vaccinale', 'Visita specialistica', 'Lettera di dimissione', 'Scontrino farmacia', 'Fattura medica', 'Esenzione'],
    child: ['Visita pediatrica', 'Libretto vaccinale', 'Certificato medico', 'Iscrizione nido', 'Iscrizione scuola', 'Pagella', 'Retta nido', 'Bilancio di salute'],
    home: ['Bolletta luce', 'Bolletta gas', 'Bolletta acqua', 'Bolletta internet', 'Contratto di affitto', 'Rata mutuo', 'Atto di compravendita', 'Spese condominiali', 'Verbale condominio', 'TARI', 'IMU', 'Planimetria', 'Certificazione impianti'],
    car: ['Libretto di circolazione', 'Certificato di proprietà', 'Polizza RC auto', 'Bollo auto', 'Revisione', 'Tagliando', 'Multa', 'Fattura officina'],
    tax: ['Modello 730', 'Certificazione Unica (CU)', 'F24', 'Ricevuta spesa detraibile', 'Dichiarazione dei redditi', 'ISEE'],
    work: ['Busta paga', 'Contratto di lavoro', 'CUD', 'Lettera di assunzione', 'Nota spese', 'Estratto contributivo'],
    purchases: ['Scontrino', 'Fattura', 'Garanzia', 'Manuale', 'Ricevuta', 'Prova di acquisto'],
    bank: ['Estratto conto', 'Contratto conto corrente', 'Contabile bonifico', 'Rendiconto investimenti', 'Mutuo', 'Carta di credito'],
    insurance: ['Polizza casa', 'Polizza vita', 'Polizza salute', 'Quietanza', 'Denuncia sinistro'],
    other: [],
  },
  en: {
    identity: ['ID card', 'Passport', 'Driving licence', 'Health card', 'Tax code', 'Residence permit', 'Birth certificate'],
    health: ['Medical report', 'Blood test', 'Prescription', 'Vaccination certificate', 'Specialist visit', 'Discharge letter', 'Pharmacy receipt', 'Medical invoice'],
    child: ['Paediatric visit', 'Vaccination booklet', 'Medical certificate', 'Nursery enrolment', 'School enrolment', 'School report', 'Nursery fee'],
    home: ['Electricity bill', 'Gas bill', 'Water bill', 'Internet bill', 'Rental contract', 'Mortgage payment', 'Deed', 'Condominium fees', 'Waste tax', 'Property tax'],
    car: ['Registration document', 'Certificate of ownership', 'Car insurance', 'Car tax', 'MOT / inspection', 'Service', 'Fine', 'Garage invoice'],
    tax: ['Tax return (730)', 'Income statement (CU)', 'F24 payment', 'Deductible expense receipt', 'ISEE'],
    work: ['Payslip', 'Employment contract', 'Hiring letter', 'Expense report', 'Pension statement'],
    purchases: ['Receipt', 'Invoice', 'Warranty', 'Manual', 'Proof of purchase'],
    bank: ['Bank statement', 'Account contract', 'Transfer receipt', 'Investment report', 'Mortgage', 'Credit card'],
    insurance: ['Home insurance', 'Life insurance', 'Health insurance', 'Premium receipt', 'Claim'],
    other: [],
  },
};

/** Types to suggest: the family's own first, then the typical ones of the category. */
export function typeSuggestions(category, own = []) {
  const lang = TYPES[language.id] ?? TYPES.it;
  const typical = category ? lang[category] ?? [] : Object.values(lang).flat();
  return [...new Set([...own, ...typical])];
}

export function fmtSize(bytes) {
  if (bytes == null) return '';
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1).replace('.0', '')} MB`;
}

export function fmtAmount(cents) {
  if (cents == null) return '';
  return new Intl.NumberFormat(language.locale, { style: 'currency', currency: 'EUR' }).format(cents / 100);
}
/** Cents → what the amount field shows ("12,50" in Italian). */
export function amountInput(cents) {
  if (cents == null) return '';
  return new Intl.NumberFormat(language.locale, { minimumFractionDigits: 2, maximumFractionDigits: 2, useGrouping: false }).format(cents / 100);
}

/** Expiry: { text, level } where level is expired | soon | ok */
export function expiryInfo(date) {
  if (!date) return null;
  const n = daysFromToday(date);
  if (n < 0) return { text: t('expiry.expired_on', { date: fmtDate(date) }), level: 'expired' };
  if (n <= 60) return { text: n === 0 ? t('expiry.today') : t('expiry.in_days', { n }), level: 'soon' };
  return { text: t('expiry.until', { date: fmtDate(date) }), level: 'ok' };
}

/** Message of a reason key (why an import failed or a document is "da sistemare"). */
export const reasonText = (key) => (key ? t('reason.' + key) : '');

/** Highlighted extract from the search: "[[word]]" → <mark>, everything else escaped. */
export function snippetHtml(s) {
  const esc = (x) => x.replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  return esc(s).replace(/\[\[/g, '<mark>').replace(/\]\]/g, '</mark>');
}
