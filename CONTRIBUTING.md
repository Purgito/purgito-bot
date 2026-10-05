# Contribuir a purgito-bot

¡Gracias por querer aportar! Aquí está todo lo que necesitas saber para trabajar localmente.

## Setup local

### Requisitos

- Python 3.11+ (producción y CI usan 3.14)
- PostgreSQL (producción usa 18) con dos bases: una para desarrollo y `purgito_test` para los tests
- Una cuenta de Discord con un bot creado en el [Portal de Desarrolladores](https://discord.com/developers/applications)
- (Opcional) Cuenta de Cloudflare con un bucket R2 para los GIFs

### Pasos

1. **Fork y clona el repo**
```bash
   git clone https://github.com/<tu-usuario>/purgito-bot.git
   cd purgito-bot
```

2. **Crea un entorno virtual e instala dependencias**
```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
```

3. **Configura las variables de entorno**
   Copia el archivo de ejemplo y completa tus valores:
```bash
   cp .env.example .env
```
   Edita `.env` con tus credenciales. Como mínimo `DISCORD_TOKEN` y `DATABASE_URL`;
   la referencia completa de variables está en [`DEPLOY.md`](DEPLOY.md) § 4 y la guía de
   la base en [`docs/POSTGRES.md`](docs/POSTGRES.md).

4. **Ejecuta el proyecto localmente**
```bash
   python src/bot.py
```

## Tests

Necesitan una base PostgreSQL **distinta** de la de desarrollo: pon su URL en
`TEST_DATABASE_URL` (en `.env` o en el entorno, p. ej. `.../purgito_test`). Los
tests la vacían, así que nunca la apuntes a datos reales.

```bash
.venv/bin/python -m pytest tests -q
```

Ocho tests levantan la app web real. Si el bot ya usa el puerto 8080 en la misma
máquina, no lo pares: `WEB_PORT=18080 .venv/bin/python -m pytest tests -q`. Antes de
abrir un PR corre también `ruff check .`, `ruff format --check .` y, si tocaste
`docs/*.md`, `landing/` (CSS, JS o páginas), `.venv/bin/python landing/build_docs.py`
(el HTML generado se commitea; CI corre el `--check`).

## Convenciones

- **Ramas:** `feat/nombre-feature`, `fix/descripcion-bug`, `chore/tarea`
- **Commits:** mensajes en minúscula con prefijo: `feat:`, `fix:`, `chore:`, `docs:`, `refactor:`
- **Código:** seguir el estilo existente; no romper comandos actuales del bot
- **PRs:** completar el template, describir qué cambiaste y cómo probarlo

## Reportar bugs

Usa los [issue templates](.github/ISSUE_TEMPLATE/) del repo.

## ¿Preguntas?

Abre una discusión o un issue con el tag `question`.
