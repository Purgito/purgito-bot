# Políticas de reembolsos

**Última actualización:** 2 de agosto de 2026

Esta página resume cómo funcionan la prueba gratuita, la cancelación y
los reembolsos del plan Premium de Purgito.

## Prueba gratuita (trial)

Existe una prueba gratuita de 7 días en el plan mensual. La prueba aplica
una única vez por cliente (mismo comprador o método de pago), incluso si
se activa en otro servidor.

## Cancelación

La suscripción se cancela desde el portal de cliente de Polar, cuyo
acceso se envía por correo (de Polar, no de Purgito) al momento de
suscribirse. No se cancela desde el dashboard de Purgito.

## Reembolsos

Purgito no ofrece reembolsos por períodos ya iniciados o pagados, ya sean
mensuales o anuales.

Antes de pagar, cada servidor tiene acceso a una prueba gratuita de 7
días en el plan mensual, pensada específicamente para decidir si Premium
vale la pena antes de comprometer un pago. Por eso, una vez iniciado el
período pagado, no se realizan devoluciones parciales ni totales — ni por
el tiempo restante, ni por el uso que se le haya dado al servicio, ni por
una decisión posterior de dejar de usarlo.

Cancelar la suscripción es distinto de pedir un reembolso: cancelar solo
detiene la renovación automática del siguiente período. El acceso premium
que ya pagaste sigue activo con normalidad hasta que ese período termine
— no se interrumpe antes, y tampoco se devuelve el dinero de lo que quede
de ese período si cancelas antes de que termine.

Como los pagos los procesa Polar.sh como Merchant of Record, cualquier
disputa de cobro (contracargo/chargeback) se gestiona directamente entre
quien pagó y Polar, bajo los propios términos de Polar — esto puede
derivar en la suspensión del acceso premium mientras la disputa esté
abierta (ver "Revocación").

## Revocación

El desarrollador de Purgito o Polar.sh pueden revocar el acceso premium
en casos de fraude, contracargo (chargeback) o fallo de pago no
resuelto.

## Qué pasa con tu contenido si el servidor pierde Premium

Cuando un servidor deja de tener Premium (por cancelación, revocación, o
fin del período pagado), el contenido que ya tenía guardado (corpus de
mensajes, GIFs, plantillas de embeds, etc.) **no se borra**. Simplemente
deja de poder seguir creciendo más allá de los límites del plan
gratuito: si ya tenías más contenido guardado del que el plan gratuito
permite, ese excedente se conserva tal cual hasta que, con el uso normal
del bot, converge naturalmente al límite gratuito (por ejemplo, el
sistema descarta lo más viejo a medida que se guarda contenido nuevo, en
las categorías que ya funcionan así).

## Titularidad del premium

El Premium activado en un servidor pertenece a ese servidor (identificado
por su guild_id de Discord), no a la persona ni a la cuenta que hizo el
pago.

En la práctica:

- Si quien pagó abandona el servidor, es expulsado, o transfiere la
  propiedad del servidor a otra persona, el Premium se mantiene activo
  sin cambios — el servidor no pierde los beneficios.
- La gestión de la suscripción (cancelar, cambiar de plan, ver recibos)
  solo puede hacerla quien tiene acceso al portal de cliente de Polar
  asociado a esa compra — normalmente, quien pagó originalmente. Si esa
  persona pierde acceso a su email o a su cuenta de Polar, nadie más en
  el servidor puede gestionar la suscripción directamente; hay que
  contactar al desarrollador para resolverlo caso por caso.
