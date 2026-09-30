"""S3 falso en memoria con varios buckets, para los tests de R2.

Guarda qué bucket toca cada operación (`calls`), que es lo que importa
comprobar: que un GIF nunca caiga en el bucket de imágenes, que un backup
nunca salga del suyo, que la migración no borre nada. Los errores son
ClientError de verdad, con la misma forma que los de boto3.
"""

import hashlib
import io
from datetime import datetime, timezone

from botocore.exceptions import ClientError


def _not_found(op: str, code: str = "404") -> ClientError:
    return ClientError(
        {
            "Error": {"Code": code, "Message": "no existe"},
            "ResponseMetadata": {"HTTPStatusCode": 404},
        },
        op,
    )


class _Paginator:
    def __init__(self, s3):
        self._s3 = s3

    def paginate(self, Bucket, Prefix=""):
        objects = self._s3._bucket(Bucket, "ListObjectsV2")
        contents = [
            {
                "Key": key,
                "Size": len(obj["Body"]),
                "LastModified": obj["LastModified"],
            }
            for key, obj in sorted(objects.items())
            if key.startswith(Prefix)
        ]
        # Dos páginas a propósito: el código real tiene que paginar.
        half = max(1, len(contents) // 2)
        yield {"Contents": contents[:half]}
        if contents[half:]:
            yield {"Contents": contents[half:]}


class FakeS3:
    def __init__(self, *buckets: str):
        self.buckets: dict[str, dict[str, dict]] = {name: {} for name in buckets}
        self.calls: list[tuple[str, str, str | None]] = []
        self.fail_put = False

    # ── helpers de los tests ────────────────────────────────────────────────
    def seed(self, bucket: str, key: str, body: bytes = b"x", **meta) -> None:
        """Deja un objeto ya puesto, sin registrar una llamada."""
        self.buckets[bucket][key] = {
            "Body": body,
            "LastModified": datetime(2026, 1, 1, tzinfo=timezone.utc),
            "Metadata": meta.pop("Metadata", {}),
            **meta,
        }

    def ops(self, *names: str) -> list[tuple[str, str, str | None]]:
        return [c for c in self.calls if c[0] in names]

    def keys(self, bucket: str) -> set[str]:
        return set(self.buckets[bucket])

    # ── API de boto3 ────────────────────────────────────────────────────────
    def _bucket(self, name: str, op: str) -> dict:
        if name not in self.buckets:
            raise _not_found(op, "NoSuchBucket")
        return self.buckets[name]

    def head_bucket(self, Bucket):
        self.calls.append(("head_bucket", Bucket, None))
        self._bucket(Bucket, "HeadBucket")
        return {}

    def put_object(self, Bucket, Key, Body, **kw):
        self.calls.append(("put_object", Bucket, Key))
        if self.fail_put:
            raise ClientError(
                {"Error": {"Code": "500", "Message": "boom"}}, "PutObject"
            )
        self._bucket(Bucket, "PutObject")[Key] = {
            "Body": bytes(Body),
            "LastModified": datetime.now(timezone.utc),
            "Metadata": dict(kw.pop("Metadata", {}) or {}),
            **kw,
        }
        return {}

    def _obj(self, Bucket, Key, op):
        obj = self._bucket(Bucket, op).get(Key)
        if obj is None:
            raise _not_found(op)
        return obj

    def head_object(self, Bucket, Key):
        self.calls.append(("head_object", Bucket, Key))
        obj = self._obj(Bucket, Key, "HeadObject")
        head = {
            "ContentLength": len(obj["Body"]),
            "ETag": f'"{hashlib.md5(obj["Body"]).hexdigest()}"',
            "Metadata": dict(obj["Metadata"]),
        }
        for field in (
            "ContentType",
            "CacheControl",
            "ContentDisposition",
            "ContentEncoding",
            "ContentLanguage",
        ):
            if obj.get(field):
                head[field] = obj[field]
        return head

    def get_object(self, Bucket, Key):
        self.calls.append(("get_object", Bucket, Key))
        obj = self._obj(Bucket, Key, "GetObject")
        return {"Body": io.BytesIO(obj["Body"]), "Metadata": dict(obj["Metadata"])}

    def delete_object(self, Bucket, Key):
        self.calls.append(("delete_object", Bucket, Key))
        self._bucket(Bucket, "DeleteObject").pop(Key, None)
        return {}

    def copy_object(self, Bucket, Key, CopySource, MetadataDirective="COPY", **kw):
        self.calls.append(("copy_object", Bucket, Key))
        src = self._obj(CopySource["Bucket"], CopySource["Key"], "CopyObject")
        copied = dict(src)
        if MetadataDirective == "REPLACE":
            for field in (
                "ContentType",
                "CacheControl",
                "ContentDisposition",
                "ContentEncoding",
                "ContentLanguage",
            ):
                copied.pop(field, None)
            copied.update(kw)
            copied["Metadata"] = dict(kw.get("Metadata") or {})
        self._bucket(Bucket, "CopyObject")[Key] = copied
        return {}

    def get_paginator(self, name):
        assert name == "list_objects_v2"
        return _Paginator(self)
