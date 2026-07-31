"""HTML de las páginas del rediseño: perfil (/es/perfil*) y dashboard por
servidor (/es/dashboard/{guild_id}*). El navbar/footer los arma shell.js; los
datos de sesión y links viajan como data-attributes del <script> de entrada
(mismo patrón que data-guild-id en pages/panel.py)."""

_SHELL_DATA = (
    'data-username="{{USERNAME}}" data-avatar="{{AVATAR_URL}}" '
    'data-email="{{EMAIL}}" data-user-id="{{USER_ID}}" '
    'data-support="{{SUPPORT_URL}}" data-docs="{{DOCS_URL}}" '
    'data-repo="{{REPO_URL}}" data-landing="{{LANDING_URL}}" '
    'data-invite="{{INVITE_URL}}"'
)

PERFIL_HTML = f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Purgito · Perfil</title>
<link rel="stylesheet" href="/static/panel.css">
</head>
<body class="shell-page">
<header id="navbar"></header>
<main class="shell-main" id="perfilMain"></main>
<footer id="footer"></footer>
<div id="toast"></div>
{{{{IMPORT_MAP}}}}
<script type="module" src="/static/js/main-perfil.js?v={{{{STATIC_V}}}}" {_SHELL_DATA}></script>
</body>
</html>
"""

DASH_HTML = f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Purgito · Dashboard</title>
<link rel="stylesheet" href="/static/panel.css">
</head>
<body class="shell-page">
<header id="navbar"></header>
<main class="shell-main">
  <div id="dashHead"></div>
  <nav id="dashTabs" class="dash-tabs"></nav>
  <div id="catContent"></div>
</main>
<footer id="footer"></footer>
<div id="toast"></div>
{{{{IMPORT_MAP}}}}
<script type="module" src="/static/js/main-dash.js?v={{{{STATIC_V}}}}" data-guild-id="{{{{GUILD_ID}}}}" {_SHELL_DATA}></script>
</body>
</html>
"""
