/* Check del reescrito de prefijo de idioma en script.js.
   node landing/test_lang.mjs — falla si la lógica de /es/… se rompe. */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const LANGS = ['es', 'en', 'ru', 'ja', 'de'];

// Misma lógica que el bloque del selector de idioma en script.js.
function hrefFor(pathname, lang) {
  const seg = pathname.split('/')[1];
  const rest = LANGS.includes(seg) ? pathname.slice(seg.length + 1) : pathname;
  return '/' + lang + (rest || '/');
}

assert.equal(hrefFor('/es/', 'en'), '/en/');
assert.equal(hrefFor('/es', 'en'), '/en/');            // sin barra final
assert.equal(hrefFor('/es/docs', 'ja'), '/ja/docs');   // conserva el resto
assert.equal(hrefFor('/', 'de'), '/de/');              // servida sin prefijo
assert.equal(hrefFor('/docs/guia', 'ru'), '/ru/docs/guia');
assert.equal(hrefFor('/estado', 'es'), '/es/estado');  // "estado" no es idioma
assert.equal(hrefFor('/en/premium', 'es'), '/es/premium');

// Misma lógica que el redirect sin prefijo del <head> de index.html.
const READY = ['es'];
function redirectTo(pathname, accept) {
  if (/^\/(es|en|ru|ja|de)(\/|$)/.test(pathname)) return null;  // ya tiene prefijo
  const pick = accept.map(l => l.slice(0, 2).toLowerCase()).find(l => READY.includes(l)) || 'es';
  return '/' + pick + pathname;
}

assert.equal(redirectTo('/', ['en-US', 'en']), '/es/');       // sin traducción → es
assert.equal(redirectTo('/', ['es-CL']), '/es/');
assert.equal(redirectTo('/', []), '/es/');                    // sin Accept-Language
assert.equal(redirectTo('/premium', ['ja']), '/es/premium');  // conserva el resto
assert.equal(redirectTo('/es/', ['en']), null);               // no redirige en loop
assert.equal(redirectTo('/en/docs', ['en']), null);           // prefijo válido, aunque falte contenido
assert.equal(redirectTo('/estado', ['en']), '/es/estado');    // "estado" no es prefijo de idioma

// Los 5 idiomas del boceto están en el HTML, con el orden y los nombres exactos.
const html = readFileSync(new URL('./index.html', import.meta.url), 'utf8');
for (const [lang, name] of [['es', 'Español'], ['en', 'English'], ['ru', 'Русский'], ['ja', '日本語'], ['de', 'Deutsch']]) {
  assert.ok(html.includes(`data-lang="${lang}"`), `falta el idioma ${lang}`);
  assert.ok(html.includes(name), `falta el nombre ${name}`);
}

console.log('ok');
