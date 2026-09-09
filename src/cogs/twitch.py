"""Notificaciones de Twitch: avisa cuando un canal empieza una transmisión en
vivo. A diferencia de YouTube (RSS público, sin credenciales), Twitch exige
una app registrada (TWITCH_CLIENT_ID/TWITCH_CLIENT_SECRET en .env, ver
.env.example) -- si no están configuradas, la feature queda desactivada por
completo sin romper el resto del bot (mismo criterio que GROQ_API_KEY)."""

import asyncio
import logging
import re
import time

import discord
import requests
from discord.ext import commands, tasks

import config
from db import (
    TWITCH_ERROR_CHANNEL_NOT_FOUND,
    TWITCH_ERROR_NO_PERMISSION,
    get_all_twitch_subs,
    set_twitch_sub_error,
    update_last_stream_id,
)
from i18n import guild_locale, t

log = logging.getLogger(__name__)

_HELIX_URL = "https://api.twitch.tv/helix"
_LOGIN_RE = re.compile(r"^[a-z0-9_]{4,25}$")


class TwitchNotConfigured(Exception):
    """TWITCH_CLIENT_ID/TWITCH_CLIENT_SECRET no configuradas -- ver .env.example."""


def is_configured() -> bool:
    return bool(config.TWITCH_CLIENT_ID and config.TWITCH_CLIENT_SECRET)


# Cache del app access token (client_credentials): un solo token compartido
# por todo el proceso, no por guild -- es una credencial de la app, no del
# usuario. Se renueva 5 min antes de que Twitch lo dé por vencido.
_token_cache: dict = {"token": None, "expires_at": 0.0}


