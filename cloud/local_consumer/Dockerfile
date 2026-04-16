FROM python:3.11-slim

WORKDIR /app

COPY cloud/local_consumer/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY common/ ./common/
COPY cloud/local_consumer/cloud_consumer.py .

EXPOSE 5000

CMD ["python", "-m", "uvicorn", "cloud_consumer:app", "--host", "0.0.0.0", "--port", "5000"]
