FROM mcr.microsoft.com/playwright/python:v1.59.0-noble
WORKDIR /srv
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY fresh_browser/requirements.txt /srv/requirements.txt
RUN python -m pip install --no-cache-dir -r /srv/requirements.txt
COPY fresh_browser/server.py fresh_browser/navigation_runtime.py fresh_browser/index.html /srv/fresh_browser/
COPY fresh_browser/test_security.py fresh_browser/test_owner_access.py fresh_browser/test_tabs.py fresh_browser/test_navigation.py fresh_browser/test_form_runtime.py fresh_browser/test_network_diagnostics.py /srv/fresh_browser/
RUN python -m py_compile /srv/fresh_browser/server.py /srv/fresh_browser/navigation_runtime.py && python /srv/fresh_browser/server.py
RUN python -m pip install --no-cache-dir httpx2==2.13.0
RUN cd /srv/fresh_browser && python -m unittest -v test_security test_owner_access test_tabs test_navigation test_form_runtime test_network_diagnostics
EXPOSE 10000
CMD ["sh", "-c", "exec uvicorn navigation_runtime:app --app-dir /srv/fresh_browser --host 0.0.0.0 --port ${PORT:-10000} --no-access-log"]
