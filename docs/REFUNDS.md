# Políticas de reembolsos

**Última actualización:** 7 de noviembre de 2026

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

Como regla general, Purgito no devuelve el dinero de períodos ya iniciados o
pagados, sean mensuales o anuales. Para eso existe la prueba gratuita de 7
días del plan mensual: sirve para decidir si Premium vale la pena antes de
pagar. Por eso, una vez iniciado el período pagado, no se hacen devoluciones
por el tiempo restante ni por una decisión posterior de dejar de usar el servicio.

Esta regla no limita los derechos que la ley te reconoce como consumidor,
y no excluimos el derecho de retracto cuando la ley te lo reconozca. Si
crees que en tu caso corresponde un reembolso o quieres ejercer ese derecho (por ejemplo,
un cobro duplicado o por error, o un servicio que no funciona como se
ofreció), escribe a contacto@purgito.app indicando el servidor y la fecha
del cobro, y lo revisamos. Como Polar.sh procesa los pagos, el reembolso, si
procede, se tramita a través de Polar.

Cancelar la suscripción es distinto de pedir un reembolso: cancelar solo
detiene la renovación automática del siguiente período. El acceso premium
que ya pagaste sigue activo con normalidad hasta que ese período termine
— no se interrumpe antes, y tampoco se devuelve el dinero de lo que quede
de ese período si cancelas antes de que termine, salvo que la ley disponga otra cosa.

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
mensajes, GIFs, plantillas de embeds, anuncios
programados, frases especiales, etc.) **no se borra**. Simplemente deja
de poder seguir creciendo más allá de los límites del plan gratuito.

Cómo se comporta el excedente depende de la categoría. En mensajes de
corpus, GIFs, el sistema descarta lo más viejo a
medida que se guarda contenido nuevo, así que el excedente converge
solo con el uso normal del bot. En plantillas de embeds, anuncios
programados y frases especiales no hay descarte automático: simplemente
no se puede crear ninguno nuevo hasta bajar del límite del plan gratuito
borrando algo a mano.

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
  escribir a contacto@purgito.app para resolverlo caso por caso.
