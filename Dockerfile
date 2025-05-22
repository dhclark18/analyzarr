FROM python:3.11-slim

WORKDIR /app
COPY . /app

COPY requirements.txt /app/
RUN pip install --no-cache-dir -r /app/requirements.txt

ENV LOG_PATH=/logs
ENV WATCH_DIR=/watched

CMD ["python", "watcher.py"]
