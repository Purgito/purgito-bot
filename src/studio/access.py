"""Verificación del JWT de Cloudflare Access para el acceso remoto a Studio.

Cloudflare Access firma (RS256) un JWT por sesión y lo añade a cada petición en la cabecera
``Cf-Access-Jwt-Assertion``. Una cabecera de identidad (``Cf-Access-Authenticated-User-Email``) NO se
usa nunca: cualquier cliente puede escribirla. Aquí solo se confía en un JWT cuya firma verifica con las
claves públicas de *nuestro* equipo de Access y cuyo ``aud`` es *esta* aplicación.

Sin dependencias nuevas: la firma se comprueba con ``cryptography`` (ya está en requirements.txt).
Falla cerrado: cualquier irregularidad levanta ``AccessDenied`` con un código corto (sin eco del token).
"""

import asyncio
import base64
import json
import logging
import re
import time

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa

_TEAM = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}\.cloudflareaccess\.com$")
_HOST = re.compile(r"^(?=.{4,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,}$")
_AUD = re.compile(r"^[0-9a-f]{64}$")
_EMAIL = re.compile(r"^[^@\s,;<>]{1,64}@[^@\s,;<>]{1,255}$")
MAX_TOKEN = 8192

log = logging.getLogger("studio.access")


class AccessDenied(Exception):
    """Motivo de rechazo como código corto; nunca incluye contenido del token."""

    def __init__(self, code):
        super().__init__(code)
        self.code = code


class AccessSettings:
    """Configuración del acceso remoto. Todo o nada: una configuración a medias es un error."""

    def __init__(self, team, audience, host, emails):
        self.team, self.audience, self.host, self.emails = team, audience, host, emails

    @classmethod
    def from_env(cls, environ):
        names = {
            "team": "STUDIO_ACCESS_TEAM",
            "audience": "STUDIO_ACCESS_AUD",
            "host": "STUDIO_PUBLIC_HOST",
            "emails": "STUDIO_ACCESS_EMAILS",
        }
        values = {key: (environ.get(name) or "").strip() for key, name in names.items()}
        if not any(values.values()):
            return None  # acceso remoto desactivado: solo el acceso local con token
        missing = [names[k] for k, v in values.items() if not v]
        if missing:
            raise ValueError(
                "Acceso remoto a medias: faltan "
                + ", ".join(missing)
                + ". Define las cuatro o ninguna."
            )
        team = values["team"].lower()
        host = values["host"].lower()
        emails = frozenset(
            e.strip().lower() for e in values["emails"].split(",") if e.strip()
        )
        if not _TEAM.fullmatch(team):
            raise ValueError(
                "STUDIO_ACCESS_TEAM debe ser <equipo>.cloudflareaccess.com"
            )
        if not _HOST.fullmatch(host) or host.endswith(".cloudflareaccess.com"):
            raise ValueError(
                "STUDIO_PUBLIC_HOST debe ser un nombre de host (p. ej. studio.purgito.app)"
            )
        if not _AUD.fullmatch(values["audience"]):
            raise ValueError(
                "STUDIO_ACCESS_AUD debe ser la etiqueta AUD de 64 hex de la aplicación"
            )
        if not emails or not all(_EMAIL.fullmatch(e) for e in emails):
            raise ValueError(
                "STUDIO_ACCESS_EMAILS debe listar al menos un correo válido, separados por coma"
            )
        return cls(team, values["audience"], host, emails)


def _b64(segment):
    if not re.fullmatch(r"[A-Za-z0-9_-]+", segment or ""):
        raise AccessDenied("malformed")
    return base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4))


def _json(segment):
    try:
        value = json.loads(_b64(segment))
    except (ValueError, UnicodeDecodeError):
        raise AccessDenied("malformed") from None
    if not isinstance(value, dict):
        raise AccessDenied("malformed")
    return value


def public_key(jwk):
    if jwk.get("kty") != "RSA":
        return None
    try:
        n = int.from_bytes(_b64(jwk["n"]), "big")
        e = int.from_bytes(_b64(jwk["e"]), "big")
        if n.bit_length() < 2048:
            return None
        return rsa.RSAPublicNumbers(e, n).public_key()
    except (KeyError, AccessDenied, ValueError):
        return None


async def fetch_jwks(team):
    """Claves públicas del equipo de Access. HTTPS con verificación, tamaño y tiempo acotados."""
    import aiohttp

    url = f"https://{team}/cdn-cgi/access/certs"
    timeout = aiohttp.ClientTimeout(total=5)
    async with aiohttp.ClientSession(timeout=timeout, trust_env=False) as client:
        async with client.get(url, allow_redirects=False) as res:
            if res.status != 200:
                log.warning(
                    "studio.access claves: el equipo respondió HTTP %s", res.status
                )
                raise AccessDenied("keys-unavailable")
            body = await res.content.read(65537)
            if len(body) > 65536:
                raise AccessDenied("keys-unavailable")
            return json.loads(body)


