FROM python:3.12-slim AS builder
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 PYTHONDONTWRITEBYTECODE=1
RUN python -m venv /opt/venv
COPY requirements.txt /tmp/requirements.txt
RUN /opt/venv/bin/pip install --no-cache-dir -r /tmp/requirements.txt

FROM python:3.12-slim AS runtime
ENV PATH="/opt/venv/bin:$PATH" PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=10000
RUN useradd --uid 10001 --no-create-home app
WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
COPY --chown=10001:10001 config config
COPY --chown=10001:10001 tracker tracker
COPY --chown=10001:10001 ops ops
COPY --chown=10001:10001 templates templates
COPY --chown=10001:10001 static static
COPY --chown=10001:10001 manage.py requirements.txt ./
RUN DEBUG=1 python manage.py collectstatic --noinput && chown -R 10001:10001 /app
USER 10001:10001
EXPOSE 10000
CMD ["python","ops/start.py"]
