FROM python:3.11-slim

WORKDIR /app
COPY . /app

RUN pip install --no-cache-dir requests watchdog
RUN pip install psycopg2-binary

ENV LOG_PATH=/logs
ENV WATCH_DIR=/watched

CMD ["python", "watcher.py"]
