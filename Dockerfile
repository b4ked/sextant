# SILO engine image. CPU-only; no GPU runtime required.
#
#   docker build -t silo .
#   docker run --rm -v silo-home:/data silo models pull          # needs network, once
#   docker run --rm --network none -v silo-home:/data -v /path/to/docs:/docs:ro \
#       silo index /docs                                            # no network at all
#   docker run --rm -p 127.0.0.1:8321:8321 -v silo-home:/data -v /path/to/docs:/docs:ro \
#       silo serve --host 0.0.0.0
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /usr/local/bin/uv
RUN apt-get update && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never UV_NO_CACHE=1 \
    SILO_HOME=/data PATH="/app/.venv/bin:$PATH"
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
RUN uv sync --frozen --no-dev
RUN useradd --create-home silo && mkdir /data && chown silo /data
USER silo
VOLUME /data
EXPOSE 8321
ENTRYPOINT ["silo"]
CMD ["serve", "--host", "0.0.0.0"]
