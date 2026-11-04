# Solo pruebas: no ejecuta el bot ni incluye secretos o datos del checkout.
FROM postgres:18 AS pgtools
RUN mkdir /tools && cp /usr/lib/postgresql/18/bin/pg_dump /usr/lib/postgresql/18/bin/pg_restore /tools/ \
    && find /usr/lib -name libpq.so.5 -exec cp -L '{}' /tools/libpq.so.5 ';'

FROM python:3.14-slim
RUN apt-get update && apt-get install -y --no-install-recommends \
    libldap2 libgssapi-krb5-2 libzstd1 liblz4-1 libxxhash0 \
    && rm -rf /var/lib/apt/lists/*
COPY --from=pgtools /tools/pg_dump /tools/pg_restore /usr/local/bin/
COPY --from=pgtools /tools/libpq.so.5 /usr/local/lib/
RUN ldconfig && pg_dump --version
COPY requirements.txt /tmp/purgito-requirements.txt
RUN pip install --no-cache-dir -r /tmp/purgito-requirements.txt pytest==9.1.1 ruff==0.15.8
WORKDIR /work
USER 1000:1000
ENV HOME=/tmp
CMD ["python", "-m", "pytest", "tests", "-q"]
