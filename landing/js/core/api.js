import { getLoginUrl } from './config.js';

export async function apiFetch(url, options = {}) {
  const opts = { credentials: 'include', ...options };
  opts.headers = { ...(opts.headers || {}) };
  if (opts.body && !(opts.body instanceof FormData) && !(opts.body instanceof Blob)) {
    if (!opts.headers['Content-Type'] && !opts.headers['content-type']) {
      opts.headers['Content-Type'] = 'application/json';
    }
    if (typeof opts.body !== 'string') {
      opts.body = JSON.stringify(opts.body);
    }
  }
  let r;
  try {
    r = await fetch(url, opts);
  } catch (e) {
    throw new Error('No se pudo conectar con el servidor. Revisa tu conexión e intenta de nuevo.');
  }
  if (r.status === 401) {
    location.href = getLoginUrl();
    throw new Error('Sesión expirada.');
  }
  const data = await r.json().catch(() => ({}));
  if (!r.ok) {
    const err = new Error(data.error || humanError(r.status));
    err.status = r.status;
    err.premium = !!data.premium;
    throw err;
  }
  return data;
}

export function humanError(status) {
  if (status === 429) return 'Estás haciendo demasiadas solicitudes — espera un momento e intenta de nuevo.';
  if (status >= 500) return 'Algo salió mal de nuestro lado. Intenta de nuevo en un rato.';
  if (status === 403) return 'No tienes permiso para hacer esto.';
  if (status === 404) return 'No se encontró lo que buscabas.';
  return 'No se pudo completar la solicitud (código ' + status + ').';
}
