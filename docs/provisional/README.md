# Textos provisionales (no son la fuente de verdad)

`PRIVACY.md` y `PRIVACY.en.md` de esta carpeta son la Política de Privacidad **tal como es cierta en producción hoy**:
iguales a `docs/PRIVACY*.md` salvo las afirmaciones que dependen de mecanismos que solo están preparados en el
repositorio (purga de logs a 30 días, nginx sin parámetros, domingos hasta 13 días, entrega de `contacto@`).
`deploy/landing_hotfix.sh` los usa para construir, **fuera del árbol que sirve nginx**, las dos páginas corregidas.
Al desplegar el cierre técnico se publican `docs/PRIVACY*.md` (el texto objetivo) y esta carpeta deja de usarse.
