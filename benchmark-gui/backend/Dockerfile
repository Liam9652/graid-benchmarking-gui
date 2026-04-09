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
    git \
    smartmontools \
    && rm -rf /var/lib/apt/lists/*

# Install bench-fio from the latest GitHub release of fio-plot.
# Override the version at build time with: --build-arg BENCH_FIO_TAG=v<x.y.z>
ARG BENCH_FIO_TAG=""
RUN set -e; \
    if [ -z "$BENCH_FIO_TAG" ]; then \
        echo "Fetching latest fio-plot release tag..."; \
        BENCH_FIO_TAG=$(curl -fsSL https://api.github.com/repos/louwrentius/fio-plot/releases/latest \
            | python3 -c "import sys,json; print(json.load(sys.stdin)['tag_name'])"); \
    fi; \
    echo "Installing bench-fio @ $BENCH_FIO_TAG"; \
    pip install --no-cache-dir "git+https://github.com/louwrentius/fio-plot.git@${BENCH_FIO_TAG}"

# Setup nsenter wrappers for host tools
RUN for tool in graidctl nvidia-smi ipmitool smartctl giostat; do \
    echo "#!/bin/bash\nnsenter --target 1 --mount --uts --ipc --net --pid -- $tool \"\$@\"" > /usr/local/bin/$tool && \
    chmod +x /usr/local/bin/$tool; \
    done

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .
COPY fastapi_app.py .
COPY templates ./templates
RUN mkdir -p /app/scripts /app/results /app/logs

EXPOSE 50071
EXPOSE 50073
CMD ["python", "app.py"]