class AccessVerifier:
    def __init__(
        self,
        settings,
        fetch_keys=None,
        *,
        clock=time.time,
        leeway=30,
        key_ttl=3600,
        refetch_min=300,
        failure_backoff=10,
        max_stale=86400,
        retry_delay=0.5,
    ):
        self.s = settings
        self._fetch = fetch_keys or (lambda: fetch_jwks(settings.team))
        self._clock, self._leeway = clock, leeway
        self._ttl, self._refetch_min = key_ttl, refetch_min
        self._backoff, self._max_stale, self._retry_delay = (
            failure_backoff,
            max_stale,
            retry_delay,
        )
        self._keys, self._loaded, self._tried = {}, 0.0, 0.0
        self._next_try = (
            0.0  # tras un fallo de descarga: cuándo se puede volver a intentar
        )
        self._lock = asyncio.Lock()

    async def _download(self):
        """Claves descargadas y legibles, o None si la descarga falla (dos intentos)."""
        for attempt in (1, 2):
            try:
                jwks = await self._fetch()
            except Exception as exc:  # incluye AccessDenied del propio descargador
                log.warning(
                    "studio.access claves no disponibles (intento %s): %s",
                    attempt,
                    type(exc).__name__,
                )
                if attempt == 1 and self._retry_delay:
                    await asyncio.sleep(self._retry_delay)
                continue
            keys = {}
            for jwk in (jwks or {}).get("keys", []) if isinstance(jwks, dict) else []:
                key = public_key(jwk) if isinstance(jwk, dict) else None
                if key is not None and isinstance(jwk.get("kid"), str):
                    keys[jwk["kid"]] = key
            return keys
        return None

    async def preload(self):
        """Descarga las claves al arrancar para que el primer login no dependa de ello."""
        async with self._lock:
            now = self._clock()
            self._tried = now
            keys = await self._download()
            if keys:
                self._keys, self._loaded = keys, now
                log.info("studio.access claves de Access cargadas (%s)", len(keys))
            else:
                self._next_try = now + self._backoff

    async def _key(self, kid):
        now = self._clock()
        if kid in self._keys and now - self._loaded < self._ttl:
            return self._keys[kid]
        async with self._lock:
            now = self._clock()
            stale = now - self._loaded >= self._ttl
            # Con claves válidas, un kid desconocido no puede forzar una descarga por petición.
            # Sin claves (o caducadas), tras un fallo se reintenta a los pocos segundos.
            usable = bool(self._keys) and not stale
            window = self._tried + self._refetch_min if usable else self._next_try
            if (stale or kid not in self._keys) and now >= window:
                self._tried = now
                keys = await self._download()
                if keys:
                    self._keys, self._loaded = keys, now
                elif keys is None:
                    self._next_try = now + self._backoff
                    # Una renovación fallida no tira el acceso: las claves anteriores siguen
                    # valiendo un tiempo acotado (Cloudflare no retira una clave de golpe).
                    if not (kid in self._keys and now - self._loaded < self._max_stale):
                        raise AccessDenied("keys-unavailable")
                else:
                    self._next_try = now + self._backoff
            elif stale and now - self._loaded >= self._max_stale:
                raise AccessDenied("keys-unavailable")
            if kid not in self._keys:
                raise AccessDenied("kid")
            return self._keys[kid]

    async def verify(self, token):
        """Devuelve las claims si el token es auténtico, vigente, de esta aplicación y de una persona autorizada."""
        if not isinstance(token, str) or not token:
            raise AccessDenied("missing")
        if len(token) > MAX_TOKEN:
            raise AccessDenied("malformed")
        parts = token.split(".")
        if len(parts) != 3:
            raise AccessDenied("malformed")
        header, claims = _json(parts[0]), _json(parts[1])
        # Solo RS256: rechaza "none" y la confusión RS256/HS256 sin siquiera mirar la firma.
        if header.get("alg") != "RS256":
            raise AccessDenied("alg")
        kid = header.get("kid")
        if not isinstance(kid, str):
            raise AccessDenied("kid")
        key = await self._key(kid)
        try:
            key.verify(
                _b64(parts[2]),
                f"{parts[0]}.{parts[1]}".encode("ascii"),
                padding.PKCS1v15(),
                hashes.SHA256(),
            )
        except InvalidSignature:
            raise AccessDenied("signature") from None
        now = self._clock()
        if claims.get("iss") != f"https://{self.s.team}":
            raise AccessDenied("iss")
        aud = claims.get("aud")
        if self.s.audience not in (aud if isinstance(aud, list) else [aud]):
            raise AccessDenied("aud")
        exp = claims.get("exp")
        if (
            not isinstance(exp, (int, float))
            or isinstance(exp, bool)
            or exp < now - self._leeway
        ):
            raise AccessDenied("exp")
        for name in ("nbf", "iat"):
            value = claims.get(name)
            if value is not None and (
                not isinstance(value, (int, float))
                or isinstance(value, bool)
                or value > now + self._leeway
            ):
                raise AccessDenied(name)
        email = claims.get("email")
        if not isinstance(email, str) or email.strip().lower() not in self.s.emails:
            raise AccessDenied("email")
        return {**claims, "email": email.strip().lower()}
