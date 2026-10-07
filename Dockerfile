FROM mcr.microsoft.com/playwright/python:v1.56.0-noble
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 AI_BROWSER_HOST=0.0.0.0 AI_BROWSER_PORTABLE_PROFILES=1 AI_BROWSER_MAX_SESSIONS=1 AI_BROWSER_HOME=/tmp/ai-browser DISPLAY=:99
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
COPY bootstrap.py /app/bootstrap.py
EXPOSE 10000
CMD ["bash","-lc","Xvfb :99 -screen 0 1440x900x24 -nolisten tcp >/tmp/xvfb.log 2>&1 & sleep 0.5; exec python /app/bootstrap.py"]
