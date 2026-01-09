# GRAID Benchmarking GUI - Docker Release Guide

This guide provides instructions on how to package, push, and run the GRAID Benchmarking GUI using Docker.

## 1. Prerequisites
- Docker & Docker Compose installed on the host.
- **SupremeRAID™ Driver** installed and running on the host.
- A Docker Hub account (e.g., `your-account`).

## 2. Standard Files for Users
To allow users to run this tool easily, you should provide the following files in your repository:
- `docker-compose.yml`: Pre-configured orchestration.
- `graid-bench.conf`: Default configuration file.
- `scripts/`: Directory containing the benchmark logic.
- `README.md`: Basic usage instructions.

## 3. How to Build and Push to Docker Hub

### Step 1: Login
```bash
docker login
```

### Step 2: Build and Tag Images
```bash
# Build Backend
docker build -t your-account/graid-bench-backend:v1.0 ./backend

# Build Frontend
docker build -t your-account/graid-bench-frontend:v1.0 ./frontend
```

### Step 3: Push Images
```bash
docker push your-account/graid-bench-backend:v1.0
docker push your-account/graid-bench-frontend:v1.0
```

## 4. How Users Can Run It
Users can simply download your `docker-compose.yml` and run:

```bash
docker-compose up -d
```

## 5. Security & Risk Disclosure
> [!WARNING]
> **Privileged Mode Required**: This container requires `--privileged` and `pid: host` access.
> - **Why?**: To communicate directly with NVMe drives and the SupremeRAID™ controller via `ioctl` and `nsenter`.
> - **Risk**: A privileged container has significantly more control over the host system. Ensure that the network access to the GUI ports (`50071`, `50072`) is restricted to trusted IPs.

## 6. Maintenance
- **Base Image Updates**: Regularly rebuild images to include security patches from the base `python:3.11-slim` and `nginx:alpine` images.
- **Scout Scanning**: Use `docker scout quickview` to check for vulnerabilities before pushing.
