"""HTML del panel de configuración por servidor (/server/{guild_id})."""

PANEL_HTML = """<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Purgito · Panel</title>
<link rel="stylesheet" href="/static/panel.css">
</head>
<body class="panel-page">
<aside class="sidebar">
  <div class="server-head" id="serverHead"></div>
  <nav id="catNav"></nav>
  <div class="sidebar-footer">
    <a href="/es/perfil"><span class="nav-icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="19" y1="12" x2="5" y2="12"/><polyline points="12 19 5 12 12 5"/></svg></span><span class="nav-label">Mis servidores</span></a>
    <a href="/auth/logout"><span class="nav-icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/></svg></span><span class="nav-label">Cerrar sesión</span></a>
  </div>
</aside>
<main class="content">
  <h1 id="catTitle"></h1>
  <div id="catContent"></div>
</main>
<div id="toast"></div>
{{IMPORT_MAP}}
<script type="module" src="/static/js/main-panel.js?v={{STATIC_V}}" data-guild-id="{{GUILD_ID}}"></script>
</body>
</html>
"""
