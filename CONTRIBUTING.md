# Contribuir a bot-discord-purg

¡Gracias por querer aportar! Aquí está todo lo que necesitas saber para trabajar localmente.

## Setup local

### Requisitos

- Python 3.11+
- Una cuenta de Discord con un bot creado en el [Portal de Desarrolladores](https://discord.com/developers/applications)
- (Opcional) Cuenta de Cloudflare con un bucket R2 para los GIFs

### Pasos

1. **Fork y clona el repo**
```bash
   git clone https://github.com/<tu-usuario>/bot-discord-purg.git
   cd bot-discord-purg
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
   Edita `.env` con tus credenciales (ver sección "Variables de entorno" en el README).

4. **Ejecuta el proyecto localmente**
```bash
   python src/bot.py
```

## Convenciones

- **Ramas:** `feat/nombre-feature`, `fix/descripcion-bug`, `chore/tarea`
- **Commits:** mensajes en minúscula con prefijo: `feat:`, `fix:`, `chore:`, `docs:`, `refactor:`
- **Código:** seguir el estilo existente; no romper comandos actuales del bot
- **PRs:** completar el template, describir qué cambiaste y cómo probarlo

## Reportar bugs

Usa los [issue templates](.github/ISSUE_TEMPLATE/) del repo.

## ¿Preguntas?

Abrí una discusión o un issue con el tag `question`.
