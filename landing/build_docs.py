#!/usr/bin/env python3
"""Genera las páginas legales de la landing desde docs/*.md.

    python landing/build_docs.py           # escribe landing/es/{terminos,privacidad,reembolsos}/
    python landing/build_docs.py --check   # solo verifica, no escribe

El HTML generado se commitea: el deploy sigue siendo `git pull` + copiar
`landing/`, sin build step en el servidor. Correr esto después de editar
cualquier docs/*.md.

El markdown de docs/ usa un subconjunto acotado (encabezados, listas,
negrita, links, código inline) — por eso el convertidor son 40 líneas de
stdlib y no una dependencia nueva.

El navbar y el footer se recortan de index.html en cada corrida: una sola
copia de esos bloques en el repo.

También sella el cache-busting de style.css y script.js (ver `stamp`), por eso
hay que correrlo después de tocar esos archivos, no solo docs/*.md. El
`--check` de CI falla si quedaron desincronizados.
"""

import base64
import functools
import hashlib
import html
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LANDING = ROOT / "landing"
DOCS = ROOT / "docs"

BASE_URL = "https://purgito.app"

# Los dos idiomas que build_docs.py genera de verdad (ru/ja/de solo existen
# como ítems atenuados del selector — ver window.READY_LANGS en index.html).
LANGS = ("es", "en")

# Única fuente de verdad para qué slugs cambian de un idioma a otro. La
# inmensa mayoría de las páginas conservan el mismo slug (guia, premium,
# estado, dashboard, perfil/*) -- acá solo van las excepciones. El selector
# de idioma en script.js mantiene una copia de este mismo mapeo (no puede
# importar este módulo Python) y landing/test_lang.mjs verifica que ambos
# lados coincidan con lo que existe en disco, así que un olvido acá se
# detecta ahí, no en producción.
SLUG_MAP_ES_EN = {
    "terminos": "terms",
    "privacidad": "privacy",
    "reembolsos": "refunds",
    "documentacion": "documentation",
    "documentacion/arquitectura": "documentation/architecture",
    "documentacion/discord": "documentation/discord",
    "documentacion/api": "documentation/api",
    "documentacion/generacion": "documentation/generation",
    "documentacion/almacenamiento": "documentation/storage",
    "documentacion/seguridad": "documentation/security",
    "documentacion/infraestructura": "documentation/infrastructure",
    "documentacion/desarrollo": "documentation/development",
    "documentacion/referencia": "documentation/reference",
}
SLUG_MAP_EN_ES = {v: k for k, v in SLUG_MAP_ES_EN.items()}


def en_slug(es_slug):
    return SLUG_MAP_ES_EN.get(es_slug, es_slug)


def es_slug(en_slug_):
    return SLUG_MAP_EN_ES.get(en_slug_, en_slug_)


def counterpart_slug(slug, lang):
    """Slug de la misma página en el otro idioma."""
    return en_slug(slug) if lang == "es" else es_slug(slug)


def og_image_digest() -> str:
    """Retorna los primeros 8 caracteres del hash SHA-256 de landing/assets/og-purgito.png."""
    og_path = LANDING / "assets" / "og-purgito.png"
    return hashlib.sha256(og_path.read_bytes()).hexdigest()[:8]


def get_default_og_image() -> str:
    """Retorna la URL canónica de og:image versionada con el hash SHA-256 del asset."""
    return f"{BASE_URL}/assets/og-purgito.png?v={og_image_digest()}"


DEFAULT_OG_IMAGE = get_default_og_image()
DEFAULT_OG_IMAGE_WIDTH = "512"
DEFAULT_OG_IMAGE_HEIGHT = "512"
DEFAULT_OG_IMAGE_ALT = "Purgito"
DEFAULT_TWITTER_CARD = "summary"

# Las descripciones del índice no salen del markdown (no existen ahí): se
# escriben acá, una línea por sección, en el mismo orden del documento.
PAGES = [
    {
        "slug": "terminos",
        "src": "TERMS.md",
        "title": "Términos del Servicio",
        "meta": "Condiciones del servicio de Purgito: uso aceptable, licencia, "
        "contenido generado, suscripciones y límites de responsabilidad.",
        "toc": [
            "Qué se puede y qué no se puede hacer con el bot.",
            "Licencia MIT y ausencia de garantías sobre el software.",
            "Qué implica que el texto lo genere una máquina y quién modera.",
            "Premium, precios, prueba gratuita, cancelación y reembolsos.",
            "El servicio se ofrece sin garantía de disponibilidad continua.",
            "Qué daños no cubre el desarrollador.",
            "Cómo y cuándo cambian estos Términos.",
            "Dónde escribir si tienes dudas o quieres reportar un problema.",
        ],
    },
    {
        "slug": "privacidad",
        "src": "PRIVACY.md",
        "title": "Política de Privacidad",
        "meta": "Qué datos recopila Purgito, para qué los usa, con qué servicios "
        "los comparte y cómo eliminarlos.",
        "toc": [
            "Qué datos guarda el bot: IDs, mensajes, multimedia, sesión y pagos.",
            "Para qué se usan esos datos — nunca para publicidad ni venta.",
            "Proveedores externos que intervienen en alguna función.",
            "Cuánto tiempo se conservan los datos y cómo borrarlos.",
            "Qué puedes pedir sobre la información recopilada.",
            "Edad mínima y capacidad para contratar premium.",
            "Medidas para proteger la información almacenada.",
            "Cómo se avisan las actualizaciones de esta Política.",
            "Dónde escribir para preguntar o pedir una eliminación.",
        ],
    },
    {
        "slug": "reembolsos",
        "src": "REFUNDS.md",
        "title": "Política de Reembolso",
        "meta": "Política de reembolsos de las suscripciones premium de Purgito y "
        "condiciones de la prueba gratuita.",
        "toc": [
            "La prueba gratuita de 7 días y sus condiciones.",
            "Cómo cancelar la suscripción desde el portal de Polar.",
            "Por qué no se ofrecen reembolsos por el período ya pagado.",
            "Cuándo se puede revocar el acceso premium.",
            "Qué pasa con tu contenido guardado si el servidor pierde Premium.",
            "A quién queda asociado el premium: al servidor, no a la cuenta.",
        ],
    },
]

# Mismo formato que PAGES, en inglés. slug via en_slug() -- nunca a mano --
# para que no pueda desincronizarse de SLUG_MAP_ES_EN.
PAGES_EN = [
    {
        "slug": en_slug("terminos"),
        "src": "TERMS.en.md",
        "title": "Terms of Service",
        "meta": "Purgito's terms of service: acceptable use, license, generated "
        "content, subscriptions, and limits of liability.",
        "toc": [
            "What you can and can't do with the bot.",
            "MIT license and no warranties on the software.",
            "What it means that the text is machine-generated, and who moderates it.",
            "Premium, pricing, free trial, cancellation, and refunds.",
            "The service is offered without a guarantee of continuous availability.",
            "What damages the developer isn't liable for.",
            "How and when these Terms change.",
            "Where to write with questions or to report a problem.",
        ],
    },
    {
        "slug": en_slug("privacidad"),
        "src": "PRIVACY.en.md",
        "title": "Privacy Policy",
        "meta": "What data Purgito collects, what it's used for, which services "
        "it's shared with, and how to delete it.",
        "toc": [
            "What data the bot stores: IDs, messages, media, session, and payments.",
            "What that data is used for — never for advertising or sale.",
            "External providers involved in certain features.",
            "How long data is kept, and how to delete it.",
            "What you can request about the information collected.",
            "Minimum age and eligibility to purchase Premium.",
            "Measures to protect stored information.",
            "How updates to this Policy are announced.",
            "Where to write with questions or a deletion request.",
        ],
    },
    {
        "slug": en_slug("reembolsos"),
        "src": "REFUNDS.en.md",
        "title": "Refund Policy",
        "meta": "Purgito's refund policy for Premium subscriptions and the free "
        "trial's conditions.",
        "toc": [
            "The 7-day free trial and its conditions.",
            "How to cancel your subscription from the Polar portal.",
            "Why refunds aren't offered for an already-paid period.",
            "When Premium access can be revoked.",
            "What happens to your saved content if the server loses Premium.",
            "Who Premium is tied to: the server, not the account.",
        ],
    },
]

# Mismo formato que PAGES, en ruso/japonés/alemán. A diferencia de PAGES_EN,
# el slug es el mismo literal que en PAGES -- ru/ja/de reutilizan el slug
# español tal cual (ver SLUG_MAP_ES_EN, que solo cubre ES<->EN). src apunta a
# los markdown en docs/*.{ru,ja,de}.md, que agrega el agente de traducción.
PAGES_RU = [
    {
        "slug": "terminos",
        "src": "TERMS.ru.md",
        "title": "Условия обслуживания",
        "meta": "Условия использования Purgito: допустимое использование, "
        "лицензия, генерируемый контент, подписки и ограничение ответственности.",
        "toc": [
            "Что можно и что нельзя делать с ботом.",
            "Лицензия MIT и отсутствие гарантий на программное обеспечение.",
            "Что значит, что текст создаётся машиной, и кто его модерирует.",
            "Premium, цены, бесплатный пробный период, отмена и возврат средств.",
            "Сервис предоставляется без гарантии непрерывной доступности.",
            "Какой ущерб не покрывается разработчиком.",
            "Как и когда меняются эти Условия.",
            "Куда писать, если есть вопросы или нужно сообщить о проблеме.",
        ],
    },
    {
        "slug": "privacidad",
        "src": "PRIVACY.ru.md",
        "title": "Политика конфиденциальности",
        "meta": "Какие данные собирает Purgito, для чего они используются, "
        "с какими сервисами передаются и как их удалить.",
        "toc": [
            "Какие данные хранит бот: ID, сообщения, медиафайлы, сессия и платежи.",
            "Для чего используются эти данные — никогда для рекламы или продажи.",
            "Внешние поставщики услуг, участвующие в некоторых функциях.",
            "Как долго хранятся данные и как их удалить.",
            "Что вы можете запросить в отношении собранной информации.",
            "Минимальный возраст и возможность оформить Premium.",
            "Меры по защите хранимой информации.",
            "Как сообщается об обновлениях этой Политики.",
            "Куда писать с вопросами или запросом на удаление данных.",
        ],
    },
    {
        "slug": "reembolsos",
        "src": "REFUNDS.ru.md",
        "title": "Политика возврата средств",
        "meta": "Политика возврата средств за премиум-подписки Purgito и "
        "условия бесплатного пробного периода.",
        "toc": [
            "7-дневный бесплатный пробный период и его условия.",
            "Как отменить подписку через портал Polar.",
            "Почему не предоставляется возврат средств за уже оплаченный период.",
            "Когда доступ к Premium может быть отозван.",
            "Что происходит с сохранённым контентом, если сервер теряет Premium.",
            "К чему привязан Premium: к серверу, а не к аккаунту.",
        ],
    },
]

