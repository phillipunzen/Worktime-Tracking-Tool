FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    FLASK_APP=wsgi.py \
    INSTANCE_PATH=/app/instance

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY app ./app
COPY wsgi.py docker-entrypoint.sh ./

RUN chmod +x docker-entrypoint.sh \
    && useradd --create-home --uid 1000 zeiterfassung \
    && mkdir -p /app/instance \
    && chown -R zeiterfassung /app/instance

USER zeiterfassung
EXPOSE 8000
VOLUME ["/app/instance"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4).status == 200 else 1)"

ENTRYPOINT ["./docker-entrypoint.sh"]
