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
    bc \
    curl \
    && rm -rf /var/lib/apt/lists/*


RUN echo '#!/bin/bash\nnsenter --target 1 --mount --uts --ipc --net --pid -- graidctl "$@"' > /usr/local/bin/graidctl && \
    chmod +x /usr/local/bin/graidctl && \
    echo '#!/bin/bash\nnsenter --target 1 --mount --uts --ipc --net --pid -- nvidia-smi "$@"' > /usr/local/bin/nvidia-smi && \
    chmod +x /usr/local/bin/nvidia-smi && \
    echo '#!/bin/bash\nnsenter --target 1 --mount --uts --ipc --net --pid -- ipmitool "$@"' > /usr/local/bin/ipmitool && \
    chmod +x /usr/local/bin/ipmitool && \
    echo '#!/bin/bash\nnsenter --target 1 --mount --uts --ipc --net --pid -- smartctl "$@"' > /usr/local/bin/smartctl && \
    chmod +x /usr/local/bin/smartctl && \
    echo '#!/bin/bash\nnsenter --target 1 --mount --uts --ipc --net --pid -- giostat "$@"' > /usr/local/bin/giostat && \
    chmod +x /usr/local/bin/giostat
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py .
RUN mkdir -p /app/scripts /app/results /app/logs
EXPOSE 50071
CMD ["python", "app.py"]