PAGES_JA = [
    {
        "slug": "terminos",
        "src": "TERMS.ja.md",
        "title": "利用規約",
        "meta": "Purgitoの利用規約:許容される使用方法、ライセンス、生成される"
        "コンテンツ、サブスクリプション、責任の制限について。",
        "toc": [
            "ボットでできること・できないこと。",
            "MITライセンスとソフトウェアに関する保証の不存在。",
            "テキストが機械によって生成されることの意味と、誰がモデレーションを行うか。",
            "Premium、料金、無料トライアル、キャンセルと返金について。",
            "本サービスは継続的な稼働を保証するものではありません。",
            "開発者が責任を負わない損害について。",
            "本規約がどのように、いつ変更されるか。",
            "質問や問題を報告したい場合の連絡先。",
        ],
    },
    {
        "slug": "privacidad",
        "src": "PRIVACY.ja.md",
        "title": "プライバシーポリシー",
        "meta": "Purgitoが収集するデータの種類、その利用目的、共有先のサービス、"
        "削除方法について。",
        "toc": [
            "ボットが保存するデータ:ID、メッセージ、メディア、セッション、支払い情報。",
            "そのデータの利用目的 — 広告や販売には一切使用しません。",
            "一部の機能に関わる外部サービス提供者。",
            "データの保存期間と削除方法。",
            "収集された情報について要求できること。",
            "Premium契約に必要な最低年齢と資格。",
            "保存された情報を保護するための対策。",
            "本ポリシーの更新はどのように通知されるか。",
            "質問や削除依頼をしたい場合の連絡先。",
        ],
    },
    {
        "slug": "reembolsos",
        "src": "REFUNDS.ja.md",
        "title": "返金ポリシー",
        "meta": "Purgitoのプレミアムサブスクリプションの返金ポリシーと、"
        "無料トライアルの条件について。",
        "toc": [
            "7日間の無料トライアルとその条件。",
            "Polarポータルからサブスクリプションを解約する方法。",
            "すでに支払われた期間について返金が行われない理由。",
            "Premiumアクセスが取り消される場合について。",
            "サーバーがPremiumを失った場合、保存されたコンテンツはどうなるか。",
            "Premiumが紐づく対象:アカウントではなくサーバー。",
        ],
    },
]

PAGES_DE = [
    {
        "slug": "terminos",
        "src": "TERMS.de.md",
        "title": "Nutzungsbedingungen",
        "meta": "Nutzungsbedingungen von Purgito: zulässige Nutzung, Lizenz, "
        "generierte Inhalte, Abonnements und Haftungsbeschränkungen.",
        "toc": [
            "Was mit dem Bot erlaubt ist und was nicht.",
            "MIT-Lizenz und Haftungsausschluss für die Software.",
            "Was es bedeutet, dass der Text maschinell generiert wird, und wer ihn moderiert.",
            "Premium, Preise, kostenlose Testphase, Kündigung und Rückerstattungen.",
            "Der Dienst wird ohne Garantie einer durchgehenden Verfügbarkeit angeboten.",
            "Welche Schäden der Entwickler nicht abdeckt.",
            "Wie und wann sich diese Nutzungsbedingungen ändern.",
            "Wohin man sich bei Fragen oder zur Meldung eines Problems wenden kann.",
        ],
    },
    {
        "slug": "privacidad",
        "src": "PRIVACY.de.md",
        "title": "Datenschutzrichtlinie",
        "meta": "Welche Daten Purgito erfasst, wofür sie verwendet werden, mit "
        "welchen Diensten sie geteilt werden und wie man sie löscht.",
        "toc": [
            "Welche Daten der Bot speichert: IDs, Nachrichten, Medien, Sitzung und Zahlungen.",
            "Wofür diese Daten verwendet werden — niemals für Werbung oder Verkauf.",
            "Externe Anbieter, die bei bestimmten Funktionen beteiligt sind.",
            "Wie lange Daten aufbewahrt werden und wie man sie löscht.",
            "Was du bezüglich der gesammelten Informationen verlangen kannst.",
            "Mindestalter und Berechtigung zum Erwerb von Premium.",
            "Maßnahmen zum Schutz der gespeicherten Informationen.",
            "Wie Aktualisierungen dieser Richtlinie bekannt gegeben werden.",
            "Wohin man sich mit Fragen oder einem Löschantrag wenden kann.",
        ],
    },
    {
        "slug": "reembolsos",
        "src": "REFUNDS.de.md",
        "title": "Rückerstattungsrichtlinie",
        "meta": "Rückerstattungsrichtlinie für Purgito-Premium-Abonnements und "
        "Bedingungen der kostenlosen Testphase.",
        "toc": [
            "Die 7-tägige kostenlose Testphase und ihre Bedingungen.",
            "Wie man das Abonnement über das Polar-Portal kündigt.",
            "Warum keine Rückerstattung für einen bereits bezahlten Zeitraum angeboten wird.",
            "Wann der Premium-Zugang widerrufen werden kann.",
            "Was mit deinen gespeicherten Inhalten passiert, wenn der Server Premium verliert.",
            "Woran Premium gebunden ist: an den Server, nicht an das Konto.",
        ],
    },
]

# Páginas que no salen de un markdown: el cuerpo se escribe a mano en
# landing/pages/ y acá solo se le pega el navbar/footer/head compartido.
#
# "app" marca las páginas del dashboard: además del <head> común les suma
# dash.css y su módulo de entrada. Son las únicas que cargan JavaScript propio
# — el resto del sitio se sirve con script.js y nada más.
HTML_PAGES = [
    {
        "slug": "premium",
        "src": "premium.html",
        "title": "Purgito Premium",
        "meta": "Lleva tu servidor al siguiente nivel con Purgito Premium: memoria ampliada "
        "de 50.000 mensajes, memes automáticos, 4.000 GIFs y soporte prioritario.",
    },
    {
        "slug": "perfil",
        "src": "perfil.html",
        "title": "Perfil",
        "meta": "Tu cuenta de Purgito: información de perfil de Discord, servidores y suscripciones.",
        "app": "perfil.js",
    },
    # Mismo cuerpo que /es/perfil: perfil.js decide la tab por la URL. Existen
    # como páginas propias para que cada una tenga su título y su link real.
    {
        "slug": "perfil/servidores",
        "src": "perfil.html",
        "title": "Servidores",
        "meta": "Tus servidores de Discord con Purgito: entra al dashboard de "
        "cada uno o invítalo a los que falten.",
        "app": "perfil.js",
    },
    {
        "slug": "perfil/conexiones",
        "src": "perfil.html",
        "title": "Conexiones",
        "meta": "Conexiones de tu cuenta de Purgito con Discord y servicios vinculados.",
        "app": "perfil.js",
    },
    {
        "slug": "perfil/facturacion",
        "src": "perfil.html",
        "title": "Facturación",
        "meta": "Estado de tus suscripciones Premium de Purgito y gestión de facturación.",
        "app": "perfil.js",
    },
    {
        "slug": "dashboard",
        "src": "dashboard.html",
        "title": "Dashboard",
        "meta": "Configura Purgito en tu servidor: chat, corpus, reacciones, "
        "frases, GIFs, embeds y premium.",
        "app": "dash.js",
        "no_footer": True,
    },
    {
        "slug": "estado",
        "src": "estado.html",
        "title": "Estado de Purgito",
        "meta": "Estado en vivo de Purgito: tiempo activo, memoria, latencia "
        "con Discord y cantidad de servidores. Pública, sin necesidad de login.",
        "module": "estado.js",
    },
    {
        "slug": "guia",
        "src": "guia.html",
        "title": "Guía de Purgito — Cómo funciona el bot",
        "meta": "Aprende cómo funciona Purgito, desde el sistema de aprendizaje y Chat "
        "hasta GIFs, memes, embeds, YouTube y Premium.",
        "guia": True,
    },
    {
        "slug": "documentacion",
        "src": "documentacion/index.html",
        "title": "Documentación técnica",
        "meta": "Guías, referencia y detalles sobre la arquitectura, APIs, sistemas "
        "internos e infraestructura de Purgito.",
        "doc": True,
    },
    {
        "slug": "documentacion/arquitectura",
        "src": "documentacion/arquitectura.html",
        "title": "Arquitectura — Documentación técnica",
        "meta": "Cómo se conectan el bot de Discord, el motor de generación, "
        "la base de datos y el dashboard de Purgito.",
        "doc": True,
    },
    {
        "slug": "documentacion/discord",
        "src": "documentacion/discord.html",
        "title": "Discord — Documentación técnica",
        "meta": "Cogs, eventos, permisos e interacciones del bot de Purgito.",
        "doc": True,
    },
    {
        "slug": "documentacion/api",
        "src": "documentacion/api.html",
        "title": "API — Documentación técnica",
        "meta": "Autenticación, sesiones, endpoints y webhooks de la API de Purgito.",
        "doc": True,
    },
    {
        "slug": "documentacion/generacion",
        "src": "documentacion/generacion.html",
        "title": "Motor de generación — Documentación técnica",
        "meta": "Cómo genera texto Purgito: cadenas de Markov, corpus, "
        "concurrencia y límites.",
        "doc": True,
    },
    {
        "slug": "documentacion/almacenamiento",
        "src": "documentacion/almacenamiento.html",
        "title": "Almacenamiento — Documentación técnica",
        "meta": "SQLite, Cloudflare R2, cachés en memoria y retención de "
        "datos en Purgito.",
        "doc": True,
    },
    {
        "slug": "documentacion/seguridad",
        "src": "documentacion/seguridad.html",
        "title": "Seguridad — Documentación técnica",
        "meta": "Modelo de seguridad de Purgito: OAuth2, sesiones, permisos "
        "y límites de uso.",
        "doc": True,
    },
    {
        "slug": "documentacion/infraestructura",
        "src": "documentacion/infraestructura.html",
        "title": "Infraestructura — Documentación técnica",
        "meta": "Runtime, nginx, Cloudflare y despliegue de Purgito en producción.",
        "doc": True,
    },
    {
        "slug": "documentacion/desarrollo",
        "src": "documentacion/desarrollo.html",
        "title": "Desarrollo — Documentación técnica",
        "meta": "Estructura del proyecto, entorno local y tests de Purgito.",
        "doc": True,
    },
    {
        "slug": "documentacion/referencia",
        "src": "documentacion/referencia.html",
        "title": "Referencia — Documentación técnica",
        "meta": "Variables de entorno de Purgito.",
        "doc": True,
    },
]

