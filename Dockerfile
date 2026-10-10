FROM mcr.microsoft.com/playwright/python:v1.59.0-noble
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 AI_BROWSER_HOST=0.0.0.0 AI_BROWSER_PORTABLE_PROFILES=1 AI_BROWSER_MAX_SESSIONS=1 AI_BROWSER_HOME=/tmp/ai-browser
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
COPY bootstrap.py /app/bootstrap.py
COPY test_safe_archive_extract.py /app/test_safe_archive_extract.py
COPY test_cryptography_compat.py /app/test_cryptography_compat.py
COPY entrypoint.py /app/entrypoint.py
COPY steel_runtime.py /app/steel_runtime.py
COPY test_steel_singleflight.py /app/test_steel_singleflight.py
COPY test_steel_parallel_runtime.py /app/test_steel_parallel_runtime.py
COPY test_steel_health_private.py /app/test_steel_health_private.py
COPY steel_context_fix.py /app/steel_context_fix.py
COPY native_origin_readback.py /app/native_origin_readback.py
COPY test_context_health_private.py /app/test_context_health_private.py
COPY auth_status_v052.py /app/auth_status_v052.py
COPY test_auth_status_052.py /app/test_auth_status_052.py
COPY test_meta_business_evidence_20261009.py /app/test_meta_business_evidence_20261009.py
COPY test_profile_recovery_051.py /app/test_profile_recovery_051.py
COPY test_portable_precedence.py /app/test_portable_precedence.py
COPY test_synthetic_fixture_evidence.py /app/test_synthetic_fixture_evidence.py
COPY test_synthetic_fixture_exact.py /app/test_synthetic_fixture_exact.py
COPY test_synthetic_restore_readback.py /app/test_synthetic_restore_readback.py
COPY test_coherent_fixture_pair.py /app/test_coherent_fixture_pair.py
COPY mcp_error_reporting.py /app/mcp_error_reporting.py
COPY profile_delete_guard.py /app/profile_delete_guard.py
COPY test_profile_delete_guard.py /app/test_profile_delete_guard.py
COPY test_mcp_error_reporting.py /app/test_mcp_error_reporting.py
COPY test_owner_parallel_mcp.py /app/test_owner_parallel_mcp.py
COPY session_ownership/ /app/session_ownership/
COPY session_ownership/capability_guard.py /app/capability_guard.py
COPY session_ownership/multi_capability_guard.py /app/multi_capability_guard.py
COPY connector_router.py /app/connector_router.py
COPY operator_catalog.py /app/operator_catalog.py
COPY review_dedupe.py /app/review_dedupe.py
COPY workflows/anita/reviews.yaml /app/workflows/anita/reviews.yaml
COPY test_connector_router.py /app/test_connector_router.py
COPY test_operator_catalog.py /app/test_operator_catalog.py
COPY test_operator_mcp_real.py /app/test_operator_mcp_real.py
COPY test_review_dedupe.py /app/test_review_dedupe.py
COPY Dockerfile /app/Dockerfile
RUN python /app/test_context_health_private.py && python /app/test_profile_delete_guard.py && python /app/test_steel_health_private.py && python /app/test_steel_singleflight.py && python /app/test_steel_parallel_runtime.py && python /app/test_safe_archive_extract.py && python /app/test_cryptography_compat.py && python -m py_compile /app/bootstrap.py /app/entrypoint.py /app/steel_runtime.py /app/steel_context_fix.py /app/auth_status_v052.py /app/mcp_error_reporting.py /app/capability_guard.py /app/multi_capability_guard.py /app/connector_router.py && python -c "import httpx, starlette, steel_runtime, steel_context_fix, auth_status_v052, mcp_error_reporting; from mcp.server.mcpserver.exceptions import ToolError; from playwright.async_api import BrowserContext; assert hasattr(BrowserContext, 'set_storage_state')" && python /app/test_auth_status_052.py && python /app/test_meta_business_evidence_20261009.py && python /app/test_profile_recovery_051.py && python /app/test_portable_precedence.py && python /app/test_synthetic_fixture_evidence.py && python /app/test_synthetic_fixture_exact.py && python /app/test_synthetic_restore_readback.py && python /app/test_coherent_fixture_pair.py && python /app/test_mcp_error_reporting.py && python /app/test_connector_router.py && python /app/test_operator_catalog.py && python /app/test_review_dedupe.py && PYTHONPATH=/app/session_ownership/tests:/app/session_ownership:/app python /app/test_operator_mcp_real.py && PYTHONPATH=/app/session_ownership:/app python /app/test_owner_parallel_mcp.py && PYTHONPATH=/app/session_ownership:/app python -m unittest discover -s /app/session_ownership/tests -v
EXPOSE 10000
CMD ["sh", "-c", "if [ \"$AI_BROWSER_ENGINE\" = \"steel\" ]; then exec python /app/bootstrap.py; else exec python /app/entrypoint.py; fi"]
