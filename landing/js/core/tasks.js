// Indicador mínimo de Tasks activas (TaskManager, Fase 4 -- ver src/tasks.py
// y GET /api/server/{guild_id}/tasks). No es un sistema de "Jobs": un banner
// que se arma con una sola consulta al montar, y solo arranca polling
// mientras siga habiendo alguna Task running -- se apaga apenas todas pasan
// a completed/failed/cancelled, sin esperar al próximo ciclo. Nunca hay un
// setInterval permanente en el Dashboard: nace y muere con las Tasks mismas.
//
// Reusa .onboarding-banner (ver dash.css) y <progress class="prob-bar">
// (mismo patrón que probabilityField en dash.js, ver DESIGN_SYSTEM.md) en
// vez de inventar componentes nuevos.

import { apiFetch } from './api.js';
import { el } from './dom.js';
import { GUILD_ID } from './config.js';

const POLL_MS = 4500;
const DONE_MESSAGE_MS = 4000;

const TASK_LABELS = {
  gif_health_check: 'Verificación de GIFs',
  refeed_channels: 'Importación de historial',
};

function taskLabel(task) {
  return TASK_LABELS[task.type] || task.message || 'Tarea en curso';
}

function taskBannerRow(task) {
  const hasProgress = task.progress_total != null;
  const text = hasProgress
    ? `⟳ ${taskLabel(task)} · ${task.progress_current ?? 0}/${task.progress_total}`
    : `⟳ ${task.message || taskLabel(task)}`;
  const row = el('div', { class: 'onboarding-banner task-banner' }, el('span', {}, text));
  if (hasProgress) {
    row.append(el('progress', {
      class: 'prob-bar', value: task.progress_current ?? 0, max: task.progress_total,
    }));
  }
  return row;
}

function renderRunning(container, running) {
  container.innerHTML = '';
  for (const task of running) container.append(taskBannerRow(task));
}

function renderJustFinished(container, task) {
  container.innerHTML = '';
  const ok = task.status === 'completed';
  container.append(el('div', { class: 'onboarding-banner task-banner' },
    el('span', {}, `${ok ? '✅' : '❌'} ${taskLabel(task)} ${ok ? 'terminada' : 'fallida'}`)));
  setTimeout(() => { container.innerHTML = ''; }, DONE_MESSAGE_MS);
}

/** Monta el indicador en `container` (un elemento vacío que el caller ya
 * agregó al DOM) y hace la consulta inicial a GET /tasks. Si container se
 * desmonta (cambio de tab, recarga de la sección), el próximo tick lo nota
 * y para el polling solo -- no hace falta un stop() explícito. */
export async function watchTasks(container) {
  let timer = null;
  let running = new Map();

  async function tick() {
    if (!container.isConnected) {
      if (timer) clearInterval(timer);
      return;
    }
    let data;
    try {
      data = await apiFetch(`/api/server/${GUILD_ID}/tasks`);
    } catch {
      return; // poll de fondo: un error puntual no merece interrumpir la UI
    }
    if (!container.isConnected) {
      if (timer) clearInterval(timer);
      return;
    }

    const byId = new Map(data.tasks.map(t => [t.id, t]));
    const nowRunning = data.tasks.filter(t => t.status === 'running');
    // ponytail: si dos tasks terminan en el mismo tick, solo se avisa la
    // primera -- caso raro (requiere dos operaciones running a la vez para
    // el mismo guild) y esto es un indicador simple, no un centro de
    // notificaciones. Subir a una cola de avisos si alguna vez hace falta.
    const justFinishedId = [...running.keys()].find(id => !byId.has(id) || byId.get(id).status !== 'running');
    running = new Map(nowRunning.map(t => [t.id, t]));

    if (nowRunning.length) {
      renderRunning(container, nowRunning);
    } else if (justFinishedId && byId.get(justFinishedId)) {
      renderJustFinished(container, byId.get(justFinishedId));
    } else {
      container.innerHTML = '';
    }

    if (!nowRunning.length && timer) {
      clearInterval(timer);
      timer = null;
    } else if (nowRunning.length && !timer) {
      timer = setInterval(tick, POLL_MS);
    }
  }

  await tick();
}