# Mismo formato que HTML_PAGES, en inglés. slug via en_slug(); src apunta a
# los cuerpos en landing/pages/en/ y landing/pages/documentacion/en/.
HTML_PAGES_EN = [
    {
        "slug": en_slug("premium"),
        "src": "en/premium.html",
        "title": "Purgito Premium",
        "meta": "Take your server to the next level with Purgito Premium: "
        "50,000-message extended memory, automatic memes, 4,000 GIFs, and "
        "priority support.",
    },
    {
        "slug": en_slug("perfil"),
        "src": "en/perfil.html",
        "title": "Profile",
        "meta": "Your Purgito account: Discord profile info, servers, and subscriptions.",
        "app": "perfil.js",
    },
    {
        "slug": en_slug("perfil/servidores"),
        "src": "en/perfil.html",
        "title": "Servers",
        "meta": "Your Discord servers with Purgito: open each one's dashboard "
        "or invite it to the ones still missing it.",
        "app": "perfil.js",
    },
    {
        "slug": en_slug("perfil/conexiones"),
        "src": "en/perfil.html",
        "title": "Connections",
        "meta": "Your Purgito account's connections to Discord and linked services.",
        "app": "perfil.js",
    },
    {
        "slug": en_slug("perfil/facturacion"),
        "src": "en/perfil.html",
        "title": "Billing",
        "meta": "The status of your Purgito Premium subscriptions and billing management.",
        "app": "perfil.js",
    },
    {
        "slug": en_slug("dashboard"),
        "src": "en/dashboard.html",
        "title": "Dashboard",
        "meta": "Configure Purgito on your server: chat, corpus, reactions, "
        "phrases, GIFs, embeds, and Premium.",
        "app": "dash.js",
        "no_footer": True,
    },
    {
        "slug": en_slug("estado"),
        "src": "en/estado.html",
        "title": "Purgito Status",
        "meta": "Purgito's live status: uptime, memory, latency to Discord, "
        "and server count. Public, no login required.",
        "module": "estado.js",
    },
    {
        "slug": en_slug("guia"),
        "src": "en/guia.html",
        "title": "Purgito Guide — How the bot works",
        "meta": "Learn how Purgito works, from the learning system and Chat "
        "to GIFs, memes, embeds, YouTube, and Premium.",
        "guia": True,
    },
    {
        "slug": en_slug("documentacion"),
        "src": "documentacion/en/index.html",
        "title": "Technical Documentation",
        "meta": "Guides, reference, and details on Purgito's architecture, "
        "APIs, internal systems, and infrastructure.",
        "doc": True,
    },
    {
        "slug": en_slug("documentacion/arquitectura"),
        "src": "documentacion/en/arquitectura.html",
        "title": "Architecture — Technical Documentation",
        "meta": "How Purgito's Discord bot, generation engine, database, and "
        "dashboard connect to each other.",
        "doc": True,
    },
    {
        "slug": en_slug("documentacion/discord"),
        "src": "documentacion/en/discord.html",
        "title": "Discord — Technical Documentation",
        "meta": "Cogs, events, permissions, and interactions of Purgito's bot.",
        "doc": True,
    },
    {
        "slug": en_slug("documentacion/api"),
        "src": "documentacion/en/api.html",
        "title": "API — Technical Documentation",
        "meta": "Authentication, sessions, endpoints, and webhooks of Purgito's API.",
        "doc": True,
    },
    {
        "slug": en_slug("documentacion/generacion"),
        "src": "documentacion/en/generacion.html",
        "title": "Generation engine — Technical Documentation",
        "meta": "How Purgito generates text: Markov chains, corpus, "
        "concurrency, and limits.",
        "doc": True,
    },
    {
        "slug": en_slug("documentacion/almacenamiento"),
        "src": "documentacion/en/almacenamiento.html",
        "title": "Storage — Technical Documentation",
        "meta": "SQLite, Cloudflare R2, in-memory caches, and data retention in Purgito.",
        "doc": True,
    },
    {
        "slug": en_slug("documentacion/seguridad"),
        "src": "documentacion/en/seguridad.html",
        "title": "Security — Technical Documentation",
        "meta": "Purgito's security model: OAuth2, sessions, permissions, and rate limits.",
        "doc": True,
    },
    {
        "slug": en_slug("documentacion/infraestructura"),
        "src": "documentacion/en/infraestructura.html",
        "title": "Infrastructure — Technical Documentation",
        "meta": "Runtime, nginx, Cloudflare, and Purgito's production deployment.",
        "doc": True,
    },
    {
        "slug": en_slug("documentacion/desarrollo"),
        "src": "documentacion/en/desarrollo.html",
        "title": "Development — Technical Documentation",
        "meta": "Purgito's project structure, local environment, and tests.",
        "doc": True,
    },
    {
        "slug": en_slug("documentacion/referencia"),
        "src": "documentacion/en/referencia.html",
        "title": "Reference — Technical Documentation",
        "meta": "Purgito's environment variables.",
        "doc": True,
    },
]

# Mismo formato que HTML_PAGES_EN, en ruso/japonés/alemán. El slug es el
# mismo literal que en HTML_PAGES (ver la nota de PAGES_RU/JA/DE más arriba);
# src apunta a landing/pages/{ru,ja,de}/*.html y
# landing/pages/documentacion/{ru,ja,de}/*.html, que agrega el agente de
# traducción de contenido.
HTML_PAGES_RU = [
    {
        "slug": "premium",
        "src": "ru/premium.html",
        "title": "Purgito Premium",
        "meta": "Выведи свой сервер на новый уровень с Purgito Premium: "
        "расширенная память на 50 000 сообщений, автоматические мемы, "
        "4 000 GIF и приоритетная поддержка.",
    },
    {
        "slug": "perfil",
        "src": "ru/perfil.html",
        "title": "Профиль",
        "meta": "Твой аккаунт Purgito: данные профиля Discord, серверы и подписки.",
        "app": "perfil.js",
    },
    {
        "slug": "perfil/servidores",
        "src": "ru/perfil.html",
        "title": "Серверы",
        "meta": "Твои серверы Discord с Purgito: заходи в панель управления "
        "каждого или пригласи бота туда, где его ещё нет.",
        "app": "perfil.js",
    },
    {
        "slug": "perfil/conexiones",
        "src": "ru/perfil.html",
        "title": "Подключения",
        "meta": "Подключения твоего аккаунта Purgito к Discord и связанным сервисам.",
        "app": "perfil.js",
    },
    {
        "slug": "perfil/facturacion",
        "src": "ru/perfil.html",
        "title": "Оплата",
        "meta": "Статус твоих Premium-подписок Purgito и управление платежами.",
        "app": "perfil.js",
    },
    {
        "slug": "dashboard",
        "src": "ru/dashboard.html",
        "title": "Панель управления",
        "meta": "Настрой Purgito на своём сервере: чат, корпус, реакции, "
        "фразы, GIF, embed-сообщения и premium.",
        "app": "dash.js",
        "no_footer": True,
    },
    {
        "slug": "estado",
        "src": "ru/estado.html",
        "title": "Статус Purgito",
        "meta": "Статус Purgito в реальном времени: время работы, память, "
        "задержка соединения с Discord и количество серверов. Публичная "
        "страница, вход не требуется.",
        "module": "estado.js",
    },
    {
        "slug": "guia",
        "src": "ru/guia.html",
        "title": "Гид по Purgito — Как работает бот",
        "meta": "Узнай, как работает Purgito: от системы обучения и чата до "
        "GIF, мемов, embed-сообщений, YouTube и Premium.",
        "guia": True,
    },
    {
        "slug": "documentacion",
        "src": "documentacion/ru/index.html",
        "title": "Техническая документация",
        "meta": "Руководства, справочник и подробности об архитектуре, API, "
        "внутренних системах и инфраструктуре Purgito.",
        "doc": True,
    },
    {
        "slug": "documentacion/arquitectura",
        "src": "documentacion/ru/arquitectura.html",
        "title": "Архитектура — Техническая документация",
        "meta": "Как связаны между собой бот Discord, движок генерации, "
        "база данных и панель управления Purgito.",
        "doc": True,
    },
    {
        "slug": "documentacion/discord",
        "src": "documentacion/ru/discord.html",
        "title": "Discord — Техническая документация",
        "meta": "Коги (cogs), события, разрешения и взаимодействия бота Purgito.",
        "doc": True,
    },
    {
        "slug": "documentacion/api",
        "src": "documentacion/ru/api.html",
        "title": "API — Техническая документация",
        "meta": "Аутентификация, сессии, эндпоинты и вебхуки API Purgito.",
        "doc": True,
    },
    {
        "slug": "documentacion/generacion",
        "src": "documentacion/ru/generacion.html",
        "title": "Движок генерации — Техническая документация",
        "meta": "Как Purgito генерирует текст: цепи Маркова, корпус, "
        "параллелизм и ограничения.",
        "doc": True,
    },
    {
        "slug": "documentacion/almacenamiento",
        "src": "documentacion/ru/almacenamiento.html",
        "title": "Хранилище — Техническая документация",
        "meta": "SQLite, Cloudflare R2, кэши в памяти и хранение данных в Purgito.",
        "doc": True,
    },
    {
        "slug": "documentacion/seguridad",
        "src": "documentacion/ru/seguridad.html",
        "title": "Безопасность — Техническая документация",
        "meta": "Модель безопасности Purgito: OAuth2, сессии, разрешения и "
        "лимиты использования.",
        "doc": True,
    },
    {
        "slug": "documentacion/infraestructura",
        "src": "documentacion/ru/infraestructura.html",
        "title": "Инфраструктура — Техническая документация",
        "meta": "Runtime, nginx, Cloudflare и развёртывание Purgito в продакшене.",
        "doc": True,
    },
    {
        "slug": "documentacion/desarrollo",
        "src": "documentacion/ru/desarrollo.html",
        "title": "Разработка — Техническая документация",
        "meta": "Структура проекта, локальное окружение и тесты Purgito.",
        "doc": True,
    },
    {
        "slug": "documentacion/referencia",
        "src": "documentacion/ru/referencia.html",
        "title": "Справочник — Техническая документация",
        "meta": "Переменные окружения Purgito.",
        "doc": True,
    },
]

