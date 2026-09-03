FROM python:3.12-alpine

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN apk add --no-cache \
    smartmontools \
    hdparm

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY app/main.py /app/main.py
COPY app/entrypoint.py /app/entrypoint.py
COPY app/entrypoint_headerfix.py /app/entrypoint_headerfix.py
COPY static/ /app/static/
RUN mkdir -p /app/cache

EXPOSE 8999

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8999/api/auth/status', timeout=3).read()" || exit 1

CMD ["uvicorn", "entrypoint_headerfix:app", "--host", "0.0.0.0", "--port", "8999", "--no-server-header", "--no-access-log"]
