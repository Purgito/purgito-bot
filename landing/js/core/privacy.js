// Lógica pura del Centro de Privacidad (sin DOM ni fetch): interpreta lo que devuelve
// /api/me/privacy para pintar el estado de una solicitud. Se prueba con test_privacy.mjs.

const DAY_MS = 86_400_000;
const OPEN = new Set(['pending', 'processing', 'failed']);

/** La API manda "AAAA-MM-DD HH:MM:SS" en UTC, sin zona: se lee como UTC. */
export function parseUtc(text) {
  if (!text) return null;
  const d = new Date(String(text).replace(' ', 'T') + 'Z');
  return Number.isNaN(d.getTime()) ? null : d;
}

/** La solicitud abierta (pendiente, procesando o en reintento), si hay. */
export function openRequest(requests) {
  return (requests || []).find((r) => OPEN.has(r.status)) || null;
}

/**
 * Estado legible de una solicitud.
 *  state: queued | processing | retrying | completed
 *  daysLeft: días enteros hasta el plazo máximo (>= 0), null si ya terminó
 *  overdue: el plazo pasó y sigue abierta
 * Un fallo interno se muestra como "retrying": la persona no necesita el detalle.
 */
export function describeRequest(req, now = new Date()) {
  const created = parseUtc(req.created_at);
  const due = parseUtc(req.due_at);
  const completed = parseUtc(req.completed_at);
  if (req.status === 'completed') {
    return { state: 'completed', created, due, completed, daysLeft: null, overdue: false };
  }
  const msLeft = due ? due.getTime() - now.getTime() : null;
  return {
    state: req.status === 'processing' ? 'processing' : req.status === 'failed' ? 'retrying' : 'queued',
    created,
    due,
    completed: null,
    daysLeft: msLeft === null ? null : Math.max(0, Math.ceil(msLeft / DAY_MS)),
    overdue: msLeft !== null && msLeft < 0,
  };
}

/** Solicitudes terminadas, de la más reciente a la más antigua. */
export function history(requests) {
  return (requests || [])
    .filter((r) => r.status === 'completed')
    .sort((a, b) => (b.completed_at || '').localeCompare(a.completed_at || ''));
}

/** ¿Hay que volver a consultar el estado? Solo mientras haya una solicitud abierta. */
export function shouldPoll(requests) {
  return openRequest(requests) !== null;
}