HTML_PAGES_JA = [
    {
        "slug": "premium",
        "src": "ja/premium.html",
        "title": "Purgito Premium",
        "meta": "Purgito Premiumでサーバーを次のレベルへ:5万件のメッセージを"
        "記憶する拡張メモリ、自動ミーム生成、4,000件のGIF、優先サポート。",
    },
    {
        "slug": "perfil",
        "src": "ja/perfil.html",
        "title": "プロフィール",
        "meta": "あなたのPurgitoアカウント:Discordのプロフィール情報、"
        "サーバー、サブスクリプション。",
        "app": "perfil.js",
    },
    {
        "slug": "perfil/servidores",
        "src": "ja/perfil.html",
        "title": "サーバー",
        "meta": "Purgitoを導入したあなたのDiscordサーバー:各サーバーの"
        "ダッシュボードを開くか、未導入のサーバーに招待できます。",
        "app": "perfil.js",
    },
    {
        "slug": "perfil/conexiones",
        "src": "ja/perfil.html",
        "title": "連携",
        "meta": "PurgitoアカウントとDiscordおよび連携サービスとの接続情報。",
        "app": "perfil.js",
    },
    {
        "slug": "perfil/facturacion",
        "src": "ja/perfil.html",
        "title": "請求",
        "meta": "Purgito Premiumサブスクリプションの状況と請求管理。",
        "app": "perfil.js",
    },
    {
        "slug": "dashboard",
        "src": "ja/dashboard.html",
        "title": "ダッシュボード",
        "meta": "サーバーでのPurgitoの設定:チャット、コーパス、リアクション、"
        "フレーズ、GIF、embed、premium。",
        "app": "dash.js",
        "no_footer": True,
    },
    {
        "slug": "estado",
        "src": "ja/estado.html",
        "title": "Purgitoのステータス",
        "meta": "Purgitoのリアルタイムステータス:稼働時間、メモリ使用量、"
        "Discordとの通信遅延、導入サーバー数。ログイン不要で公開されています。",
        "module": "estado.js",
    },
    {
        "slug": "guia",
        "src": "ja/guia.html",
        "title": "Purgitoガイド — ボットの仕組み",
        "meta": "学習システムやチャットから、GIF、ミーム、embed、YouTube、"
        "Premiumまで、Purgitoの仕組みを解説します。",
        "guia": True,
    },
    {
        "slug": "documentacion",
        "src": "documentacion/ja/index.html",
        "title": "技術ドキュメント",
        "meta": "Purgitoのアーキテクチャ、API、内部システム、インフラに関する"
        "ガイド、リファレンス、詳細情報。",
        "doc": True,
    },
    {
        "slug": "documentacion/arquitectura",
        "src": "documentacion/ja/arquitectura.html",
        "title": "アーキテクチャ — 技術ドキュメント",
        "meta": "DiscordボットPurgitoの生成エンジン、データベース、"
        "ダッシュボードがどのように連携しているか。",
        "doc": True,
    },
    {
        "slug": "documentacion/discord",
        "src": "documentacion/ja/discord.html",
        "title": "Discord — 技術ドキュメント",
        "meta": "PurgitoボットのCog、イベント、権限、インタラクションについて。",
        "doc": True,
    },
    {
        "slug": "documentacion/api",
        "src": "documentacion/ja/api.html",
        "title": "API — 技術ドキュメント",
        "meta": "Purgito APIの認証、セッション、エンドポイント、Webhookについて。",
        "doc": True,
    },
    {
        "slug": "documentacion/generacion",
        "src": "documentacion/ja/generacion.html",
        "title": "生成エンジン — 技術ドキュメント",
        "meta": "Purgitoがテキストを生成する仕組み:マルコフ連鎖、コーパス、"
        "並行処理と制限について。",
        "doc": True,
    },
    {
        "slug": "documentacion/almacenamiento",
        "src": "documentacion/ja/almacenamiento.html",
        "title": "ストレージ — 技術ドキュメント",
        "meta": "PurgitoにおけるSQLite、Cloudflare R2、インメモリキャッシュ、"
        "データ保持について。",
        "doc": True,
    },
    {
        "slug": "documentacion/seguridad",
        "src": "documentacion/ja/seguridad.html",
        "title": "セキュリティ — 技術ドキュメント",
        "meta": "Purgitoのセキュリティモデル:OAuth2、セッション、権限、"
        "利用制限について。",
        "doc": True,
    },
    {
        "slug": "documentacion/infraestructura",
        "src": "documentacion/ja/infraestructura.html",
        "title": "インフラストラクチャ — 技術ドキュメント",
        "meta": "Purgitoの本番環境におけるランタイム、nginx、Cloudflare、"
        "デプロイについて。",
        "doc": True,
    },
    {
        "slug": "documentacion/desarrollo",
        "src": "documentacion/ja/desarrollo.html",
        "title": "開発 — 技術ドキュメント",
        "meta": "Purgitoのプロジェクト構成、ローカル環境、テストについて。",
        "doc": True,
    },
    {
        "slug": "documentacion/referencia",
        "src": "documentacion/ja/referencia.html",
        "title": "リファレンス — 技術ドキュメント",
        "meta": "Purgitoの環境変数について。",
        "doc": True,
    },
]

HTML_PAGES_DE = [
    {
        "slug": "premium",
        "src": "de/premium.html",
        "title": "Purgito Premium",
        "meta": "Bring deinen Server mit Purgito Premium auf die nächste "
        "Stufe: erweiterter Speicher für 50.000 Nachrichten, automatische "
        "Memes, 4.000 GIFs und priorisierter Support.",
    },
    {
        "slug": "perfil",
        "src": "de/perfil.html",
        "title": "Profil",
        "meta": "Dein Purgito-Konto: Discord-Profilinformationen, Server und Abonnements.",
        "app": "perfil.js",
    },
    {
        "slug": "perfil/servidores",
        "src": "de/perfil.html",
        "title": "Server",
        "meta": "Deine Discord-Server mit Purgito: öffne das Dashboard für "
        "jeden einzelnen oder lade den Bot auf die ein, die noch fehlen.",
        "app": "perfil.js",
    },
    {
        "slug": "perfil/conexiones",
        "src": "de/perfil.html",
        "title": "Verbindungen",
        "meta": "Verbindungen deines Purgito-Kontos mit Discord und verknüpften Diensten.",
        "app": "perfil.js",
    },
    {
        "slug": "perfil/facturacion",
        "src": "de/perfil.html",
        "title": "Abrechnung",
        "meta": "Status deiner Purgito-Premium-Abonnements und Rechnungsverwaltung.",
        "app": "perfil.js",
    },
    {
        "slug": "dashboard",
        "src": "de/dashboard.html",
        "title": "Dashboard",
        "meta": "Konfiguriere Purgito auf deinem Server: Chat, Korpus, "
        "Reaktionen, Sprüche, GIFs, Embeds und Premium.",
        "app": "dash.js",
        "no_footer": True,
    },
    {
        "slug": "estado",
        "src": "de/estado.html",
        "title": "Purgito-Status",
        "meta": "Live-Status von Purgito: Betriebszeit, Speicher, Latenz zu "
        "Discord und Anzahl der Server. Öffentlich, ohne Login.",
        "module": "estado.js",
    },
    {
        "slug": "guia",
        "src": "de/guia.html",
        "title": "Purgito-Leitfaden — So funktioniert der Bot",
        "meta": "Erfahre, wie Purgito funktioniert: vom Lernsystem und Chat "
        "bis zu GIFs, Memes, Embeds, YouTube und Premium.",
        "guia": True,
    },
    {
        "slug": "documentacion",
        "src": "documentacion/de/index.html",
        "title": "Technische Dokumentation",
        "meta": "Anleitungen, Referenz und Details zu Architektur, APIs, "
        "internen Systemen und Infrastruktur von Purgito.",
        "doc": True,
    },
    {
        "slug": "documentacion/arquitectura",
        "src": "documentacion/de/arquitectura.html",
        "title": "Architektur — Technische Dokumentation",
        "meta": "Wie der Discord-Bot, die Generierungs-Engine, die Datenbank "
        "und das Dashboard von Purgito miteinander verbunden sind.",
        "doc": True,
    },
    {
        "slug": "documentacion/discord",
        "src": "documentacion/de/discord.html",
        "title": "Discord — Technische Dokumentation",
        "meta": "Cogs, Ereignisse, Berechtigungen und Interaktionen des Purgito-Bots.",
        "doc": True,
    },
    {
        "slug": "documentacion/api",
        "src": "documentacion/de/api.html",
        "title": "API — Technische Dokumentation",
        "meta": "Authentifizierung, Sitzungen, Endpunkte und Webhooks der Purgito-API.",
        "doc": True,
    },
    {
        "slug": "documentacion/generacion",
        "src": "documentacion/de/generacion.html",
        "title": "Generierungs-Engine — Technische Dokumentation",
        "meta": "Wie Purgito Text generiert: Markov-Ketten, Korpus, "
        "Nebenläufigkeit und Limits.",
        "doc": True,
    },
    {
        "slug": "documentacion/almacenamiento",
        "src": "documentacion/de/almacenamiento.html",
        "title": "Speicher — Technische Dokumentation",
        "meta": "SQLite, Cloudflare R2, In-Memory-Caches und Datenaufbewahrung bei Purgito.",
        "doc": True,
    },
    {
        "slug": "documentacion/seguridad",
        "src": "documentacion/de/seguridad.html",
        "title": "Sicherheit — Technische Dokumentation",
        "meta": "Sicherheitsmodell von Purgito: OAuth2, Sitzungen, "
        "Berechtigungen und Nutzungslimits.",
        "doc": True,
    },
    {
        "slug": "documentacion/infraestructura",
        "src": "documentacion/de/infraestructura.html",
        "title": "Infrastruktur — Technische Dokumentation",
        "meta": "Runtime, nginx, Cloudflare und Produktions-Deployment von Purgito.",
        "doc": True,
    },
    {
        "slug": "documentacion/desarrollo",
        "src": "documentacion/de/desarrollo.html",
        "title": "Entwicklung — Technische Dokumentation",
        "meta": "Projektstruktur, lokale Umgebung und Tests von Purgito.",
        "doc": True,
    },
    {
        "slug": "documentacion/referencia",
        "src": "documentacion/de/referencia.html",
        "title": "Referenz — Technische Dokumentation",
        "meta": "Umgebungsvariablen von Purgito.",
        "doc": True,
    },
]

# Estructura de /es/documentacion: una entrada por página. Los "subs" son
# anclas dentro de esa misma página (no páginas propias) — ver Task 1 del
# plan de documentación técnica para el porqué de la granularidad agrupada.
DOC_SECTIONS = [
    {"slug": "documentacion", "label": "Inicio", "subs": []},
    {
        "slug": "documentacion/arquitectura",
        "label": "Arquitectura",
        "subs": [
            ("vision-general", "Visión general"),
            ("componentes", "Componentes"),
            ("flujo-de-una-peticion", "Flujo de una petición"),
        ],
    },
    {
        "slug": "documentacion/discord",
        "label": "Discord",
        "subs": [
            ("bot-y-cogs", "Bot y cogs"),
            ("eventos", "Eventos"),
            ("permisos", "Permisos"),
            ("interacciones", "Interacciones"),
        ],
    },
    {
        "slug": "documentacion/api",
        "label": "API",
        "subs": [
            ("vision-general", "Visión general"),
            ("autenticacion", "Autenticación"),
            ("sesiones", "Sesiones"),
            ("endpoints", "Endpoints"),
            ("webhooks", "Webhooks"),
        ],
    },
    {
        "slug": "documentacion/generacion",
        "label": "Generación",
        "subs": [
            ("motor-markov", "Motor de Markov"),
            ("corpus", "Corpus"),
            ("pipeline", "Pipeline de generación"),
            ("concurrencia-y-limites", "Concurrencia y límites"),
        ],
    },
    {
        "slug": "documentacion/almacenamiento",
        "label": "Almacenamiento",
        "subs": [
            ("sqlite", "SQLite"),
            ("r2", "R2"),
            ("cache", "Caché"),
            ("retencion", "Retención de datos"),
        ],
    },
    {
        "slug": "documentacion/seguridad",
        "label": "Seguridad",
        "subs": [
            ("oauth2", "OAuth2"),
            ("permisos", "Permisos"),
            ("rate-limits", "Límites de uso"),
            ("modelo-de-seguridad", "Modelo de seguridad"),
        ],
    },
    {
        "slug": "documentacion/infraestructura",
        "label": "Infraestructura",
        "subs": [
            ("runtime", "Runtime"),
            ("nginx", "Nginx"),
            ("cloudflare", "Cloudflare"),
            ("deployment", "Despliegue"),
            ("health-checks", "Chequeos de salud"),
        ],
    },
    {
        "slug": "documentacion/desarrollo",
        "label": "Desarrollo",
        "subs": [
            ("estructura-del-proyecto", "Estructura del proyecto"),
            ("entorno-local", "Entorno local"),
            ("tests", "Tests"),
        ],
    },
    {
        "slug": "documentacion/referencia",
        "label": "Referencia",
        "subs": [
            ("variables-de-entorno", "Variables de entorno"),
        ],
    },
]


