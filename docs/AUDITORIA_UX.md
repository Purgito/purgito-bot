# Auditoría UX — "el usuario menos técnico posible"

Fecha: 2026-07-03. Alcance: todos los cogs, `generation.py`, `webapi.py`,
`gif_gallery.py`, `meme_generator.py`, `r2.py`, `music_player.py`,
`help_view.py`, `i18n.py`, `panel.js` y `src/pages/`.

Premisa: quien prueba el bot llegó por Discord Discovery, no leyó nada y no
puede (ni quiere) leer logs. Ordenado de mayor a menor impacto
(probabilidad de toparse con el problema × daño a la primera impresión).

El fix del fallback `"..."` (menciones y `/generar` sin historial) ya está
aplicado en esta misma tanda y no se repite aquí.

Nota: el prompt mencionaba "Lavalink" para música — el bot no usa Lavalink;
la música es yt-dlp + FFmpeg, y la dependencia de configuración real es el
archivo de cookies de YouTube (`YTDLP_COOKIES`). El hallazgo 5 cubre eso.

---

## 1. No hay manejador global de errores para slash commands → "La aplicación no respondió"

- **Dónde:** `src/bot.py` (no se define `bot.tree.on_error` en ningún lado);
  `src/cogs/general.py:48` (`on_command_error`) solo cubre comandos de
  prefijo (`!ping`), no los 25 slash commands.
- **Qué pasa hoy:** cualquier excepción no capturada dentro de un slash
  command (FFmpeg ausente, permiso faltante, un bug cualquiera) se loguea con
  el handler default de discord.py y el usuario ve el error nativo de Discord
  "La aplicación no respondió" o un comando que se queda "pensando" para
  siempre.
- **Por qué es un problema:** es el peor mensaje posible: no dice qué pasó,
  no dice si reintentarlo sirve, y transmite "este bot está roto". Aplica a
  *todos* los comandos a la vez, así que es el hallazgo con más superficie.
- **Sugerencia:** registrar un `tree.on_error` global que (a) loguee el
  traceback como hoy, y (b) responda/haga followup con un mensaje corto y
  humano tipo "algo salió mal de mi lado 😖 probá de nuevo en un rato",
  respetando si el interaction ya fue respondido o deferido.

## 2. Mencionar al bot puede no producir NADA, en silencio, por tres causas distintas

- **Dónde:** `src/cogs/chat.py:109` (chat desactivado → `return`),
  `chat.py:111` (chat restringido a otro canal → `return`),
  `chat.py:61-62` (canal en la lista de ignorados → `return` antes de llegar
  siquiera al manejo de menciones).
- **Qué pasa hoy:** un usuario menciona/responde al bot y no recibe ninguna
  respuesta ni indicación, si el admin desactivó el chat, lo restringió a un
  canal, o el canal está ignorado.
- **Por qué es un problema:** mencionar al bot es la forma #1 de probarlo.
  "No contesta" es indistinguible de "está caído". El usuario no tiene forma
  de saber que la respuesta está en otro canal o desactivada.
- **Sugerencia:** ante mención directa en esos tres casos, responder una
  única vez (con cooldown por guild, mismo patrón que `empty_corpus_reply`)
  algo tipo "aquí no puedo responder — prueba en #tal-canal" o "un admin
  desactivó mis respuestas en este servidor". Alternativa mínima: reaccionar
  con un emoji (🤐) para que al menos se sepa que el bot está vivo.

## 3. El flujo de memes está lleno de callejones sin salida y mensajes técnicos

- **Dónde:** `src/cogs/memes.py:426` ("se rompió algo, revisa los logs."),
  `memes.py:411` ("El corpus está vacío."), `memes.py:416` ("No se pudo
  generar el caption."), `memes.py:404` ("Sin imágenes válidas en el pool.
  Añade fotos con 🎯."), `memes.py:378` y `src/cogs/gifs.py:144` ("esta
  función no está disponible en este servidor"), `memes.py:290` (reaccionar
  🎯 en servidor no premium = no-op absolutamente silencioso).
- **Qué pasa hoy:** `/momo` y `/meme` aparecen en la lista de comandos de
  *todos* los servidores (sync global), así que en los 8 servidores no
  premium cualquiera los va a probar y recibe "no está disponible" sin saber
  por qué ni qué hacer. En los premium: "revisa los logs" (¿qué logs?),
  "corpus"/"caption"/"pool" (jerga), y el 🎯 —la única forma de cargar
  imágenes— falla sin feedback si el servidor no es premium o la imagen no
  califica.
