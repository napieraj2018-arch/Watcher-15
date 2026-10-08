FROM mcr.microsoft.com/playwright/python:v1.59.0-noble
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 AI_BROWSER_HOST=0.0.0.0 AI_BROWSER_PORTABLE_PROFILES=1 AI_BROWSER_MAX_SESSIONS=1 AI_BROWSER_HOME=/tmp/ai-browser
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
COPY bootstrap.py /app/bootstrap.py
COPY entrypoint.py /app/entrypoint.py
COPY steel_runtime.py /app/steel_runtime.py
COPY steel_context_fix.py /app/steel_context_fix.py
RUN python -m py_compile /app/bootstrap.py /app/entrypoint.py /app/steel_runtime.py /app/steel_context_fix.py && python -c "import httpx, starlette, steel_runtime, steel_context_fix; from playwright.async_api import BrowserContext; assert hasattr(BrowserContext, 'set_storage_state')"
EXPOSE 10000
CMD ["sh", "-c", "if [ \"$AI_BROWSER_ENGINE\" = \"steel\" ]; then exec python /app/bootstrap.py; else exec python /app/entrypoint.py; fi"]