# Mismas categorías y anclas que DOC_SECTIONS, en inglés. slug via en_slug().
DOC_SECTIONS_EN = [
    {"slug": en_slug("documentacion"), "label": "Home", "subs": []},
    {
        "slug": en_slug("documentacion/arquitectura"),
        "label": "Architecture",
        "subs": [
            ("overview", "Overview"),
            ("components", "Components"),
            ("request-flow", "Request flow"),
        ],
    },
    {
        "slug": en_slug("documentacion/discord"),
        "label": "Discord",
        "subs": [
            ("bot-and-cogs", "Bot and cogs"),
            ("events", "Events"),
            ("permissions", "Permissions"),
            ("interactions", "Interactions"),
        ],
    },
    {
        "slug": en_slug("documentacion/api"),
        "label": "API",
        "subs": [
            ("overview", "Overview"),
            ("authentication", "Authentication"),
            ("sessions", "Sessions"),
            ("endpoints", "Endpoints"),
            ("webhooks", "Webhooks"),
        ],
    },
    {
        "slug": en_slug("documentacion/generacion"),
        "label": "Generation",
        "subs": [
            ("markov-engine", "Markov engine"),
            ("corpus", "Corpus"),
            ("pipeline", "Generation pipeline"),
            ("concurrency-and-limits", "Concurrency and limits"),
        ],
    },
    {
        "slug": en_slug("documentacion/almacenamiento"),
        "label": "Storage",
        "subs": [
            ("sqlite", "SQLite"),
            ("r2", "R2"),
            ("cache", "Cache"),
            ("retention", "Data retention"),
        ],
    },
    {
        "slug": en_slug("documentacion/seguridad"),
        "label": "Security",
        "subs": [
            ("oauth2", "OAuth2"),
            ("permissions", "Permissions"),
            ("rate-limits", "Rate limits"),
            ("security-model", "Security model"),
        ],
    },
    {
        "slug": en_slug("documentacion/infraestructura"),
        "label": "Infrastructure",
        "subs": [
            ("runtime", "Runtime"),
            ("nginx", "Nginx"),
            ("cloudflare", "Cloudflare"),
            ("deployment", "Deployment"),
            ("health-checks", "Health checks"),
        ],
    },
    {
        "slug": en_slug("documentacion/desarrollo"),
        "label": "Development",
        "subs": [
            ("project-structure", "Project structure"),
            ("local-environment", "Local environment"),
            ("tests", "Tests"),
        ],
    },
    {
        "slug": en_slug("documentacion/referencia"),
        "label": "Reference",
        "subs": [
            ("environment-variables", "Environment variables"),
        ],
    },
]

# RU/JA/DE: mismos slugs y anchors que DOC_SECTIONS (ver la nota de arriba),
# solo cambia el texto visible (label y las etiquetas de subs).
DOC_SECTIONS_RU = [
    {"slug": "documentacion", "label": "Главная", "subs": []},
    {
        "slug": "documentacion/arquitectura",
        "label": "Архитектура",
        "subs": [
            ("vision-general", "Общий обзор"),
            ("componentes", "Компоненты"),
            ("flujo-de-una-peticion", "Поток обработки запроса"),
        ],
    },
    {
        "slug": "documentacion/discord",
        "label": "Discord",
        "subs": [
            ("bot-y-cogs", "Бот и коги (cogs)"),
            ("eventos", "События"),
            ("permisos", "Разрешения"),
            ("interacciones", "Взаимодействия"),
        ],
    },
    {
        "slug": "documentacion/api",
        "label": "API",
        "subs": [
            ("vision-general", "Общий обзор"),
            ("autenticacion", "Аутентификация"),
            ("sesiones", "Сессии"),
            ("endpoints", "Эндпоинты"),
            ("webhooks", "Вебхуки"),
        ],
    },
    {
        "slug": "documentacion/generacion",
        "label": "Генерация",
        "subs": [
            ("motor-markov", "Движок Маркова"),
            ("corpus", "Корпус"),
            ("pipeline", "Конвейер генерации"),
            ("concurrencia-y-limites", "Параллелизм и ограничения"),
        ],
    },
    {
        "slug": "documentacion/almacenamiento",
        "label": "Хранилище",
        "subs": [
            ("sqlite", "SQLite"),
            ("r2", "R2"),
            ("cache", "Кэш"),
            ("retencion", "Хранение данных"),
        ],
    },
    {
        "slug": "documentacion/seguridad",
        "label": "Безопасность",
        "subs": [
            ("oauth2", "OAuth2"),
            ("permisos", "Разрешения"),
            ("rate-limits", "Лимиты запросов"),
            ("modelo-de-seguridad", "Модель безопасности"),
        ],
    },
    {
        "slug": "documentacion/infraestructura",
        "label": "Инфраструктура",
        "subs": [
            ("runtime", "Runtime"),
            ("nginx", "Nginx"),
            ("cloudflare", "Cloudflare"),
            ("deployment", "Развёртывание"),
            ("health-checks", "Проверки состояния"),
        ],
    },
    {
        "slug": "documentacion/desarrollo",
        "label": "Разработка",
        "subs": [
            ("estructura-del-proyecto", "Структура проекта"),
            ("entorno-local", "Локальное окружение"),
            ("tests", "Тесты"),
        ],
    },
    {
        "slug": "documentacion/referencia",
        "label": "Справочник",
        "subs": [
            ("variables-de-entorno", "Переменные окружения"),
        ],
    },
]

DOC_SECTIONS_JA = [
    {"slug": "documentacion", "label": "ホーム", "subs": []},
    {
        "slug": "documentacion/arquitectura",
        "label": "アーキテクチャ",
        "subs": [
            ("vision-general", "概要"),
            ("componentes", "コンポーネント"),
            ("flujo-de-una-peticion", "リクエストの流れ"),
        ],
    },
    {
        "slug": "documentacion/discord",
        "label": "Discord",
        "subs": [
            ("bot-y-cogs", "ボットとCog"),
            ("eventos", "イベント"),
            ("permisos", "権限"),
            ("interacciones", "インタラクション"),
        ],
    },
    {
        "slug": "documentacion/api",
        "label": "API",
        "subs": [
            ("vision-general", "概要"),
            ("autenticacion", "認証"),
            ("sesiones", "セッション"),
            ("endpoints", "エンドポイント"),
            ("webhooks", "Webhook"),
        ],
    },
    {
        "slug": "documentacion/generacion",
        "label": "生成エンジン",
        "subs": [
            ("motor-markov", "マルコフエンジン"),
            ("corpus", "コーパス"),
            ("pipeline", "生成パイプライン"),
            ("concurrencia-y-limites", "並行処理と制限"),
        ],
    },
    {
        "slug": "documentacion/almacenamiento",
        "label": "ストレージ",
        "subs": [
            ("sqlite", "SQLite"),
            ("r2", "R2"),
            ("cache", "キャッシュ"),
            ("retencion", "データ保持"),
        ],
    },
    {
        "slug": "documentacion/seguridad",
        "label": "セキュリティ",
        "subs": [
            ("oauth2", "OAuth2"),
            ("permisos", "権限"),
            ("rate-limits", "レート制限"),
            ("modelo-de-seguridad", "セキュリティモデル"),
        ],
    },
    {
        "slug": "documentacion/infraestructura",
        "label": "インフラストラクチャ",
        "subs": [
            ("runtime", "ランタイム"),
            ("nginx", "Nginx"),
            ("cloudflare", "Cloudflare"),
            ("deployment", "デプロイ"),
            ("health-checks", "ヘルスチェック"),
        ],
    },
    {
        "slug": "documentacion/desarrollo",
        "label": "開発",
        "subs": [
            ("estructura-del-proyecto", "プロジェクト構成"),
            ("entorno-local", "ローカル環境"),
            ("tests", "テスト"),
        ],
    },
    {
        "slug": "documentacion/referencia",
        "label": "リファレンス",
        "subs": [
            ("variables-de-entorno", "環境変数"),
        ],
    },
]

DOC_SECTIONS_DE = [
    {"slug": "documentacion", "label": "Start", "subs": []},
    {
        "slug": "documentacion/arquitectura",
        "label": "Architektur",
        "subs": [
            ("vision-general", "Überblick"),
            ("componentes", "Komponenten"),
            ("flujo-de-una-peticion", "Ablauf einer Anfrage"),
        ],
    },
    {
        "slug": "documentacion/discord",
        "label": "Discord",
        "subs": [
            ("bot-y-cogs", "Bot und Cogs"),
            ("eventos", "Ereignisse"),
            ("permisos", "Berechtigungen"),
            ("interacciones", "Interaktionen"),
        ],
    },
    {
        "slug": "documentacion/api",
        "label": "API",
        "subs": [
            ("vision-general", "Überblick"),
            ("autenticacion", "Authentifizierung"),
            ("sesiones", "Sitzungen"),
            ("endpoints", "Endpunkte"),
            ("webhooks", "Webhooks"),
        ],
    },
    {
        "slug": "documentacion/generacion",
        "label": "Generierung",
        "subs": [
            ("motor-markov", "Markov-Engine"),
            ("corpus", "Korpus"),
            ("pipeline", "Generierungs-Pipeline"),
            ("concurrencia-y-limites", "Nebenläufigkeit und Limits"),
        ],
    },
    {
        "slug": "documentacion/almacenamiento",
        "label": "Speicher",
        "subs": [
            ("sqlite", "SQLite"),
            ("r2", "R2"),
            ("cache", "Cache"),
            ("retencion", "Datenaufbewahrung"),
        ],
    },
    {
        "slug": "documentacion/seguridad",
        "label": "Sicherheit",
        "subs": [
            ("oauth2", "OAuth2"),
            ("permisos", "Berechtigungen"),
            ("rate-limits", "Ratenbegrenzungen"),
            ("modelo-de-seguridad", "Sicherheitsmodell"),
        ],
    },
    {
        "slug": "documentacion/infraestructura",
        "label": "Infrastruktur",
        "subs": [
            ("runtime", "Runtime"),
            ("nginx", "Nginx"),
            ("cloudflare", "Cloudflare"),
            ("deployment", "Deployment"),
            ("health-checks", "Health-Checks"),
        ],
    },
    {
        "slug": "documentacion/desarrollo",
        "label": "Entwicklung",
        "subs": [
            ("estructura-del-proyecto", "Projektstruktur"),
            ("entorno-local", "Lokale Umgebung"),
            ("tests", "Tests"),
        ],
    },
    {
        "slug": "documentacion/referencia",
        "label": "Referenz",
        "subs": [
            ("variables-de-entorno", "Umgebungsvariablen"),
        ],
    },
]