- **Por qué es un problema:** es el flujo con más jerga interna y más
  estados donde "no pasa nada". "Revisa los logs" dirigido a un usuario de
  Discord es el ejemplo canónico de mensaje para el dev filtrado al usuario.
- **Sugerencia:** (a) reescribir los cinco textos en lenguaje simple, p. ej.
  "algo salió mal de mi lado, probá de nuevo", "todavía no leí suficientes
  mensajes del servidor — un admin puede correr /refeed_all", "no tengo fotos
  guardadas: reaccioná con 🎯 a un mensaje que tenga una foto y la agrego";
  (b) al gate premium, explicar en una línea qué es premium y cómo se
  consigue; (c) al reaccionar 🎯 sin premium o con imagen inválida, contestar
  con una reacción (❌) o mensaje efímero en vez de silencio.

## 4. `/refeed_all` (el primer paso recomendado en la bienvenida) puede morir en silencio a los 15 minutos

- **Dónde:** `src/cogs/chat.py:193` y `:243` (`defer(thinking=True)` + bucles
  de historial de hasta 80.000/20.000 mensajes por canal, sin feedback
  intermedio).
- **Qué pasa hoy:** en un servidor con historial grande, el recorrido tarda
  más de 15 minutos, el token del interaction expira y el
  `followup.send()` final falla: el usuario ve "Purgito está pensando…" que
  termina en error, sin saber si funcionó ni cuánto falta. Encima el embed de
  bienvenida y `/setup` recomiendan correr `/refeed_all` como primer paso.
- **Por qué es un problema:** es la primera acción del admin nuevo, y en
  servidores medianos/grandes la probabilidad de superar los 15 min es alta.
  El admin queda sin confirmación de si el bot "aprendió" o no.
