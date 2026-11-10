// UI translations. To add a language: a new file in ./locales and a line in LANGUAGES.
import it from './locales/it.js';
import en from './locales/en.js';

export const LANGUAGES = [
  { id: 'it', name: 'Italiano' },
  { id: 'en', name: 'English' },
];
const DICTIONARIES = { it, en };
const STORAGE_KEY = 'patrack.language';

export const DEFAULT_LANGUAGE = 'it';
// Browser preferences, e.g. ['pt-BR', 'pt', 'en-US']
const BROWSER = (navigator.languages?.length ? navigator.languages : [navigator.language]).filter(Boolean).map(String);

/** First browser language we have a translation for, otherwise Italian */
function detect() {
  return BROWSER.map((tag) => tag.slice(0, 2).toLowerCase()).find((id) => DICTIONARIES[id]) ?? DEFAULT_LANGUAGE;
}

/** Locale used for dates and numbers: the browser's regional variant of the language when it has one
 *  (e.g. en-GB → day/month, en-US → month/day), otherwise the plain language code. */
function regionalLocale(id) {
  return BROWSER.find((tag) => tag.slice(0, 2).toLowerCase() === id && tag.length > 2) ?? id;
}

function initial() {
  try {
    const saved = localStorage.getItem(STORAGE_KEY);
    if (DICTIONARIES[saved]) return saved; // chosen by hand earlier on this device
  } catch { /* storage unavailable */ }
  return detect();
}

const startId = initial();
export const language = $state({ id: startId, locale: regionalLocale(startId) });
document.documentElement.lang = language.id;

export function setLanguage(id) {
  if (!DICTIONARIES[id]) return;
  language.id = id;
  language.locale = regionalLocale(id);
  document.documentElement.lang = id;
  try { localStorage.setItem(STORAGE_KEY, id); } catch { /* ignore */ }
}

/** Translated text; {name} in the text is replaced with values.name */
export function t(key, values) {
  const s = DICTIONARIES[language.id]?.[key] ?? DICTIONARIES[DEFAULT_LANGUAGE][key] ?? key;
  return values ? s.replace(/\{(\w+)\}/g, (_, k) => values[k] ?? '') : s;
}