# ru/ja/de (si existen) reutilizan el slug español tal cual -- ver
# SLUG_MAP_ES_EN -- pero sí traducen label y las etiquetas de subs; el
# anchor (primer elemento de cada tupla) se mantiene igual en los 5 idiomas
# porque es un fragmento de URL invisible, no texto que lea nadie.
DOC_SECTIONS_BY_LANG = {
    "es": DOC_SECTIONS,
    "en": DOC_SECTIONS_EN,
    "ru": DOC_SECTIONS_RU,
    "ja": DOC_SECTIONS_JA,
    "de": DOC_SECTIONS_DE,
}


DOC_SIDEBAR_LABEL = {
    "es": "Categorías",
    "en": "Categories",
    "ru": "Категории",
    "ja": "カテゴリー",
    "de": "Kategorien",
}
DOC_SIDEBAR_ARIA = {
    "es": "Documentación técnica",
    "en": "Technical documentation",
    "ru": "Техническая документация",
    "ja": "技術ドキュメント",
    "de": "Technische Dokumentation",
}


def doc_sidebar(current_slug, lang="es"):
    """Sidebar de /{lang}/documentacion: categorías + anclas de la página activa.

    Sin JS: la categoría activa se resuelve en build time (cada página sabe
    su propio slug) y las anclas son <a href="#id"> normales.
    """
    sections = DOC_SECTIONS_BY_LANG[lang]
    label = DOC_SIDEBAR_LABEL[lang]
    aria = DOC_SIDEBAR_ARIA[lang]
    items = []
    for sec in sections:
        active = sec["slug"] == current_slug
        cls = ' class="active"' if active else ""
        href = "/%s/%s" % (lang, sec["slug"])
        items.append(
            '    <li><a%s href="%s">%s</a>' % (cls, href, html.escape(sec["label"]))
        )
        if active and sec["subs"]:
            sub_items = "".join(
                '<li><a href="#%s">%s</a></li>' % (anchor, html.escape(label_))
                for anchor, label_ in sec["subs"]
            )
            items.append('      <ul class="docs-subnav">%s</ul>' % sub_items)
        items.append("    </li>")
    return (
        '<details class="docs-sidebar" open aria-label="%s">\n'
        "  <summary>%s</summary>\n"
        "  <ul>\n%s\n  </ul>\n</details>" % (aria, label, "\n".join(items))
    )


# Estructura de /es/guia: navegación por anclas para la página única de la Guía.
GUIA_SECTIONS = [
    ("introduccion", "Introducción"),
    ("primeros-pasos", "Primeros pasos"),
    ("como-aprende", "Cómo aprende Purgito"),
    ("chat", "Chat"),
    ("corpus", "Corpus"),
    ("gifs", "GIFs"),
    ("memes", "Memes"),
    ("reacciones", "Reacciones"),
    ("frases-y-packs", "Frases y packs"),
    ("triggers", "Triggers"),
    ("embeds", "Embeds"),
    ("youtube", "YouTube"),
    ("anuncios", "Anuncios programados"),
    ("premium", "Premium"),
    ("dashboard", "Dashboard"),
    ("historial", "Historial"),
]


GUIA_SECTIONS_EN = [
    ("introduction", "Introduction"),
    ("getting-started", "Getting started"),
    ("how-purgito-learns", "How Purgito learns"),
    ("chat", "Chat"),
    ("corpus", "Corpus"),
    ("gifs", "GIFs"),
    ("memes", "Memes"),
    ("reactions", "Reactions"),
    ("phrases-and-packs", "Phrases and packs"),
    ("triggers", "Triggers"),
    ("embeds", "Embeds"),
    ("youtube", "YouTube"),
    ("scheduled-announcements", "Scheduled announcements"),
    ("premium", "Premium"),
    ("dashboard", "Dashboard"),
    ("history", "History"),
]


# ru/ja/de (si existen) reutilizan el anchor español tal cual -- ver la nota
# de DOC_SECTIONS_BY_LANG, mismo motivo.
# Mismos anchors que GUIA_SECTIONS (fragmento de URL invisible), solo cambia
# el label visible.
GUIA_SECTIONS_RU = [
    ("introduccion", "Введение"),
    ("primeros-pasos", "Первые шаги"),
    ("como-aprende", "Как учится Purgito"),
    ("chat", "Чат"),
    ("corpus", "Корпус"),
    ("gifs", "GIF-файлы"),
    ("memes", "Мемы"),
    ("reacciones", "Реакции"),
    ("frases-y-packs", "Фразы и наборы"),
    ("triggers", "Триггеры"),
    ("embeds", "Embed-сообщения"),
    ("youtube", "YouTube"),
    ("anuncios", "Запланированные объявления"),
    ("premium", "Premium"),
    ("dashboard", "Панель управления"),
    ("historial", "История изменений"),
]

GUIA_SECTIONS_JA = [
    ("introduccion", "はじめに"),
    ("primeros-pasos", "最初のステップ"),
    ("como-aprende", "Purgitoの学習方法"),
    ("chat", "チャット"),
    ("corpus", "コーパス"),
    ("gifs", "GIF"),
    ("memes", "ミーム"),
    ("reacciones", "リアクション"),
    ("frases-y-packs", "フレーズとパック"),
    ("triggers", "トリガー"),
    ("embeds", "Embed"),
    ("youtube", "YouTube"),
    ("anuncios", "予約投稿"),
    ("premium", "Premium"),
    ("dashboard", "ダッシュボード"),
    ("historial", "履歴"),
]

GUIA_SECTIONS_DE = [
    ("introduccion", "Einführung"),
    ("primeros-pasos", "Erste Schritte"),
    ("como-aprende", "Wie Purgito lernt"),
    ("chat", "Chat"),
    ("corpus", "Korpus"),
    ("gifs", "GIFs"),
    ("memes", "Memes"),
    ("reacciones", "Reaktionen"),
    ("frases-y-packs", "Sprüche und Packs"),
    ("triggers", "Trigger"),
    ("embeds", "Embeds"),
    ("youtube", "YouTube"),
    ("anuncios", "Geplante Ankündigungen"),
    ("premium", "Premium"),
    ("dashboard", "Dashboard"),
    ("historial", "Verlauf"),
]

GUIA_SECTIONS_BY_LANG = {
    "es": GUIA_SECTIONS,
    "en": GUIA_SECTIONS_EN,
    "ru": GUIA_SECTIONS_RU,
    "ja": GUIA_SECTIONS_JA,
    "de": GUIA_SECTIONS_DE,
}
GUIA_SIDEBAR_SUMMARY = {
    "es": "Guía ▾",
    "en": "Guide ▾",
    "ru": "Гид ▾",
    "ja": "ガイド ▾",
    "de": "Leitfaden ▾",
}
GUIA_SIDEBAR_ARIA = {
    "es": "Guía de Purgito",
    "en": "Purgito Guide",
    "ru": "Гид по Purgito",
    "ja": "Purgitoガイド",
    "de": "Purgito-Leitfaden",
}


def guia_sidebar(lang="es"):
    """Sidebar de /{lang}/guia: navegación por anclas a las secciones de la página.

    Funciona con anchors directos (#id) en una sola página. En móvil se pliega
    en un <details> accesible con summary 'Guía ▾'.
    """
    sections = GUIA_SECTIONS_BY_LANG[lang]
    summary = GUIA_SIDEBAR_SUMMARY[lang]
    aria = GUIA_SIDEBAR_ARIA[lang]
    items = []
    for anchor, label in sections:
        items.append('    <li><a href="#%s">%s</a></li>' % (anchor, html.escape(label)))
    return (
        '<details class="docs-sidebar guia-sidebar" open aria-label="%s">\n'
        "  <summary>%s</summary>\n"
        "  <ul>\n%s\n  </ul>\n</details>" % (aria, summary, "\n".join(items))
    )


# ── markdown → html ──────────────────────────────────────────────────────────


def inline(text):
    """`code`, **negrita** y [texto](url) sobre texto ya escapado."""
    out = html.escape(text)
    out = re.sub(r"`([^`]+)`", r'<code class="cmd">\1</code>', out)
    out = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", out)
    out = re.sub(
        r"\[([^\]]+)\]\(([^)]+)\)",
        r'<a href="\2" target="_blank" rel="noopener">\1</a>',
        out,
    )
    return out


def render(body):
    """Cuerpo de una sección → HTML. Agrupa listas y párrafos multilínea."""
    out, para, items = [], [], []

    def flush():
        if para:
            out.append("<p>" + inline(" ".join(para)) + "</p>")
            para.clear()
        if items:
            out.append(
                "<ul>" + "".join("<li>%s</li>" % inline(i) for i in items) + "</ul>"
            )
            items.clear()

    for line in body.splitlines():
        line = line.strip()
        if not line or line == "---":
            flush()
        elif line.startswith("## "):
            flush()
            out.append("<h3>%s</h3>" % inline(line[3:]))
        elif line.startswith("- "):
            if para:
                flush()
            items.append(line[2:])
        elif items:
            # Bullet cortado en varias líneas: sigue el ítem, no abre párrafo.
            items[-1] += " " + line
        else:
            para.append(line)
    flush()
    return "\n".join(out)


def parse(md):
    """Devuelve (título, fecha, intro_html, [(encabezado, cuerpo_html), …]).

    Los `# ` de nivel 1 separan: el primero es el título del documento y los
    siguientes son las secciones numeradas. Un documento sin secciones de
    nivel 1 (REFUNDS) usa sus `## ` como secciones.
    """
    chunks = re.split(r"^# ", md, flags=re.M)[1:]
    head, rest = chunks[0], chunks[1:]
    if not rest:
        head, *rest = re.split(r"^## ", head, flags=re.M)

    title, _, intro = head.partition("\n")
    date = re.search(r"\*\*(?:Última actualización|Last updated):\*\*\s*(.+)", intro)
    intro = re.sub(
        r"^\*\*(?:Última actualización|Last updated):\*\*.*$", "", intro, flags=re.M
    )

    sections = []
    for chunk in rest:
        name, _, body = chunk.partition("\n")
        sections.append((name.strip(), render(body)))
    return title.strip(), date.group(1).strip() if date else "", render(intro), sections