async def _get_app_token() -> str:
    if not is_configured():
        raise TwitchNotConfigured()
    now = time.monotonic()
    if _token_cache["token"] and now < _token_cache["expires_at"]:
        return _token_cache["token"]

    def _fetch():
        resp = requests.post(
            "https://id.twitch.tv/oauth2/token",
            data={
                "client_id": config.TWITCH_CLIENT_ID,
                "client_secret": config.TWITCH_CLIENT_SECRET,
                "grant_type": "client_credentials",
            },
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()

    data = await asyncio.to_thread(_fetch)
    _token_cache["token"] = data["access_token"]
    _token_cache["expires_at"] = now + max(data.get("expires_in", 3600) - 300, 60)
    return _token_cache["token"]


def _auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", "Client-Id": config.TWITCH_CLIENT_ID}


def _normalize_login(raw: str) -> str | None:
    """Acepta login crudo, URL completa (twitch.tv/<login>) o con @ adelante."""
    s = (raw or "").strip()
    if not s:
        return None
    m = re.search(r"twitch\.tv/([A-Za-z0-9_]+)", s)
    login = m.group(1) if m else s.lstrip("@").split("/")[0].split("?")[0].strip()
    login = login.lower()
    return login if _LOGIN_RE.match(login) else None


async def resolve_twitch_channel(raw: str) -> dict | None:
    """Valida que el canal exista y devuelve {id, login, display_name}. None
    si el canal no existe o el login es inválido. Levanta TwitchNotConfigured
    si el bot no tiene credenciales de Twitch (ver .env.example) -- el caller
    debe distinguir ese caso de "canal no encontrado" para no confundir al
    admin con un mensaje que sugiere revisar el nombre cuando el problema es
    de configuración del bot."""
    if not is_configured():
        raise TwitchNotConfigured()
    login = _normalize_login(raw)
    if not login:
        return None

    token = await _get_app_token()

    def _fetch():
        resp = requests.get(
            f"{_HELIX_URL}/users",
            params={"login": login},
            headers=_auth_headers(token),
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()

    try:
        data = await asyncio.to_thread(_fetch)
    except Exception:
        log.exception("Error resolviendo canal de Twitch %s", raw)
        return None

    users = data.get("data") or []
    if not users:
        return None
    user = users[0]
    return {
        "id": user["id"],
        "login": user["login"],
        "display_name": user.get("display_name") or user["login"],
    }


async def get_live_streams(twitch_user_ids: list[str]) -> dict[str, dict]:
    """id_usuario_twitch -> {id, title, game_name, url} para los que están EN
    VIVO ahora mismo -- Helix simplemente omite del resultado a los que no lo
    están, no hay un flag "offline" que leer. Batchea de a 100 (límite de
    Twitch para el parámetro user_id repetido en un solo request)."""
    if not twitch_user_ids:
        return {}
    token = await _get_app_token()
    result: dict[str, dict] = {}
    for i in range(0, len(twitch_user_ids), 100):
        batch = twitch_user_ids[i : i + 100]

        def _fetch(batch=batch):
            resp = requests.get(
                f"{_HELIX_URL}/streams",
                params=[("user_id", uid) for uid in batch],
                headers=_auth_headers(token),
                timeout=10,
            )
            resp.raise_for_status()
            return resp.json()

        data = await asyncio.to_thread(_fetch)
        for item in data.get("data") or []:
            result[item["user_id"]] = {
                "id": item["id"],
                "title": item.get("title", ""),
                "game_name": item.get("game_name", ""),
                "url": f"https://twitch.tv/{item.get('user_login', '')}",
            }
    return result


class Twitch(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self) -> None:
        if is_configured():
            self.check_twitch.start()
        else:
            log.warning(
                "TWITCH_CLIENT_ID/TWITCH_CLIENT_SECRET no configuradas: "
                "notificaciones de Twitch desactivadas."
            )

    async def cog_unload(self) -> None:
        if self.check_twitch.is_running():
            self.check_twitch.cancel()

    @tasks.loop(minutes=3)
    async def check_twitch(self):
        subs = await get_all_twitch_subs()
        if not subs:
            return

        try:
            live = await get_live_streams([s["twitch_user_id"] for s in subs])
        except Exception:
            log.exception("Error consultando streams en vivo de Twitch")
            return

        async def _check_one(sub: dict) -> None:
            try:
                channel = self.bot.get_channel(sub["discord_channel_id"])
                if channel is None:
                    error = TWITCH_ERROR_CHANNEL_NOT_FOUND
                elif (
                    not isinstance(channel, discord.TextChannel)
                    or not channel.permissions_for(channel.guild.me).send_messages
                ):
                    error = TWITCH_ERROR_NO_PERMISSION
                else:
                    error = None

                if error:
                    if sub["last_error"] != error:
                        log.warning(
                            "Suscripción Twitch %s (guild %s) no puede avisar: %s",
                            sub["twitch_login"],
                            sub["guild_id"],
                            error,
                        )
                        await set_twitch_sub_error(
                            sub["guild_id"], sub["twitch_user_id"], error
                        )
                    return

                if sub["last_error"]:
                    await set_twitch_sub_error(
                        sub["guild_id"], sub["twitch_user_id"], None
                    )
                    log.info(
                        "Suscripción Twitch %s (guild %s) recuperada, reanuda avisos",
                        sub["twitch_login"],
                        sub["guild_id"],
                    )

                stream = live.get(sub["twitch_user_id"])
                if stream is None:
                    return
                if stream["id"] != sub["last_stream_id"]:
                    role_id = sub.get("mention_role_id")
                    mention = f"<@&{role_id}> " if role_id else ""
                    locale = await guild_locale(sub["guild_id"])
                    await channel.send(
                        mention
                        + t(
                            "twitch.now_live",
                            locale,
                            login=sub["twitch_login"],
                            title=stream["title"],
                            url=stream["url"],
                        ),
                        # Mismo motivo que youtube.new_video: el título del
                        # stream lo escribe la persona en vivo, no el
                        # servidor -- solo se permite el rol que el admin
                        # configuró como aviso.
                        allowed_mentions=discord.AllowedMentions(
                            everyone=False,
                            users=False,
                            roles=[discord.Object(id=role_id)] if role_id else False,
                        ),
                    )
                    await update_last_stream_id(
                        sub["guild_id"], sub["twitch_user_id"], stream["id"]
                    )
            except Exception:
                log.exception(
                    "Error procesando suscripción Twitch %s", sub["twitch_login"]
                )

        await asyncio.gather(*(_check_one(sub) for sub in subs))

    @check_twitch.before_loop
    async def _wait_ready(self):
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Twitch(bot))
