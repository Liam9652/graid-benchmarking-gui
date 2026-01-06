#!/bin/bash

# SupremeRAID Benchmarking Environment Setup Script
# Version: 1.0.0
# Supports: Ubuntu/Debian, CentOS/RHEL/Alma/Rocky, SLES

set -e

# --- Colors for output ---
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}Starting SupremeRAID Benchmarking Environment Setup...${NC}"

# --- Root Check ---
if [[ $EUID -ne 0 ]]; then
   echo -e "${RED}This script must be run as root (or with sudo).${NC}"
   exit 1
fi

# --- Distribution Detection ---
if [ -f /etc/os-release ]; then
    . /etc/os-release
    DISTRO=$ID
    DISTRO_VERSION=$VERSION_ID
else
    echo -e "${RED}Error: /etc/os-release not found. Cannot determine distribution.${NC}"
    exit 1
fi

echo -e "${YELLOW}Detected Distribution: $NAME ($DISTRO $DISTRO_VERSION)${NC}"

# --- Helper Functions ---
install_pkg() {
    local pkgs=$@
    echo -e "${YELLOW}Installing system packages: $pkgs...${NC}"
    case $DISTRO in
        ubuntu|debian)
            apt-get update
            apt-get install -y $pkgs
            ;;
        centos|rhel|almalinux|rocky|ol)
            if [[ $DISTRO == "centos" && $DISTRO_VERSION == 7* ]]; then
                yum install -y $pkgs
            else
                dnf install -y $pkgs
            fi
            ;;
        sled|sles|opensuse*)
            zypper install -y $pkgs
            ;;
        *)
            echo -e "${RED}Unsupported distribution for automatic package installation: $DISTRO${NC}"
            exit 1
            ;;
    esac
}

# --- 1. Install System Dependencies ---
SYS_DEPS="fio jq nvme-cli atop bc python3-pip sg3-utils lsof curl wget git"
install_pkg $SYS_DEPS

# --- 2. Install Docker & Docker Compose ---
if ! command -v docker &> /dev/null; then
    echo -e "${YELLOW}Installing Docker...${NC}"
    case $DISTRO in
        ubuntu|debian)
            curl -fsSL https://get.docker.com -o get-docker.sh
            sh get-docker.sh
            rm get-docker.sh
            ;;
        centos|rhel|almalinux|rocky|ol)
            curl -fsSL https://get.docker.com -o get-docker.sh
            sh get-docker.sh
            rm get-docker.sh
            ;;
        *)
            echo -e "${RED}Please install Docker manually for $DISTRO${NC}"
            ;;
    esac
    systemctl enable --now docker
else
    echo -e "${GREEN}Docker is already installed.${NC}"
fi

# Install Docker Compose (plugin) if missing
if ! docker compose version &> /dev/null; then
    echo -e "${YELLOW}Installing Docker Compose Plugin...${NC}"
    install_pkg docker-compose-plugin || echo -e "${YELLOW}Warning: Could not install docker-compose-plugin via package manager. Trying manual download...${NC}"
fi

# --- 3. Install NVIDIA Container Toolkit ---
if lspci | grep -i nvidia &> /dev/null; then
    echo -e "${GREEN}NVIDIA GPU detected. Installing NVIDIA Container Toolkit...${NC}"
    if ! command -v nvidia-ctk &> /dev/null; then
        case $DISTRO in
            ubuntu|debian)
                curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
                curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list | \
                    sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#' | \
                    tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
                apt-get update
                apt-get install -y nvidia-container-toolkit
                ;;
            centos|rhel|almalinux|rocky|ol)
                curl -s -L https://nvidia.github.io/libnvidia-container/stable/rpm/nvidia-container-toolkit.repo | \
                    tee /etc/yum.repos.d/nvidia-container-toolkit.repo
                yum install -y nvidia-container-toolkit
                ;;
            *)
                echo -e "${RED}Please install NVIDIA Container Toolkit manually for $DISTRO${NC}"
                ;;
        esac
        nvidia-ctk runtime configure --runtime=docker
        systemctl restart docker
    else
        echo -e "${GREEN}NVIDIA Container Toolkit is already installed.${NC}"
    fi
else
    echo -e "${YELLOW}No NVIDIA GPU detected. Skipping NVIDIA Container Toolkit installation.${NC}"
fi

# --- 4. Install Python Dependencies ---
echo -e "${YELLOW}Installing Python dependencies...${NC}"
PIP_CMD="pip3"
# Handle PEP 668 (externally-managed-environment) in newer distros
if [[ -f /usr/lib/python3.12/EXTERNALLY-MANAGED ]] || [[ -f /usr/lib/python3.11/EXTERNALLY-MANAGED ]]; then
    PIP_CMD="pip3 install --break-system-packages"
fi

$PIP_CMD install pandas || echo -e "${RED}Warning: Failed to install pandas via pip.${NC}"

if [[ -f "src/requirements.txt" ]]; then
    $PIP_CMD install -r src/requirements.txt || echo -e "${RED}Warning: Failed to install dependencies from src/requirements.txt${NC}"
fi

# --- 5. Verify Installation ---
echo -e "\n${GREEN}--- Verification Summary ---${NC}"
for cmd in fio nvme jq docker python3 pip3 bc; do
    if command -v $cmd &> /dev/null; then
        echo -e "${GREEN}[OK] $cmd is installed: $($cmd --version 2>&1 | head -n 1)${NC}"
    else
        echo -e "${RED}[FAILED] $cmd is not installed${NC}"
    fi
done

echo -e "\n${GREEN}Environment setup complete!${NC}"
echo -e "${YELLOW}Note: If you are a non-root user, you may need to run 'sudo usermod -aG docker \$USER' and re-login to use Docker without sudo.${NC}"
echo -e "${YELLOW}Note: Please ensure 'graidctl' and SupremeRAID driver/license are installed separately.${NC}"
