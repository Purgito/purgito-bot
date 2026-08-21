/* Check del reescrito de prefijo de idioma en script.js.
   node landing/test_lang.mjs — falla si la lógica de /es/…//en/… se rompe. */
import assert from 'node:assert/strict';
import { readFileSync, existsSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

const LANGS = ['es', 'en', 'ru', 'ja', 'de'];
const LANDING = fileURLToPath(new URL('.', import.meta.url));

// Espejo de SLUG_MAP_ES_EN en landing/build_docs.py y en landing/script.js.
// Los tres deben coincidir -- el check de "existe en disco" de más abajo es
// justamente lo que detecta un desincronizado.
const SLUG_MAP_ES_EN = {
  terminos: 'terms',
  privacidad: 'privacy',
  reembolsos: 'refunds',
  documentacion: 'documentation',
  'documentacion/arquitectura': 'documentation/architecture',
  'documentacion/discord': 'documentation/discord',
  'documentacion/api': 'documentation/api',
  'documentacion/generacion': 'documentation/generation',
  'documentacion/almacenamiento': 'documentation/storage',
  'documentacion/seguridad': 'documentation/security',
  'documentacion/infraestructura': 'documentation/infrastructure',
  'documentacion/desarrollo': 'documentation/development',
  'documentacion/referencia': 'documentation/reference',
};
const SLUG_MAP_EN_ES = Object.fromEntries(
  Object.entries(SLUG_MAP_ES_EN).map(([es, en]) => [en, es])
);

// Misma lógica que translateRest() en script.js.
function translateRest(rest, from, to) {
  const slug = rest.replace(/^\/|\/$/g, '');
  if (!slug) return rest;
  let mapped = slug;
  if (from === 'es' && to === 'en') mapped = SLUG_MAP_ES_EN[slug] || slug;
  else if (from === 'en' && to === 'es') mapped = SLUG_MAP_EN_ES[slug] || slug;
  return '/' + mapped;
}

// Misma lógica que el bloque del selector de idioma en script.js.
function hrefFor(pathname, lang) {
  const seg = pathname.split('/')[1];
  const current = LANGS.includes(seg) ? seg : 'es';
  const rest = LANGS.includes(seg) ? pathname.slice(seg.length + 1) : pathname;
  return '/' + lang + (translateRest(rest || '/', current, lang) || '/');
}

assert.equal(hrefFor('/es/', 'en'), '/en/');
assert.equal(hrefFor('/es', 'en'), '/en/');            // sin barra final
assert.equal(hrefFor('/es/docs', 'ja'), '/ja/docs');   // conserva el resto (slug sin mapeo)
assert.equal(hrefFor('/', 'de'), '/de/');              // servida sin prefijo
assert.equal(hrefFor('/docs/guia', 'ru'), '/ru/docs/guia');
assert.equal(hrefFor('/estado', 'es'), '/es/estado');  // "estado" no es idioma
assert.equal(hrefFor('/en/premium', 'es'), '/es/premium');

// Slugs que SÍ cambian entre ES y EN: el selector tiene que traducirlos, no
// solo conservar el prefijo.
assert.equal(hrefFor('/es/terminos', 'en'), '/en/terms');
assert.equal(hrefFor('/en/terms', 'es'), '/es/terminos');
assert.equal(hrefFor('/es/privacidad', 'en'), '/en/privacy');
assert.equal(hrefFor('/en/privacy', 'es'), '/es/privacidad');
assert.equal(hrefFor('/es/reembolsos', 'en'), '/en/refunds');
assert.equal(hrefFor('/en/refunds', 'es'), '/es/reembolsos');
assert.equal(hrefFor('/es/documentacion', 'en'), '/en/documentation');
assert.equal(hrefFor('/en/documentation', 'es'), '/es/documentacion');
assert.equal(hrefFor('/es/documentacion/arquitectura', 'en'), '/en/documentation/architecture');
assert.equal(hrefFor('/en/documentation/architecture', 'es'), '/es/documentacion/arquitectura');
assert.equal(hrefFor('/es/documentacion/desarrollo', 'en'), '/en/documentation/development');
assert.equal(hrefFor('/en/documentation/development', 'es'), '/es/documentacion/desarrollo');

// Slugs que se mantienen iguales en los dos idiomas: el selector conserva el
// resto tal cual, sin necesitar una entrada en el mapa.
for (const same of ['guia', 'premium', 'estado', 'dashboard', 'perfil/servidores', 'perfil/conexiones', 'perfil/facturacion']) {
  assert.equal(hrefFor(`/es/${same}`, 'en'), `/en/${same}`, `slug idéntico roto: ${same}`);
  assert.equal(hrefFor(`/en/${same}`, 'es'), `/es/${same}`, `slug idéntico roto (vuelta): ${same}`);
}

// El mapeo tiene que ser reversible en ambos sentidos (auditado también en
// build_docs.py con el mismo assert, sobre la copia Python del mapa).
for (const [es, en] of Object.entries(SLUG_MAP_ES_EN)) {
  assert.equal(SLUG_MAP_EN_ES[en], es, `mapeo no reversible: ${es} <-> ${en}`);
}

// Cada slug del mapa tiene página real de los dos lados -- si build_docs.py
// no llegó a generarla (o el slug está mal escrito acá), esto lo detecta en
// vez de fallar recién en producción con un 404 al cambiar de idioma.
for (const [es, en] of Object.entries(SLUG_MAP_ES_EN)) {
  const esPath = `${LANDING}es/${es}/index.html`;
  const enPath = `${LANDING}en/${en}/index.html`;
  assert.ok(existsSync(esPath), `falta la página ES generada: ${esPath}`);
  assert.ok(existsSync(enPath), `falta la página EN generada: ${enPath}`);
}
// Idem para los slugs idénticos en ambos idiomas.
for (const same of ['guia', 'premium', 'estado', 'dashboard', 'perfil', 'perfil/servidores', 'perfil/conexiones', 'perfil/facturacion']) {
  assert.ok(existsSync(`${LANDING}es/${same}/index.html`), `falta ES: ${same}`);
  assert.ok(existsSync(`${LANDING}en/${same}/index.html`), `falta EN: ${same}`);
}
// Las dos homepages (index.html sirve /es/ y /; en/index.html es el fallback
// real de nginx para /en/, ver build_docs.py main()).
assert.ok(existsSync(`${LANDING}index.html`), 'falta landing/index.html');
assert.ok(existsSync(`${LANDING}en/index.html`), 'falta landing/en/index.html (fallback de nginx para /en/)');

// Misma lógica que el redirect sin prefijo del <head> de index.html /
// index.en.html. 'es' y 'en' ya tienen traducción; ru/ja/de siguen
// "Próximamente" en el selector (ver window.READY_LANGS).
const READY = ['es', 'en'];
function redirectTo(pathname, accept) {
  if (/^\/(es|en|ru|ja|de)(\/|$)/.test(pathname)) return null;  // ya tiene prefijo
  const pick = accept.map(l => l.slice(0, 2).toLowerCase()).find(l => READY.includes(l)) || 'es';
  return '/' + pick + pathname;
}

assert.equal(redirectTo('/', ['en-US', 'en']), '/en/');       // con traducción → en
assert.equal(redirectTo('/', ['es-CL']), '/es/');
assert.equal(redirectTo('/', ['ja']), '/es/');                 // sin traducción → es (default)
assert.equal(redirectTo('/', []), '/es/');                    // sin Accept-Language
assert.equal(redirectTo('/premium', ['ja']), '/es/premium');  // conserva el resto
assert.equal(redirectTo('/premium', ['en']), '/en/premium');
assert.equal(redirectTo('/es/', ['en']), null);               // no redirige en loop
assert.equal(redirectTo('/en/docs', ['en']), null);           // prefijo válido, aunque falte contenido
assert.equal(redirectTo('/estado', ['en']), '/en/estado');    // "estado" no es prefijo de idioma

// Los 5 idiomas del boceto están en el HTML, con el orden y los nombres
// exactos -- en las DOS homepages (index.html e index.en.html), ya que cada
// una arma el selector desde su propia copia estática del menú.
for (const file of ['index.html', 'index.en.html']) {
  const html = readFileSync(new URL(`./${file}`, import.meta.url), 'utf8');
  for (const [lang, name] of [['es', 'Español'], ['en', 'English'], ['ru', 'Русский'], ['ja', '日本語'], ['de', 'Deutsch']]) {
    assert.ok(html.includes(`data-lang="${lang}"`), `${file}: falta el idioma ${lang}`);
    assert.ok(html.includes(name), `${file}: falta el nombre ${name}`);
  }
  // READY_LANGS tiene que incluir 'en' en las dos -- si index.en.html se
  // desincroniza del array de index.html, el redirect deja de coincidir con
  // lo que hrefFor()/redirectTo() de este mismo test asumen.
  assert.match(html, /window\.READY_LANGS = \['es', 'en'\];/, `${file}: READY_LANGS desactualizado`);
}

// hreflang + canonical: toda página ES generada tiene su alternate EN con la
// URL real, y viceversa (muestreo sobre el mapa de slugs, que cubre los
// casos con slug distinto -- los más propensos a un href mal armado).
const allSlugs = [
  ...Object.entries(SLUG_MAP_ES_EN),
  ...['guia', 'premium', 'estado', 'dashboard', 'perfil', 'perfil/servidores', 'perfil/conexiones', 'perfil/facturacion'].map(s => [s, s]),
];

for (const [es, en] of allSlugs) {
  const esHtml = readFileSync(`${LANDING}es/${es}/index.html`, 'utf8');
  const enHtml = readFileSync(`${LANDING}en/${en}/index.html`, 'utf8');
  assert.match(esHtml, /<html lang="es">/, `${es}: <html lang> no es "es"`);
  assert.match(enHtml, /<html lang="en">/, `${en}: <html lang> no es "en"`);
  assert.ok(esHtml.includes(`<link rel="canonical" href="https://purgito.app/es/${es}">`), `${es}: canonical roto`);
  assert.ok(enHtml.includes(`<link rel="canonical" href="https://purgito.app/en/${en}">`), `${en}: canonical roto`);
  assert.ok(esHtml.includes(`hreflang="en" href="https://purgito.app/en/${en}">`), `${es}: hreflang en roto`);
  assert.ok(esHtml.includes(`hreflang="es" href="https://purgito.app/es/${es}">`), `${es}: hreflang es roto`);
  assert.ok(esHtml.includes(`hreflang="x-default" href="https://purgito.app/es/${es}">`), `${es}: hreflang x-default roto`);
  assert.ok(enHtml.includes(`hreflang="x-default" href="https://purgito.app/es/${es}">`), `${en}: hreflang x-default roto en EN`);
}

// Verificación de que las páginas en inglés no contienen títulos o strings principales en español
const enHome = readFileSync(`${LANDING}en/index.html`, 'utf8');
assert.ok(enHome.includes('A bot that mimics your community'), 'en/index.html: falta título en inglés');
assert.ok(!enHome.includes('Un bot que imita tu comunidad'), 'en/index.html: contiene título en español');

const enTerms = readFileSync(`${LANDING}en/terms/index.html`, 'utf8');
assert.ok(enTerms.includes('Terms of Service'), 'en/terms: falta título en inglés');
assert.ok(!enTerms.includes('Términos del Servicio — Purgito'), 'en/terms: contiene título en español');

const enPrivacy = readFileSync(`${LANDING}en/privacy/index.html`, 'utf8');
assert.ok(enPrivacy.includes('Privacy Policy'), 'en/privacy: falta título en inglés');
assert.ok(!enPrivacy.includes('Política de Privacidad — Purgito'), 'en/privacy: contiene título en español');

const enRefunds = readFileSync(`${LANDING}en/refunds/index.html`, 'utf8');
assert.ok(enRefunds.includes('Refund Policy'), 'en/refunds: falta título en inglés');
assert.ok(!enRefunds.includes('Política de Reembolso — Purgito'), 'en/refunds: contiene título en español');

const enDocs = readFileSync(`${LANDING}en/documentation/index.html`, 'utf8');
assert.ok(enDocs.includes('Technical Documentation'), 'en/documentation: falta título en inglés');
assert.ok(!enDocs.includes('Documentación técnica — Purgito'), 'en/documentation: contiene título en español');

const enGuia = readFileSync(`${LANDING}en/guia/index.html`, 'utf8');
assert.ok(enGuia.includes('Purgito Guide'), 'en/guia: falta título en inglés');
assert.ok(!enGuia.includes('Guía de Purgito — Purgito'), 'en/guia: contiene título en español');

const enEstado = readFileSync(`${LANDING}en/estado/index.html`, 'utf8');
assert.ok(enEstado.includes('Purgito Status'), 'en/estado: falta título en inglés');
assert.ok(!enEstado.includes('Estado de Purgito — Purgito'), 'en/estado: contiene título en español');

console.log('ok');