# ── importmap y cache-busting de módulos ────────────────────────────────────


@functools.cache
def js_files():
    """(hash del árbol, rutas de landing/js/**.js) — un solo hash para todos.

    Tocar cualquier módulo invalida el árbol entero: es algo más de caché
    tirada a la basura, a cambio de un mapa estable y un diff mínimo. Son
    ~130 KB en total, no vale la pena afinarlo por archivo.
    """
    files = sorted((LANDING / "js").rglob("*.js"))
    digest = hashlib.sha256(
        b"".join(
            p.relative_to(LANDING).as_posix().encode() + p.read_bytes() for p in files
        )
    ).hexdigest()[:8]
    return digest, files


def import_map():
    """`<script type="importmap">` que le pone ?v= a cada módulo de landing/js/.

    Sin esto el cache-busting del dashboard quedaría a medias: el `?v=` del
    <script> de entrada no se propaga a lo que ese módulo importa, y Cloudflare
    (4 h de caché para .js) seguiría sirviendo los módulos internos viejos
    después de un deploy — el bug clásico de "actualicé y no cambió nada".

    Las claves son las mismas rutas absolutas que usan los `import` de
    landing/js/, así que el mapa es una sustitución 1:1: sin bare specifiers
    ni scopes, y los módulos siguen funcionando si el mapa no se aplica.
    """
    digest, files = js_files()
    entries = {
        "/" + p.relative_to(LANDING).as_posix(): "/%s?v=%s"
        % (p.relative_to(LANDING).as_posix(), digest)
        for p in files
    }
    return '<script type="importmap">\n%s\n</script>\n' % json.dumps(
        {"imports": entries}, indent=2, ensure_ascii=False
    )


def import_map_hash() -> str:
    """Calcula el hash SHA-256 del contenido exacto del `<script type="importmap">`
    para autorizarlo en la directiva script-src de la CSP sin usar 'unsafe-inline'."""
    imap = import_map()
    start = imap.find(">") + 1
    end = imap.rfind("</script>")
    script_content = imap[start:end]
    digest = base64.b64encode(
        hashlib.sha256(script_content.encode("utf-8")).digest()
    ).decode("ascii")
    return f"sha256-{digest}"


# ── página ───────────────────────────────────────────────────────────────────


# Cubre lo que el sitio realmente carga: fonts.googleapis.com/gstatic.com
# (@import de fuentes en style.css), tenor.com (iframe de preview de GIFs en
# la tab de gifs del dashboard), img-src ancho porque las imágenes salen de
# hosts variables según guild (avatares e emojis de Discord, GIFs de Giphy,
# el bucket R2 configurado por env var). El primer hash cubre el único
# inline handler que hay en todo el sitio (onerror="this.remove()" en los
# <img> del navbar/botones de invitar); el segundo cubre el <script> inline
# de redirect de idioma que solo vive en index.html; el tercero cubre el
# <script type="importmap"> inline que usan dashboard, perfil y estado --
# todos autorizados por hash exacto sin abrir 'unsafe-inline'. meta http-equiv NO soporta
# frame-ancestors/sandbox/report-uri -- la protección contra clickjacking
# para estas páginas va por X-Frame-Options: DENY, que sí pone nginx como
# cabecera real (ver DEPLOY.md); no hay una CSP con frame-ancestors a nivel
# nginx (a propósito: se pisaría con esta CSP y con la de la API, ver el
# comentario del add_header en DEPLOY.md).
def compute_landing_csp() -> str:
    imap_hash = import_map_hash()
    return (
        "default-src 'self'; "
        "script-src 'self' 'sha256-9f8ZK5epjuMsYtXFjPqrgJI0L4QOAUYmJdHtT+RSH/c=' "
        "'sha256-uHnzZdoBeA8QhQo9pAiIG4QTYLZ3o1hEppo4N8A6sio=' "
        f"'{imap_hash}'; "
        "style-src 'self' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com; "
        "img-src 'self' https: data:; "
        "frame-src https://tenor.com; "
        "connect-src 'self'; "
        "object-src 'none'; "
        "base-uri 'self'; "
        "form-action 'self'"
    )


LANDING_CSP = compute_landing_csp()

SHELL = (
    """<!DOCTYPE html>
<html lang="{lang}">
<head>
<meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="%s">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{full_title}</title>
<meta name="description" content="{meta}">
<meta name="theme-color" content="#13c4d8">

<!-- Open Graph / Link Previews (Discord, Twitter, Telegram, Slack, etc.) -->
<meta property="og:type" content="{og_type}">
<meta property="og:site_name" content="Purgito">
<meta property="og:url" content="{canonical_url}">
<meta property="og:title" content="{full_title}">
<meta property="og:description" content="{meta}">
<meta property="og:image" content="{og_image}">
<meta property="og:image:width" content="{og_image_width}">
<meta property="og:image:height" content="{og_image_height}">
<meta property="og:image:alt" content="{og_image_alt}">
<meta property="og:locale" content="{og_locale}">

<meta name="twitter:card" content="{twitter_card}">
<meta name="twitter:title" content="{full_title}">
<meta name="twitter:description" content="{meta}">
<meta name="twitter:image" content="{og_image}">

<link rel="canonical" href="{canonical_url}">
{hreflang}<link rel="icon" href="/assets/icon.png">
<link rel="stylesheet" href="/style.css">
{head}</head>
<body>

<div id="bg" class="bg-short" aria-hidden="true"></div>

<a class="skip" href="#contenido">{skip}</a>

{nav}

{body}

{footer}

<script src="/script.js"></script>
{scripts}</body>
</html>
"""
    % LANDING_CSP
)

SKIP_LABEL = {
    "es": "Saltar al contenido",
    "en": "Skip to content",
    "ru": "Перейти к содержимому",
    "ja": "コンテンツへスキップ",
    "de": "Zum Inhalt springen",
}


def hreflang_links(slug, lang):
    """Bloque de <link rel="alternate" hreflang> para cada idioma activo
    (LANGS) + x-default.

    x-default apunta siempre a la versión española: sigue siendo el idioma
    por defecto del sitio (ver el fallback 'es' en el redirect de índex.html).
    Solo ES↔EN tienen slugs propios (SLUG_MAP_ES_EN); ru/ja/de reutilizan el
    slug español tal cual -- mismo criterio que translateRest() en script.js,
    normalizar al slug canónico (el español) y de ahí retraducir al destino.
    """
    canonical = es_slug(slug) if lang == "en" else slug
    links = [
        '<link rel="alternate" hreflang="%s" href="%s/%s/%s">'
        % (lg, BASE_URL, lg, en_slug(canonical) if lg == "en" else canonical)
        for lg in LANGS
    ]
    links.append(
        '<link rel="alternate" hreflang="x-default" href="%s/es/%s">'
        % (BASE_URL, canonical)
    )
    return "\n".join(links) + "\n"


# Páginas del dashboard: el CSS propio va después de style.css (lo extiende, no
# lo reemplaza) y el módulo de entrada después de script.js, que es quien pinta
# la sesión en el navbar.
APP_HEAD = '<link rel="stylesheet" href="/dash.css">\n{importmap}'
APP_SCRIPT = '<script type="module" src="/js/{src}?v={v}"></script>\n'
# Páginas públicas con un módulo ES propio (ej. /es/estado) pero SIN dash.css:
# no son parte del dashboard, así que no necesitan su hoja de estilos, pero sí
# el importmap para que el cache-busting de Cloudflare alcance a lo que ese
# módulo importa (mismo motivo que las páginas "app" -- ver import_map()).
MODULE_HEAD = "{importmap}"


OG_LOCALE = {"es": "es_ES", "en": "en_US", "ru": "ru_RU", "ja": "ja_JP", "de": "de_DE"}
TOC_LABEL = {"es": "Índice", "en": "Index", "ru": "Оглавление", "ja": "目次", "de": "Inhalt"}
UPDATED_LABEL = {
    "es": "Última actualización",
    "en": "Last updated",
    "ru": "Последнее обновление",
    "ja": "最終更新日",
    "de": "Zuletzt aktualisiert",
}


def build_toc(sections, descs, lang="es"):
    if not sections:
        return ""
    rows = []
    for i, ((name, _), desc) in enumerate(zip(sections, descs), 1):
        rows.append(
            '      <li><a href="#seccion-%d"><span class="toc-t">%s</span>'
            '<span class="toc-d">%s</span></a></li>' % (i, html.escape(name), desc)
        )
    return (
        '  <nav class="box doc-toc" aria-labelledby="indice">\n'
        '    <h2 id="indice">%s</h2>\n'
        "    <ol>\n%s\n    </ol>\n  </nav>\n" % (TOC_LABEL[lang], "\n".join(rows))
    )


def build_page(page, nav, footer, lang="es"):
    title, date, intro, sections = parse((DOCS / page["src"]).read_text("utf-8"))
    descs = page["toc"]
    if len(descs) != len(sections):
        sys.exit(
            "%s: %d secciones en el markdown pero %d descripciones en PAGES"
            % (page["src"], len(sections), len(descs))
        )

    blocks = []
    for i, (name, body) in enumerate(sections, 1):
        blocks.append(
            '  <section class="box doc-sec" id="seccion-%d">\n'
            '    <h2 class="doc-sec-title">%s</h2>\n'
            '    <div class="doc-body">\n%s\n    </div>\n  </section>'
            % (i, html.escape(name), body)
        )

    body = (
        '<main id="contenido" class="doc wrap">\n'
        '  <header class="doc-head">\n'
        '    <h1 class="doc-title">%s</h1>\n'
        '    <p class="doc-date">%s: %s</p>\n'
        '    <div class="doc-body doc-intro">\n%s\n    </div>\n'
        "  </header>\n%s%s\n</main>"
        % (
            html.escape(title),
            UPDATED_LABEL[lang],
            html.escape(date),
            intro,
            build_toc(sections, descs, lang),
            "\n".join(blocks),
        )
    )
    full_title = f"{html.escape(page.get('title', title))} — Purgito"
    canonical_url = f"{BASE_URL}/{lang}/{page['slug']}"
    og_image = page.get("og_image") or get_default_og_image()
    return SHELL.format(
        lang=lang,
        skip=SKIP_LABEL[lang],
        full_title=full_title,
        meta=html.escape(page["meta"]),
        canonical_url=canonical_url,
        hreflang=hreflang_links(page["slug"], lang),
        og_type="article",
        og_image=og_image,
        og_image_width=page.get("og_image_width", DEFAULT_OG_IMAGE_WIDTH),
        og_image_height=page.get("og_image_height", DEFAULT_OG_IMAGE_HEIGHT),
        og_image_alt=page.get("og_image_alt", DEFAULT_OG_IMAGE_ALT),
        og_locale=OG_LOCALE[lang],
        twitter_card=page.get("twitter_card", DEFAULT_TWITTER_CARD),
        nav=nav,
        body=body,
        footer=footer,
        head="",
        scripts="",
    )