- **Sugerencia:** mandar un primer followup inmediato ("estoy leyendo el
  historial, esto puede tardar — te avisaré aquí cuando termine"), reportar el
  resultado final con `channel.send()` (que no depende del token del
  interaction), y opcionalmente ir editando un mensaje de progreso cada N
  canales.
- **Estado: ✅ resuelto (2026-07-06).** `/refeed_all` ahora responde de
  inmediato, corre en background (`asyncio.create_task`), edita un mensaje de
  progreso línea-por-canal y manda el resumen final con `channel.send()`.
  Además el refeed se dispara solo al unirse a un servidor nuevo
  (`on_guild_join`), y hay estado persistente por canal
  (`channel_refeed_status`) que permite lecturas incrementales y reanudar
  backfills a medias.

## 5. Música: jerga de infraestructura en mensajes al usuario

- **Dónde:** `src/music_player.py:340` y `:364` ("YouTube no está disponible
  desde este servidor. Usa SoundCloud o configura cookies para yt-dlp."),
  `music_player.py:204-205` ("YouTube bloqueó la request. Las cookies pueden
  haber expirado — contacta al admin del bot.").
- **Qué pasa hoy:** cuando faltan/expiran las cookies de YouTube (pasa
  periódicamente), cualquier usuario que pega una URL de YouTube en `/play`
  recibe instrucciones de configurar "cookies para yt-dlp".
- **Por qué es un problema:** "cookies", "yt-dlp" y "request" son palabras
  del deploy, no del usuario. Además le pide configurar algo que solo el
  dueño del droplet puede tocar.
- **Sugerencia:** separar audiencias: al usuario, "YouTube no está andando
  en este momento 😞 probá con el nombre de la canción (busco en SoundCloud)";
  y en paralelo loguear/avisar al owner (log level WARNING ya existe) que las
  cookies expiraron. Nunca mencionar yt-dlp/cookies en el chat.
- **Estado: ✅ resuelto por eliminación (2026-08-04).** Se sacó la
  reproducción de música por completo (cog, `music_player.py`,
  dependencias yt-dlp/FFmpeg/PyNaCl) en vez de arreglar el mensaje: el
  hallazgo ya no aplica porque la feature no existe.

## 6. Jerga "Markov / corpus / pool" en todos los textos de primer contacto

- **Dónde (candidatas a simplificar):**
  - `src/locales/es.json:99` — `welcome.intro`: "Soy un bot de **Markov**…"
    (y su par en `en.json`).
  - `es.json:100` — `welcome.getting_started`: "importar el historial de
    mensajes **al corpus**".
  - `es.json:101` — `welcome.premium_target`: "agregarlas al **pool** de
    `/momo`".
  - `es.json:103` — `welcome.commands`: "genera un mensaje **con Markov**".
  - `src/help_view.py:13-16` — `INTRO_DESCRIPTION`: "**cadenas de Markov**
    entrenadas…"; etiqueta de categoría "Markov / Chat".
  - `src/cogs/chat.py:168` — `/imitar`: "solo tiene N mensaje(s) **en el
    corpus**".
  - `chat.py:183/233/291` — descripciones visibles de `/refeed`,
    `/refeed_all` y `/corpus_info`: "**corpus del modelo Markov**".
  - `chat.py:302-304` — `/corpus_info`: "El **corpus** de este canal…".
  - `es.json:51-55` — botón/modal "**Vaciar corpus** del servidor".
  - `es.json:39-48` — "**Pool** de emojis / El **pool** está vacío" (ídem
    frases).
- **Qué pasa hoy:** el embed de bienvenida (lo primero que ve un servidor
  nuevo), `/help`, `/setup` y varios comandos hablan en vocabulario de
  implementación.
- **Por qué es un problema:** "Markov", "corpus" y "pool" no significan nada
  para el usuario objetivo; en el mejor caso los ignora, en el peor asume que
  el bot es "para programadores".
- **Sugerencia:** pasada de reescritura con un glosario fijo: corpus →
  "los mensajes que aprendí / la memoria del bot"; Markov → "imitando cómo
  escriben ustedes" (o directamente omitirlo); pool → "la lista/colección".
  Los *nombres* de comandos (`/corpus_info`, `/refeed`) pueden quedar, pero
  descripción y respuestas deberían estar en lenguaje simple.

## 7. YouTube: configurar exige el "ID que empieza con UC…", no acepta @handles, y los avisos pueden fallar en silencio

- **Dónde:** `src/locales/es.json:76` (modal de `/settings`: "ID del canal de
  YouTube (empieza con UC...)"), `src/static/panel.js:336-339`
  (`extractYoutubeId` solo entiende URLs `…/channel/UCxxx`),
  `src/cogs/youtube.py:65-75` (si el bot no puede escribir en el canal
  destino, el aviso falla con solo un `log.exception` y reintenta cada 15 min
  para siempre).
- **Qué pasa hoy:** la URL que cualquier persona copia de YouTube hoy es
  `youtube.com/@nombre`; ni el modal ni el panel la resuelven, así que el
  flujo termina en "❌ No se pudo obtener información del canal. Verifica el
  ID". Y una suscripción creada apuntando a un canal donde el bot no puede
  escribir queda "activa" en el panel pero jamás anuncia nada.
- **Por qué es un problema:** encontrar el ID `UC…` de un canal requiere
  saber dónde mirarlo (nadie no técnico lo sabe). Y el fallo de permisos es
  un estado roto invisible: el admin cree que configuró bien.
- **Sugerencia:** (a) resolver @handles: la página
  `youtube.com/@handle` expone el `channelId` (o usar la búsqueda del RSS);
  como mínimo, actualizar `extractYoutubeId` y el texto del modal para
  aceptar la URL completa; (b) al crear la suscripción, verificar
  `permissions_for(me).send_messages` en el canal destino y avisar en el
  momento; (c) si el envío del aviso falla N veces seguidas, notificar al
  admin o marcar la suscripción en el panel.

## 8. Memes automáticos configurados que nunca postean, sin aviso

- **Dónde:** `src/cogs/memes.py:343` y `:348` (`auto_meme_task`: pool de
  imágenes vacío o historial corto → `log.info` y `continue`), más el caso
  de canal borrado/sin permisos (`:334-336`).
- **Qué pasa hoy:** un admin activa "memes cada 6 h" desde `/settings` o el
  panel; si no cargó imágenes con 🎯 o el bot aún no leyó suficientes
  mensajes, la tarea saltea el canal en silencio cada 10 minutos. El panel
  sigue mostrando el schedule como activo.
- **Por qué es un problema:** configuración aparentemente exitosa + cero
  resultado = "el bot no funciona". Nada le dice al admin cuál de los dos
  requisitos falta.
- **Sugerencia:** validar los prerequisitos al momento de activar (¿hay
  imágenes en la colección? ¿hay historial suficiente?) y avisar ahí mismo;
  y/o publicar una única vez en el canal configurado "quiero mandar memes aquí
  pero todavía no tengo fotos — reaccioná con 🎯 a una imagen para dármelas".

## 9. El selector de idioma promete más de lo que cumple: casi todo el bot está hardcodeado en español

- **Dónde:** `src/cogs/chat.py`, `src/cogs/musica.py`, `src/cogs/memes.py`,
  `src/cogs/gifs.py`, `src/music_player.py`, `src/help_view.py` — todos los
  textos de respuesta están en español fijo; solo `settings.py` (panel,
  welcome, setup) y el nuevo mensaje de historial vacío pasan por i18n.
- **Qué pasa hoy:** un servidor que elige "English" en `/settings → Idioma`
  ve el panel en inglés, pero `/help`, toda la música, los memes y los
  errores siguen en español.
- **Por qué es un problema:** Discovery trae servidores de cualquier idioma;
  la opción de idioma genera la expectativa de un bot bilingüe y la rompe en
  el primer comando.
- **Sugerencia:** migración incremental empezando por los textos de mayor
  contacto (`/help`, errores de música, mensajes de memes). Mientras tanto,
  bajar la expectativa en la descripción de la categoría Idioma ("se aplica a
  los paneles de configuración").

## 10. Panel web: errores crudos y callejones sin salida

- **Dónde:** `src/static/panel.js:19` (errores sin `error` del backend se
  muestran como "Error 500" pelado), `panel.js:409-413` (card premium:
  "Contactá al owner del bot para activarlo" — sin ningún medio de contacto),
  `src/webapi.py:400-401` (página `no_guilds`: "No administrás ningún
  servidor de Discord." para cualquier miembro raso que entre al panel).
- **Qué pasa hoy:** un usuario no admin que encuentra el link del panel (está
  en `/help` y en el footer de `/settings`) hace todo el login de Discord y
  termina en una página negra que le dice que no administra servidores, sin
  explicar que el panel es solo para administradores. Los errores de API se
  muestran como códigos HTTP.
- **Por qué es un problema:** el flujo OAuth es largo (autorizar scopes,
  redirect); terminarlo en un mensaje seco se siente como error del sitio. Y
  "Error 500" no le dice a nadie qué hacer.
- **Sugerencia:** en `no_guilds`, explicar "este panel es para administrar
  la configuración del bot; necesitas el permiso *Gestionar servidor* en un
  servidor donde esté Purgito"; en `apiFetch`, mapear códigos a mensajes
  humanos ("no se pudo guardar, probá de nuevo"); en la card premium, poner
  el link/medio de contacto real (servidor de soporte o Discord del owner).

## 11. Galería pública: botones de agregar/borrar visibles sin sesión → "Error de red"

- **Dónde:** `src/gif_gallery.py` (form `add-form` y botón ✕ de borrar,
  visibles para cualquier visitante; el POST/DELETE va a `/api/gifs`, que con
  dashboard activo responde con un redirect 302 a `/auth/login` que el
  `fetch` no puede seguir por CORS).
- **Qué pasa hoy:** un visitante anónimo pega una URL y aprieta agregar: el
  status muestra "✕ Error de red: Failed to fetch". Nada le dice que hace
  falta iniciar sesión.
- **Por qué es un problema:** la UI ofrece una acción que no puede
  funcionar y el error resultante apunta a "problema de conexión", que es
  falso.
- **Sugerencia:** que el backend responda 401 JSON (en vez de redirect) para
  requests de API, y que la galería, ante 401, muestre "necesitas iniciar
  sesión con Discord para agregar GIFs" con un botón a `/auth/login` — u
  ocultar el form/botones si no hay sesión.

## 12. Detalles del pool de imágenes 🎯: límites silenciosos y URLs que expiran

- **Dónde:** `src/cogs/memes.py:302-315` (imagen >10 MB o extensión no
  soportada → se ignora sin feedback; si R2 no está configurado o falla, se
  guarda `attachment.url` de Discord, que expira a las ~24 h).
- **Qué pasa hoy:** el usuario reacciona 🎯, no aparece el ✅ y no sabe por
  qué (¿muy pesada? ¿formato?). Peor: con R2 caído la imagen "se guarda" pero
  el link muere en un día, y `/momo` después la descarta con la eviction lazy
  — la colección se vacía sola misteriosamente.
- **Por qué es un problema:** feedback binario (✅ o nada) para un flujo con
  cuatro causas de fallo distintas; y un estado que se degrada con el tiempo
  sin que nadie lo vea.
- **Sugerencia:** ante fallo, reaccionar con ❌ (y opcionalmente responder
  efímero/borrar-después con la causa: "la imagen supera 10 MB"); si R2 no
  está disponible, avisar en el momento en vez de guardar un link que va a
  expirar.
