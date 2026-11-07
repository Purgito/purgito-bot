# Base de licitud del aprendizaje de mensajes (análisis interno)

**Estado:** análisis para decidir, NO publicado y **no es asesoría legal**. Fecha: 2026-11-07.
**Norma:** Ley 21.719 (en vigencia el 2026-12-01; hasta entonces rige la Ley 19.628). Artículos citados del texto
oficial en leychile.cl (idNorma=1209272). Falta la decisión del titular y su revisión por un abogado.

## 1. Qué se trata y de quién

- **Datos:** el contenido de mensajes de canales habilitados (texto libre), con ID del autor y nombre visible
  (`corpus_messages`, `user_corpus`), hasta 30 días (desde 2026-11-07); GIFs con su remitente, hasta 180 días. Nunca de canales NSFW.
- **Titulares:** las personas que escriben en el servidor. **No tienen ninguna relación con Purgito**: quien
  invita al bot es un administrador, no ellas.
- **Dos tratamientos distintos:**
  1. *Corpus colectivo del servidor* (cadenas de Markov para el chat).
  2. *Estilo por persona* (`user_corpus`, `/imitar`): reproduce cómo escribe alguien concreto. Encaja en la
     definición de **elaboración de perfiles** del art. 2 (tratamiento automatizado para evaluar o analizar
     «preferencias personales, intereses, … comportamiento»).
- **Datos sensibles incidentales:** el texto libre puede contener salud, religión, orientación sexual, etc.
  (art. 2). No se pueden filtrar de forma fiable.
- **Menores:** Discord exige 13 años. El art. 16 quáter exige el consentimiento de padres o representantes para
  tratar datos de «niños y niñas» (menores de 14 según la Ley 21.430; **verificar**) y para los datos sensibles de
  adolescentes menores de 16. Purgito no conoce la edad de nadie.

## 2. Lo que NO es defendible (por eso no se presupone)

| Argumento | Por qué no |
|---|---|
| «El administrador invitó al bot» | El consentimiento lo otorga **el titular** (art. 12); un mandatario necesita facultad expresa. El administrador no la tiene sobre sus miembros. |
| «Quien sigue en el servidor consiente» / silencio | El consentimiento debe ser previo, inequívoco y por un acto afirmativo (art. 12). |
| «Son mensajes públicos» | «Fuente de acceso público» (art. 2 i) es lo que **cualquier persona** puede consultar lícitamente (Diario Oficial, medios, registros públicos). Un servidor de Discord no lo es, y aunque lo fuera sigue sujeto a la ley. |
| «Contrato» (art. 13 c) | El contrato de Purgito es con quien paga Premium, no con los miembros. |
| «Somos solo encargados del administrador» (art. 2 x) | Purgito decide los fines y los medios (corpus, retención, imitación): es responsable, no encargado. |

## 3. Opciones jurídicamente defendibles

### A. Consentimiento individual (art. 12) — la más sólida, la más costosa
Libre, informado, específico y por acto afirmativo; revocable sin expresión de causa y sin costo; **la carga de la
prueba es de Purgito**. Ojo con la presunción del art. 12: se presume no libre si se recaba en un servicio en que
la recolección no es necesaria.
- *Implicaciones técnicas:* tabla de consentimientos (persona, fecha, versión del texto, revocación); el
  aprendizaje es opt-in (hoy es opt-out por exclusión); aviso a cada persona (botón/mensaje del bot) y opción
  en el Centro de Privacidad; `save_corpus_and_user_message` consulta el registro; lo ya aprendido sin
  consentimiento se purga o se reubica bajo otra base.
- *Costo funcional:* el bot arranca «en frío» y el corpus de un servidor solo crece con quienes opten. Los
  sensibles y los menores quedan cubiertos solo para quien consienta (y los menores de 14 exigen padres).

### B. Interés legítimo (art. 13 d) — posible solo si la ponderación lo sostiene
El interés legítimo **no justifica automáticamente** guardar los mensajes de todas las personas de un servidor: depende de una ponderación concreta que hoy no existe por escrito.
Requiere un **análisis de ponderación documentado** (finalidad, necesidad, expectativas razonables, impacto)
y que «no se afecten los derechos y libertades del titular»; el titular puede exigir saber qué interés se invoca
(art. 13 d y 14 ter d). Hoy ya existen salvaguardas: exclusión global, sin NSFW, 30 días, borrado por solicitud y confirmación del administrador al activar un canal.
- *Límites que no se pueden resolver con técnica:*
  - No habilita datos **sensibles** (art. 16 exige consentimiento expreso salvo excepciones estrechas): el
    riesgo del texto libre queda abierto.
  - No sirve para **menores de 14** (art. 16 quáter).
  - El perfil individual (`/imitar`) difícilmente supera la ponderación para quien no lo espera.
- *Implicaciones técnicas:* documento de ponderación versionado; aviso de transparencia donde la gente lo vea
  (mensaje del bot al unirse a un servidor y en el canal habilitado, además de la Política); mantener la
  oposición fácil y efectiva; la retención ya se redujo a 30 días.

### C. Híbrida (alternativa de diseño para evaluación jurídica; no está decidida)
Corpus colectivo bajo **interés legítimo con salvaguardas** + estilo por persona (`user_corpus`, `/imitar`) bajo
**consentimiento opt-in** (A). Implica: aviso al unirse, ponderación por escrito, `user_corpus` solo de quien
consintió, `/imitar` solo sobre personas que consintieron. No resuelve sensibles ni menores en el corpus
colectivo: eso requiere decisión sobre el riesgo residual o pasar el corpus colectivo también a opt-in.

### D. Anonimizar antes de aprender — no recomendada
Anonimización es **irreversible** (art. 2 k). Un modelo de n-gramas conserva fragmentos de texto, y quitar el
autor haría imposible atender una eliminación (hoy se borra por autor). Chocaría con el Centro de Privacidad.

## 4. Riesgo adicional fuera de la ley chilena
`docs/DISCORD_INTENTS.md`: la Developer Policy de Discord puede alcanzar el entrenamiento con contenido de la
API (cadenas de Markov). Independiente de la base de licitud; sigue abierto hasta la decisión de Discord.

## 5. Qué hace falta para publicar el art. 14 ter d)
Elegir A, B o C y redactar el párrafo de la Política con **esa** base (no se publica ninguna hasta decidir).
Modelos de redacción, para revisar con el abogado (no vigentes):
- *B/C:* «Tratamos el contenido de los mensajes de los canales habilitados por el administrador para que Purgito
  pueda responder en el estilo de la comunidad. La base es nuestro interés legítimo en ofrecer esa función; puedes
  oponerte en cualquier momento desde el Centro de Privacidad y dejaremos de aprender de ti. [Ponderación disponible
  si la solicitas.]»
- *A:* «Purgito solo aprende de tus mensajes si lo autorizas con [botón/comando]; puedes retirarlo cuando quieras
  desde el Centro de Privacidad.»
