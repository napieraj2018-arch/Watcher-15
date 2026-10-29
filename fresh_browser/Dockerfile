FROM mcr.microsoft.com/playwright/python:v1.59.0-noble
WORKDIR /srv
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY fresh_browser/requirements.txt /srv/requirements.txt
RUN python -m pip install --no-cache-dir -r /srv/requirements.txt
COPY fresh_browser/server.py fresh_browser/index.html /srv/fresh_browser/
RUN python -m py_compile /srv/fresh_browser/server.py && python /srv/fresh_browser/server.py
EXPOSE 10000
CMD ["sh", "-c", "exec uvicorn server:app --app-dir /srv/fresh_browser --host 0.0.0.0 --port ${PORT:-10000} --no-access-log"]
