FROM mcr.microsoft.com/playwright/python:v1.56.0-noble
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 AI_BROWSER_HOST=0.0.0.0 AI_BROWSER_PORTABLE_PROFILES=1 AI_BROWSER_MAX_SESSIONS=1 AI_BROWSER_HOME=/tmp/ai-browser
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
COPY bootstrap.py /app/bootstrap.py
EXPOSE 10000
CMD ["python","/app/bootstrap.py"]
