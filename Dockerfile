FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=10000
WORKDIR /app
COPY payload.tgz /tmp/payload.tgz
RUN tar -xzf /tmp/payload.tgz -C /app && rm /tmp/payload.tgz
RUN pip install --no-cache-dir fastapi==0.128.2 uvicorn==0.48.0 httpx==0.28.1 pydantic==2.13.5 Pillow==12.3.0 numpy==2.3.5 python-multipart==0.0.29 pillow-heif==1.8.1  && useradd --create-home --uid 10001 appuser && chown -R appuser:appuser /app
USER appuser
EXPOSE 10000
CMD ["sh","-c","exec uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-10000} --workers 1 --no-access-log"]
