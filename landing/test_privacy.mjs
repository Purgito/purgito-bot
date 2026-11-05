// Pruebas de la lógica pura del Centro de Privacidad: node landing/test_privacy.mjs
import assert from 'node:assert/strict';
import { parseUtc, openRequest, describeRequest, history, shouldPoll } from './js/core/privacy.js';

const NOW = new Date('2026-11-10T12:00:00Z');

assert.equal(parseUtc('2026-11-06 12:00:00').toISOString(), '2026-11-06T12:00:00.000Z');
assert.equal(parseUtc(null), null);
assert.equal(parseUtc('basura'), null);

// Estados: un fallo interno se ve como reintento, nunca como error
const base = { id: 1, created_at: '2026-11-06 12:00:00', due_at: '2026-11-13 12:00:00', completed_at: null };
assert.equal(describeRequest({ ...base, status: 'pending' }, NOW).state, 'queued');
assert.equal(describeRequest({ ...base, status: 'processing' }, NOW).state, 'processing');
assert.equal(describeRequest({ ...base, status: 'failed' }, NOW).state, 'retrying');

// Días restantes y vencida
assert.equal(describeRequest({ ...base, status: 'pending' }, NOW).daysLeft, 3);
const late = describeRequest({ ...base, status: 'failed' }, new Date('2026-11-14T00:00:00Z'));
assert.equal(late.overdue, true);
assert.equal(late.daysLeft, 0);

// Completada: sin plazo ni vencimiento
const done = describeRequest({ ...base, status: 'completed', completed_at: '2026-11-06 12:01:00' }, NOW);
assert.equal(done.state, 'completed');
assert.equal(done.daysLeft, null);
assert.equal(done.overdue, false);
assert.equal(done.completed.toISOString(), '2026-11-06T12:01:00.000Z');

// Solicitud abierta, historial y sondeo
const list = [
  { ...base, id: 3, status: 'completed', completed_at: '2026-10-01 10:00:00' },
  { ...base, id: 2, status: 'completed', completed_at: '2026-10-20 10:00:00' },
  { ...base, id: 4, status: 'pending' },
];
assert.equal(openRequest(list).id, 4);
assert.deepEqual(history(list).map((r) => r.id), [2, 3]);
assert.equal(shouldPoll(list), true);
assert.equal(shouldPoll(history(list)), false);
assert.equal(openRequest([]), null);
assert.equal(openRequest(undefined), null);

console.log('test_privacy: ok');