def build_html_page(page, nav, footer, lang="es"):
    """Página con cuerpo escrito a mano (landing/pages/*.html, landing/pages/en/*.html).

    Solo aporta el navbar, el footer y el <head> — el resto sale del archivo
    tal cual. Existe para que esas piezas no se dupliquen fuera de index.html
    (o index.en.html). Las que traen "app" suman además dash.css y su módulo
    de entrada; las que traen "module" suman el módulo pero NO dash.css
    (páginas públicas con su propio JS, ej. /es/estado, que no son parte del
    dashboard). Las que traen "doc" son de /{lang}/documentacion: se envuelven
    en el sidebar de doc_sidebar().
    """
    entry = page.get("app") or page.get("module")
    if page.get("app"):
        head = APP_HEAD.format(importmap=import_map())
    elif page.get("module"):
        head = MODULE_HEAD.format(importmap=import_map())
    else:
        head = ""
    raw_body = (LANDING / "pages" / page["src"]).read_text("utf-8").strip()
    if page.get("doc"):
        raw_body = (
            '<div class="docs-shell wrap">\n%s\n'
            '  <main id="contenido" class="docs-content">\n%s\n  </main>\n</div>'
            % (doc_sidebar(page["slug"], lang), raw_body)
        )
    elif page.get("guia"):
        raw_body = (
            '<div class="docs-shell wrap">\n%s\n'
            '  <main id="contenido" class="docs-content guia-content">\n%s\n  </main>\n</div>'
            % (guia_sidebar(lang), raw_body)
        )
    full_title = f"{html.escape(page['title'])} — Purgito"
    canonical_url = f"{BASE_URL}/{lang}/{page['slug']}"
    og_image = page.get("og_image") or get_default_og_image()
    og_type = "article" if (page.get("doc") or page.get("guia")) else "website"
    return SHELL.format(
        lang=lang,
        skip=SKIP_LABEL[lang],
        full_title=full_title,
        meta=html.escape(page["meta"]),
        canonical_url=canonical_url,
        hreflang=hreflang_links(page["slug"], lang),
        og_type=og_type,
        og_image=og_image,
        og_image_width=page.get("og_image_width", DEFAULT_OG_IMAGE_WIDTH),
        og_image_height=page.get("og_image_height", DEFAULT_OG_IMAGE_HEIGHT),
        og_image_alt=page.get("og_image_alt", DEFAULT_OG_IMAGE_ALT),
        og_locale=OG_LOCALE[lang],
        twitter_card=page.get("twitter_card", DEFAULT_TWITTER_CARD),
        nav=nav,
        body=raw_body,
        footer="" if page.get("no_footer") else footer,
        head=head,
        scripts=APP_SCRIPT.format(src=entry, v=js_files()[0]) if entry else "",
    )


# ── cache-busting ────────────────────────────────────────────────────────────

# Cloudflare cachea .css/.js 4 h por default (el HTML no), así que un deploy
# deja los assets viejos servidos hasta que alguien purgue a mano. El hash del
# contenido en el query string hace que cada cambio sea una URL nueva.
ASSETS = ("style.css", "script.js", "dash.css")


def stamp(page_html):
    """`/style.css` → `/style.css?v=<hash8>`, con el hash del archivo real.

    También resella la URL de og-purgito.png con su hash SHA-256 para que Discord
    y otros scrapers de Open Graph no retengan versiones antiguas en su proxy.

    Idempotente: un `?v=` viejo se reemplaza en vez de acumularse. Hash del
    contenido y no mtime, que cambia en cada clone y ensuciaría el diff.
    """
    for name in ASSETS:
        digest = hashlib.sha256((LANDING / name).read_bytes()).hexdigest()[:8]
        page_html = re.sub(
            r'(?<=["\'])/%s(?:\?v=[0-9a-f]+)?(?=["\'])' % re.escape(name),
            "/%s?v=%s" % (name, digest),
            page_html,
        )
    og_digest = og_image_digest()
    page_html = re.sub(
        r"(https://purgito\.app/assets/og-purgito\.png)(?:\?v=[0-9a-f]+)?",
        f"https://purgito.app/assets/og-purgito.png?v={og_digest}",
        page_html,
    )
    page_html = re.sub(
        r'<meta http-equiv="Content-Security-Policy" content="[^"]*">',
        f'<meta http-equiv="Content-Security-Policy" content="{LANDING_CSP}">',
        page_html,
    )
    return page_html


def chunk_of(src, pattern):
    m = re.search(pattern, src, re.S)
    if not m:
        sys.exit("no encontré %r en index.html" % pattern)
    return m.group(0)


INDEX_FILE = {
    "es": "index.html",
    "en": "index.en.html",
    "ru": "index.ru.html",
    "ja": "index.ja.html",
    "de": "index.de.html",
}
PAGES_BY_LANG = {
    "es": PAGES,
    "en": PAGES_EN,
    "ru": PAGES_RU,
    "ja": PAGES_JA,
    "de": PAGES_DE,
}
HTML_PAGES_BY_LANG = {
    "es": HTML_PAGES,
    "en": HTML_PAGES_EN,
    "ru": HTML_PAGES_RU,
    "ja": HTML_PAGES_JA,
    "de": HTML_PAGES_DE,
}


def main():
    check = "--check" in sys.argv

    for lang in LANGS:
        index_path = LANDING / INDEX_FILE[lang]
        index = index_path.read_text("utf-8")
        nav = chunk_of(index, r'<nav class="nav" id="top">.*?\n</nav>')
        footer = chunk_of(index, r'<footer class="footer">.*?</footer>')

        # index.html / index.en.html se escriben a mano: no se regeneran,
        # solo se les resella el ?v=.
        stamped_index = stamp(index)
        if stamped_index != index:
            if check:
                sys.exit(
                    "%s tiene el ?v= desactualizado — corre build_docs.py" % index_path
                )
            index_path.write_text(stamped_index, "utf-8")
            print("→", index_path.relative_to(ROOT))

        # Para "es", nginx cae en la raíz /index.html tanto para "/" como para
        # "/es/" (try_files sin match -> /index.html, ver DEPLOY.md), así que
        # alcanza con el archivo de la raíz. Para cualquier otro idioma ese
        # mismo fallback serviría la home en español -- hace falta un
        # {lang}/index.html real para que try_files lo encuentre antes de
        # caer al fallback español.
        if lang != "es":
            copy_out = LANDING / lang / "index.html"
            if check:
                if (
                    not copy_out.exists()
                    or copy_out.read_text("utf-8") != stamped_index
                ):
                    sys.exit("%s está desactualizado — corre build_docs.py" % copy_out)
            else:
                copy_out.parent.mkdir(parents=True, exist_ok=True)
                copy_out.write_text(stamped_index, "utf-8")
                print("→", copy_out.relative_to(ROOT))

        todo = [(p, build_page) for p in PAGES_BY_LANG[lang]] + [
            (p, build_html_page) for p in HTML_PAGES_BY_LANG[lang]
        ]
        for page, build in todo:
            out = LANDING / lang / page["slug"] / "index.html"
            page_html = stamp(build(page, nav, footer, lang))
            if check:
                if not out.exists() or out.read_text("utf-8") != page_html:
                    sys.exit("%s está desactualizado — corre build_docs.py" % out)
            else:
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_text(page_html, "utf-8")
                print("→", out.relative_to(ROOT))

    # Cada idioma en *_BY_LANG tiene que traer exactamente las mismas páginas
    # que "es" -- si esto falla, alguien agregó una página a un lado sin el
    # resto (incluye ru/ja/de el día que se sumen a estos dicts).
    for lang, pages in PAGES_BY_LANG.items():
        assert len(pages) == len(PAGES), (lang, len(pages), len(PAGES))
    for lang, pages in HTML_PAGES_BY_LANG.items():
        assert len(pages) == len(HTML_PAGES), (lang, len(pages), len(HTML_PAGES))
    for lang, sections in DOC_SECTIONS_BY_LANG.items():
        assert len(sections) == len(DOC_SECTIONS), (lang, len(sections))
    for lang, sections in GUIA_SECTIONS_BY_LANG.items():
        assert len(sections) == len(GUIA_SECTIONS), (lang, len(sections))
    # SLUG_MAP_ES_EN tiene que ser reversible en ambos sentidos.
    for es, en in SLUG_MAP_ES_EN.items():
        assert es_slug(en) == es, (es, en)
        assert en_slug(es) == en, (es, en)

    # Self-check del parser: el formato de docs/*.md es la única entrada, así
    # que si cambia (o el convertidor se rompe) esto falla acá y no en prod.
    title, date, intro, sections = parse((DOCS / "TERMS.md").read_text("utf-8"))
    assert title == "Condiciones del Servicio (Terms of Service)", title
    assert date == "15 de agosto de 2026", date
    assert "<p>" in intro and "Última actualización" not in intro, intro
    assert len(sections) == 8, len(sections)
    assert sections[0][0] == "1. Uso Aceptable"
    assert "<h3>Reembolsos</h3>" in sections[3][1]
    assert len(parse((DOCS / "PRIVACY.md").read_text("utf-8"))[3]) == 9
    # REFUNDS no tiene `# N.`: sus `## ` son las secciones.
    refunds = parse((DOCS / "REFUNDS.md").read_text("utf-8"))
    assert refunds[0] == "Políticas de reembolsos", refunds[0]
    assert refunds[1] == "2 de agosto de 2026", refunds[1]
    assert len(refunds[3]) == 6, len(refunds[3])
    assert refunds[3][0][0] == "Prueba gratuita (trial)", refunds[3][0][0]
    assert "<h3>" not in refunds[3][0][1], refunds[3][0][1]
    assert render("- uno\n  sigue") == "<ul><li>uno sigue</li></ul>", render(
        "- uno\n  sigue"
    )
    assert render("- uno\n- dos") == "<ul><li>uno</li><li>dos</li></ul>", render(
        "- uno\n- dos"
    )
    assert render("a\nb") == "<p>a b</p>", render("a\nb")
    assert '<a href="x" target="_blank" rel="noopener">t</a>' in inline("[t](x)")
    assert inline("a & <b>") == "a &amp; &lt;b&gt;", inline("a & <b>")
    # El sellado tiene que ser idempotente: sin esto, cada corrida encadenaría
    # otro ?v= y el HTML nunca convergería.
    once = stamp(
        '<link href="/style.css"><script src="/script.js"></script><meta property="og:image" content="https://purgito.app/assets/og-purgito.png">'
    )
    assert re.search(r'/style\.css\?v=[0-9a-f]{8}"', once), once
    assert re.search(r'/script\.js\?v=[0-9a-f]{8}"', once), once
    assert re.search(
        r'https://purgito\.app/assets/og-purgito\.png\?v=[0-9a-f]{8}"', once
    ), once
    assert stamp(once) == once, once
    assert stamp("<p>style.css sin barra</p>") == "<p>style.css sin barra</p>"
    print("ok")


if __name__ == "__main__":
    main()
