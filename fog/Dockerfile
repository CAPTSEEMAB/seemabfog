FROM python:3.11-slim

WORKDIR /app

COPY fog/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY common/ ./common/
COPY fog/__init__.py fog/config.py fog/models.py fog/analytics.py \
     fog/notifications.py fog/dispatcher.py fog/fog_node.py \
     fog/spool.py fog/metrics_collector.py ./fog/

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "fog.fog_node:app", "--host", "0.0.0.0", "--port", "8000"]
