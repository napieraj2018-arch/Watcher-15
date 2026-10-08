FROM mcr.microsoft.com/playwright/python:v1.59.0-noble
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 AI_BROWSER_HOST=0.0.0.0 AI_BROWSER_PORTABLE_PROFILES=1 AI_BROWSER_MAX_SESSIONS=1 AI_BROWSER_HOME=/tmp/ai-browser
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
COPY bootstrap.py /app/bootstrap.py
COPY entrypoint.py /app/entrypoint.py
COPY steel_runtime.py /app/steel_runtime.py
COPY steel_context_fix.py /app/steel_context_fix.py
COPY auth_status_v052.py /app/auth_status_v052.py
COPY test_auth_status_052.py /app/test_auth_status_052.py
COPY test_profile_recovery_051.py /app/test_profile_recovery_051.py
COPY test_portable_precedence.py /app/test_portable_precedence.py
COPY mcp_error_reporting.py /app/mcp_error_reporting.py
COPY test_mcp_error_reporting.py /app/test_mcp_error_reporting.py
COPY session_ownership/ /app/session_ownership/
COPY session_ownership/capability_guard.py /app/capability_guard.py
COPY Dockerfile /app/Dockerfile
RUN python -m py_compile /app/bootstrap.py /app/entrypoint.py /app/steel_runtime.py /app/steel_context_fix.py /app/auth_status_v052.py /app/mcp_error_reporting.py /app/capability_guard.py && python -c "import httpx, starlette, steel_runtime, steel_context_fix, auth_status_v052, mcp_error_reporting; from mcp.server.mcpserver.exceptions import ToolError; from playwright.async_api import BrowserContext; assert hasattr(BrowserContext, 'set_storage_state')" && python /app/test_auth_status_052.py && python /app/test_profile_recovery_051.py && python /app/test_portable_precedence.py && python /app/test_mcp_error_reporting.py && PYTHONPATH=/app/session_ownership:/app python -m unittest discover -s /app/session_ownership/tests -v
EXPOSE 10000
CMD ["sh", "-c", "if [ \"$AI_BROWSER_ENGINE\" = \"steel\" ]; then exec python /app/bootstrap.py; else exec python /app/entrypoint.py; fi"]
