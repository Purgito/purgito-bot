// Estado compartido entre los editores de embeds (clásico + Layout V2).
// Único dueño de este estado: classic-editor.js, layout-editor.js,
// shared-ui.js y persistence.js lo leen desde acá en vez de tener cada uno su
// copia. Se expone `export let` (lectura como binding vivo) + un setter por
// variable, porque un importador no puede reasignar un binding importado.

// Sub-vista activa del tab Embeds: 'editor' o 'templates'.
export let _embedTab = 'editor';
// Modo de contenido: 'classic' (embeds clásicos) o 'layout' (Components V2).
// Discord no permite combinar ambos en un mismo mensaje.
export let _embedMode = 'classic';
// Documento del editor clásico: array de hasta 10 embeds + el embed activo +
// datos de la plantilla cargada (si aplica). Persiste al cambiar de sub-vista.
export let _embedDoc = null;
// Documento del editor Layout V2 (bloques). Se mantiene aparte del clásico,
// así cambiar de modo no destruye el trabajo del otro editor.
export let _layoutDoc = null;

export function setEmbedTab(v) { _embedTab = v; }
export function setEmbedMode(v) { _embedMode = v; }
export function setEmbedDoc(v) { _embedDoc = v; }
export function setLayoutDoc(v) { _layoutDoc = v; }
