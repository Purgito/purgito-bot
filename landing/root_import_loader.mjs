// Hook de resolución de módulos para poder importar landing/js/**/*.js desde
// Node sin bundler ni servidor: en el navegador esos imports son
// root-relative ("/js/core/api.js") porque nginx los sirve desde la raíz del
// sitio; Node no sabe qué es "la raíz del sitio", así que acá se reescriben
// al árbol real bajo landing/. Solo para tests (test_historial.mjs) -- no
// se usa en producción, donde nunca corre JS de landing/ bajo Node.
const ROOT = new URL('./', import.meta.url);

export async function resolve(specifier, context, nextResolve) {
  if (specifier.startsWith('/js/')) {
    return nextResolve(new URL('.' + specifier, ROOT).href, context);
  }
  return nextResolve(specifier, context);
}
