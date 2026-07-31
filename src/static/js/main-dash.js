// Punto de entrada de /es/dashboard/{guild_id}* (pages/dash.py).
import { setGuildId } from './core/config.js';
import { initDash } from './dash.js';

const script = document.querySelector('script[data-guild-id]');
setGuildId(script ? script.dataset.guildId : '');
initDash();
