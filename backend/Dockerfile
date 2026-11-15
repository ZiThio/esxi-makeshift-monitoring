
FROM python:3.10-slim

RUN apt-get update && apt-get install -y iputils-ping && rm -rf /var/lib/apt-get/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY api.py .

EXPOSE 5000

CMD ["python", "api.py"]