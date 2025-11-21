FROM python:3.11-slim

WORKDIR /app
RUN apt-get update && apt-get install -y \
    build-essential \
    python3-dev \
    fio \
    jq \
    nvme-cli \
    atop \
    mdadm \
    util-linux \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py .
RUN mkdir -p /app/scripts /app/results /app/logs
EXPOSE 5000
CMD ["python", "app.py"]
