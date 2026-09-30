import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "src"))

_R2_ENV_VARS = (
    "R2_ACCESS_KEY_ID",
    "R2_SECRET_ACCESS_KEY",
    "R2_ENDPOINT_URL",
    "R2_IMAGES_BUCKET",
    "R2_IMAGES_PUBLIC_URL",
    "R2_GIFS_BUCKET",
    "R2_GIFS_PUBLIC_URL",
    "R2_BACKUP_BUCKET",
    # Esquema viejo de un solo bucket: lo lee el fallback transitorio de r2.py.
    "R2_BUCKET_NAME",
    "R2_PUBLIC_URL",
)


@pytest.fixture(autouse=True)
def _r2_env_aislado(monkeypatch):
    """Ningún test hereda la configuración de R2 del .env de quien lo corre
    (importar `config` ejecuta load_dotenv): cada test que necesite un bucket
    lo declara con monkeypatch.setenv. El cliente cacheado también se descarta,
    para que uno creado con las credenciales de un test no pase al siguiente."""
    for name in _R2_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    import r2

    monkeypatch.setattr(r2, "_client", None)
    monkeypatch.setattr(r2, "_checked", False)
