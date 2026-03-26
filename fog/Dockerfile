FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy all fog module files
COPY __init__.py fog_node.py spool.py metrics_collector.py ./fog/
COPY start.sh .

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "fog.fog_node:app", "--host", "0.0.0.0", "--port", "8000"]
