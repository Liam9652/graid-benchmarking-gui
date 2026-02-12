FROM python:3.11-slim

LABEL maintainer="SupremeRAID Developer" \
      description="Backend for GRAID Benchmarking GUI" \
      version="1.0"

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    python3-dev \
    fio \
    jq \
    nvme-cli \
    atop \
    mdadm \
    util-linux \
    bc \
    curl \
    smartmontools \
    && rm -rf /var/lib/apt/lists/*

# Setup nsenter wrappers for host tools
RUN for tool in graidctl nvidia-smi ipmitool smartctl giostat; do \
    echo "#!/bin/bash\nnsenter --target 1 --mount --uts --ipc --net --pid -- $tool \"\$@\"" > /usr/local/bin/$tool && \
    chmod +x /usr/local/bin/$tool; \
    done

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .
COPY templates ./templates
RUN mkdir -p /app/scripts /app/results /app/logs

EXPOSE 50071
CMD ["python", "app.py"]
