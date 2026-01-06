#!/bin/bash

#######################################################################################
# Graid Log Collection Tool
# 
# This script collects comprehensive system logs, hardware information, and
# diagnostic data for NVIDIA GPUs, NVMe devices, BeeGFS, and SupremeRAID components.
# 
# Version: 1.0.0
# Last Update: 2025-05-01
#
# DISCLAIMER: The collected logs may contain sensitive information.
# Review before sharing externally.
#######################################################################################

# Set default locale to ensure consistent output
export LC_ALL=C

# Define constants
CLASS_VGA="0300"
CLASS_NVME="0108"
VENDOR_NVIDIA="10de"
VERSION="1.0.0-20250506"

# Define the update URL and update frequency
UPDATE_URL="https://download.graidtech.com/misc/tools/graid_log_collector/linux/graid_logs_tool"
UPDATE_SCRIPT_URL="${UPDATE_URL}/graid-log-collector.sh"
UPDATE_MD5_URL="${UPDATE_URL}/log-collection-tool.md5"
LAST_UPDATE_CHECK="/tmp/.log_collector_last_check"

# Define default settings
foldname=""
dry_run=0
accept_disclaimer=0
no_heavy_ops=0
critical_only=0
create_sosreport=1
keep_temp_files=0
collect_nfs=1
collect_samba=1
collect_beegfs=1
verbose=0
auto_update=1
skip_update=0  
enforce_update=0

# Initialize variable to track dependencies status
deps_ok=1

# Check if running with bash
if [ "$BASH" != "/bin/bash" ]; then
    /bin/bash "$0" "$@"
    exit $?
fi

#######################
# Utility Functions
#######################

# Display version information
function version() {
    echo "Graid Log Collection Tool"
    echo "Version: $VERSION"
}

# Display help information
function print_help() {
    echo "
Usage: $0 [OPTIONS]

Graid Log Collection Tool - Collects comprehensive system and component logs

Options:
  -h        Display this help message
  -V        Display version information
  -o DIR    Output directory (default: auto-generated based on hostname and date)
  -n        Skip heavy operations (avoid hanging due to unreachable resources)
  -c        Collect only critical logs (faster, smaller output)
  -d        Dry run (show commands but don't execute)
  -S        Skip collect sosreport (detailed system report)
  -k        Keep temporary files after compression
  -v        Verbose output
  -y        Accept disclaimer automatically
  -F        Skip collect NFS log
  -M        Skip collect SMBA log
  -B        Skip collect beegfs log
  -U        Skip update check
  -E        Disable Enforce update

The script will create a compressed archive with all collected logs.
"
}

# Display disclaimer and get user confirmation
function show_disclaimer() {
    if [ "$accept_disclaimer" != "1" ]; then
        echo -e "\n\n==================== DISCLAIMER ====================\n"
        echo -e "This tool will collect system and configuration data that may"
        echo -e "contain sensitive information such as:"
        echo -e "  - Hardware configuration details"
        echo -e "  - System logs and crash information"
        echo -e "  - Network configuration"
        echo -e "  - Software version details"
        echo -e "\nReview all collected data before sharing it externally.\n"
        read -p "Do you wish to continue? (y/n) " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            echo "Operation cancelled."
            exit 1
        fi
    fi
}

# Log execution of a command and its output
function log_cmd() {
    local cmd="$1"
    local outfile="$2"
    local show_output="$3"

    # Create directory for outfile if it doesn't exist
    mkdir -p "$(dirname "$outfile")"

    # Log the command itself at the top of the output file
    echo "Command: $cmd" >> "$outfile"
    echo "Executed on: $(date)" >> "$outfile"
    echo "========================================" >> "$outfile"

    if [ "$dry_run" == "1" ]; then
        echo "[DRY RUN] Would execute: $cmd"
        return 0
    fi
    
    # Show command being executed if verbose
    if [ "$verbose" == "1" ]; then
        echo "Executing: $cmd"
    fi

    local cmd_name=$(echo "$cmd" | awk '{print $1}')
    if ! which "$cmd_name" &>/dev/null && [ "$cmd_name" != "cat" ] && [ "$cmd_name" != "ls" ]; then
        echo "Command $cmd_name not found, skipping" >> "$outfile"
        echo "Command not available: $cmd_name" >> "$outfile"
        if [ "$verbose" == "1" ]; then
            echo "Command not found: $cmd_name (skipping)"
        fi
        return 0
    fi

    # Execute the command and capture output
    if [ "$show_output" == "1" ]; then
        eval "$cmd" | tee -a "$outfile"
    else
        eval "$cmd" >> "$outfile" 2>&1
    fi
    
    local status=$?
    if [ $status -ne 0 ]; then
	echo "Command '$cmd' failed with status $status (non-critical)" >> "$outfile"
        if [ "$verbose" == "1" ]; then
            echo "Note: Command '$cmd' failed with status $status (continuing)"
        fi
    fi
    return $status
}

# Append the contents of a file to the log
function append() {
    local source_file="$1"
    local target_file="$2"
    
    echo "____________________________________________" >> "$target_file"
    echo "" >> "$target_file"

    if [ ! -f "$source_file" ]; then
        echo "$source_file does not exist" >> "$target_file"
    elif [ ! -r "$source_file" ]; then
        echo "$source_file is not readable" >> "$target_file"
    else
        echo "$source_file" >> "$target_file"
        cat "$source_file" >> "$target_file"
    fi
    echo "" >> "$target_file"
}

# Append a file only if it exists (without warning if missing)
function append_silent() {
    local source_file="$1"
    local target_file="$2"
    
    if [ -f "$source_file" -a -r "$source_file" ]; then
        echo "____________________________________________" >> "$target_file"
        echo "" >> "$target_file"
        echo "$source_file" >> "$target_file"
        cat "$source_file" >> "$target_file"
        echo "" >> "$target_file"
    fi
}

# Append all files matching a glob pattern
function append_glob() {
    local pattern="$1"
    local target_file="$2"
    
    for i in $(ls $pattern 2> /dev/null); do
        append "$i" "$target_file"
    done
}

# Show progress information
function show_progress() {
    local step="$1"
    local total="$2"
    local description="$3"
    local percent=$((step*100/total))
    printf "[%3d%%] %-50s\r" $percent "$description"
}

# Calculate and save MD5 checksum for a file
function calculate_checksum() {
    local file="$1"
    if [ -f "$file" ]; then
        md5sum "$file" > "${file}.md5"
        echo "MD5 checksum saved to ${file}.md5"
    else
        echo "Error: File $file not found"
    fi
}

# Get Linux distribution ID
function get_distro() {
    if [ -f /etc/os-release ]; then
        . /etc/os-release
        echo "$ID"
    elif [ -f /etc/redhat-release ]; then
        echo "rhel"
    else
        echo "unknown"
    fi
}

#######################
# Dependency Check
#######################

function check_dependencies() {
    echo "Checking dependencies..."
    local deps_failed=0
    local tools_to_install=""
    local critical_missing=0
    
    # List of critical and non-critical tools
    local critical_tools="tar md5sum"
    local optional_tools="graidctl nvidia-smi"
    local installable_tools="jq nvme"

    # Check for critical tools
    for name in $critical_tools; do
        if ! which $name &>/dev/null; then
            echo "ERROR: Critical dependency '$name' not found."
            critical_missing=1
            
            if [ -z "$tools_to_install" ]; then
                tools_to_install="$name"
            else
                tools_to_install="$tools_to_install $name"
            fi
        fi
    done
    
    # Check for non-critical tools
    for name in $installable_tools; do
        if ! which $name &>/dev/null; then
            echo "WARNING: '$name' not found. Some functionality will be limited."
            
            if [ -z "$tools_to_install" ]; then
                tools_to_install="$name"
            else
                tools_to_install="$tools_to_install $name"
            fi
            
            deps_failed=1
        fi
    done
    
    for name in $optional_tools; do
        if ! which $name &>/dev/null; then
            echo "WARNING: Optional tool '$name' not found. Some functionality will be limited."
            deps_failed=1
        fi
    done
    
    # Check for system report tools
    echo "Checking for system report tools..."
    local sos_package=""
    local install_cmd=""
    local sos_found=0
    
    DISTRO_ID=$(get_distro)
    case $DISTRO_ID in
        centos|almalinux|rocky|rhel|ol|fedora)
            if which sos &>/dev/null || which sosreport &>/dev/null; then
                sos_found=1
            else
                sos_package="sos"
                if [ -z "$tools_to_install" ]; then
                    tools_to_install="$sos_package"
                else
                    tools_to_install="$tools_to_install $sos_package"
                fi
            fi
            ;;
        
        ubuntu|debian)
            if which sosreport &>/dev/null; then
                sos_found=1
            else
                sos_package="sosreport"
                if [ -z "$tools_to_install" ]; then
                    tools_to_install="$sos_package"
                else
                    tools_to_install="$tools_to_install $sos_package"
                fi
            fi
            ;;
        
        sles|opensuse-leap|suse)
            if which supportconfig &>/dev/null; then
                sos_found=1
            else
                sos_package="supportutils"
                if [ -z "$tools_to_install" ]; then
                    tools_to_install="$sos_package"
                else
                    tools_to_install="$tools_to_install $sos_package"
                fi
            fi
            ;;
        
        *)
            if which sos &>/dev/null || which sosreport &>/dev/null || which supportconfig &>/dev/null; then
                sos_found=1
            else
                echo "WARNING: No system report tool found for this distribution."
                if [ "$create_sosreport" == "1" ]; then
                    create_sosreport=0
                    echo "SOS report creation will be skipped."
                fi
            fi
            ;;
    esac
    
    if [ $sos_found -eq 0 ] && [ "$create_sosreport" == "1" ]; then
        echo "WARNING: System report tool not found but sosreport collection is enabled."
        deps_failed=1
    fi
    
    
    if [ -n "$tools_to_install" ]; then
        if [ $critical_missing -eq 1 ]; then
            echo "Critical tools are missing. These must be installed to continue."
        fi
        
        echo "The following tools need to be installed: $tools_to_install"
        
        #
        local install_command=""
        case $DISTRO_ID in
            centos|almalinux|rocky|rhel|ol|fedora)
                if which dnf &>/dev/null; then
                    install_command="dnf install -y"
                else
                    install_command="yum install -y"
                fi
                ;;
            ubuntu|debian)
                install_command="apt-get install -y"
                ;;
            sles|opensuse-leap|suse)
                install_command="zypper install -y"
                ;;
            *)
                echo "Unknown distribution. Cannot determine package manager."
                if [ $critical_missing -eq 1 ]; then
                    exit 1
                fi
                return $deps_failed
                ;;
        esac
        
        
        read -p "Do you want to install these tools? (y/n) " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            echo "Installing dependencies with: $install_command $tools_to_install"
            
            
            if $install_command $tools_to_install; then
                echo "Installation successful."
                
                if [ $critical_missing -eq 1 ]; then
                    for name in $critical_tools; do
                        if ! which $name &>/dev/null; then
                            echo "ERROR: Critical dependency '$name' still not found after installation."
                            exit 1
                        fi
                    done
                fi
                
                # check sosreport tool exists
                if [ -n "$sos_package" ]; then
                    if which sos &>/dev/null || which sosreport &>/dev/null || which supportconfig &>/dev/null; then
                        echo "System report tool installed successfully."
                        sos_found=1
                    fi
                fi
            else
                echo "Installation failed."
                if [ $critical_missing -eq 1 ]; then
                    echo "Cannot continue without critical dependencies."
                    exit 1
                fi
            fi
        else
            if [ $critical_missing -eq 1 ]; then
                echo "Cannot continue without critical dependencies."
                exit 1
            fi
            echo "Continuing without installing dependencies. Some functionality will be limited."
        fi
    fi
    
    if [ $deps_failed -eq 0 ] && [ $sos_found -eq 1 ]; then
        echo "All dependencies available."
        return 0
    else
        echo "Some dependencies are missing. The script will continue with limited functionality."
        return 1
    fi
}

#######################
# PCI Device Functions
#######################

# PCI device attribute indices
declare -A PCI_ATTR_IDX
PCI_ATTR_IDX[CLASS]="0"
PCI_ATTR_IDX[BDF]="1"
PCI_ATTR_IDX[NAME]="2"
PCI_ATTR_IDX[VENDOR]="3"
PCI_ATTR_IDX[DEVICE]="4"
PCI_ATTR_IDX[DEV_NAME]="5"
PCI_ATTR_IDX[DEV_ADDR]="6"
PCI_ATTR_IDX[NUMA]="7"
PCI_ATTR_IDX[SPEED]="8"

# Arrays to store device information
declare -a PCI_DEVS
declare -A PCI_DRIVER

# Get GPU ID from NVIDIA SMI output
function gpu_id() {
    local bdf=${1^^}
    local gpu
    
    # Check if nvidia-smi is available
    if ! which nvidia-smi &>/dev/null; then
        return 1
    fi
    
    # Loop through nvidia-smi output to find the GPU with matching BDF
    for line in $(nvidia-smi); do
        if ! [[ ${line} =~ ^\|\ *([0-9]+)\ .+[0]{8}:${bdf} ]]; then
            continue
        fi
        gpu=${BASH_REMATCH[1]}
        break
    done
    
    # If GPU found, get its UUID
    for line in $(nvidia-smi -L); do
        if ! [[ ${line} =~ ^GPU\ ${gpu}:.+UUID:\ ([^\)]+)\) ]]; then
            continue
        fi
        echo ${BASH_REMATCH[1]}
        break
    done
}

# List PCI devices available for passthrough (NVIDIA GPUs and NVMe devices)
function list_pci_passthrough() {
    local PCI_DEVS_STR=
    local oldifs=${IFS}
    IFS=$'\n'
    
    # Skip if lspci is not available
    if ! which lspci &>/dev/null; then
        echo "lspci not found, skipping PCI device enumeration" >> "$output_log"
        return 1
    fi
    
    show_progress 0 100 "Scanning PCI devices"
    
    # Loop through all PCI devices
    local pcidev
    for pcidev in $(lspci -nn); do
        if [[ ${pcidev} =~ ^([0-9a-f]{2}:[0-9a-f]{2}.[0-9a-f])\ .+\ \[([0-9a-f]{4})\]:\ (.+)\ \[([0-9a-f]{4}):([0-9a-f]{4})\] ]]; then
            local bdf=${BASH_REMATCH[1]}
            local class=${BASH_REMATCH[2]}
            local name=${BASH_REMATCH[3]}
            local vendor=${BASH_REMATCH[4]}
            local device=${BASH_REMATCH[5]}
            local driver

            # Only process NVMe controllers and NVIDIA GPUs
            case ${class} in
                ${CLASS_NVME})
                    driver=nvme
                    ;;
                ${CLASS_VGA})
                    driver=NVIDIA
                    if [[ ${vendor} != ${VENDOR_NVIDIA} ]]; then
                        continue
                    fi
                    ;;
                *)
                    continue
                    ;;
            esac

            # Get detailed device information
            PCI_DBDF="0000:${bdf}"
            local numa_node=$(cat /sys/bus/pci/devices/${PCI_DBDF}/numa_node 2>/dev/null || echo "N/A")
            local link_speed=$(cat /sys/bus/pci/devices/${PCI_DBDF}/current_link_speed 2>/dev/null || echo "N/A")
            local link_width=$(cat /sys/bus/pci/devices/${PCI_DBDF}/current_link_width 2>/dev/null || echo "N/A")
            
            # Format the link speed in a readable way
            local speed
            case ${link_speed} in
		        32*)
                    speed=Gen5x${link_width}
                    ;;

                16*)
                    speed=Gen4x${link_width}
                    ;;
                8*)
                    speed=Gen3x${link_width}
                    ;;
                5*)
                    speed=Gen2x${link_width}
                    ;;
                2.5*)
                    speed=Gen1x${link_width}
                    ;;
                *)
                    speed=${link_speed}x${link_width}
                    ;;
            esac

            # Get device-specific information
            local devname
            local devaddr
            case ${class} in
                ${CLASS_NVME})
                    # Check for NVMe device
                    devname=$(ls /sys/bus/pci/devices/${PCI_DBDF}/nvme 2>/dev/null)
                    if ! [[ -f /sys/bus/pci/devices/${PCI_DBDF}/nvme/${devname}/subsysnqn ]]; then
                        # Check for SupremeRAID device
                        devname=$(ls /sys/bus/pci/devices/${PCI_DBDF}/gd 2>/dev/null)
                        if ! [[ -f /sys/bus/pci/devices/${PCI_DBDF}/gd/${devname}/subsysnqn ]]; then
                            continue
                        else
                            devaddr=$(cat /sys/bus/pci/devices/${PCI_DBDF}/gd/${devname}/subsysnqn)
                        fi
                    else
                        devaddr=$(cat /sys/bus/pci/devices/${PCI_DBDF}/nvme/${devname}/subsysnqn)
                    fi
                    # Trim whitespace
                    if [[ ${devaddr} =~ ^(.+[^\ ])[\ ]+$ ]]; then
                        devaddr=${BASH_REMATCH[1]}
                    fi
                    ;;
                ${CLASS_VGA})
                    # Set GPU information
                    devname=GPU
                    devaddr=$(gpu_id ${bdf})
                    if [[ -z ${devaddr} ]]; then
                        continue
                    fi
                    # Fix known model names
                    if [[ ${device} == "1fb0" ]]; then
                        name="NVIDIA Corporation TU117GLM [Quadro T1000]"
                    fi
                    if [[ ${device} == "2531" ]]; then
                        name="NVIDIA Corporation GA106 [RTX A2000]"
                    fi
                    ;;
                *)
                    continue
                    ;;
            esac

            # Add device to array with proper formatting
            if [[ -z ${PCI_DEVS_STR} ]]; then
                NL=
            else
                NL=$'\n'
            fi
            PCI_DEVS_STR="${PCI_DEVS_STR}${NL}\"${class}\" \"${bdf}\" \"${name}\" \"${vendor}\" \"${device}\" \"${devname}\" \"${devaddr}\" \"${numa_node}\" \"${speed}\""
        fi
    done
    
    # Sort devices and add to array
    for pcidev in $(echo "${PCI_DEVS_STR}" | sort); do
        PCI_DEVS+=(${pcidev})
    done
    
    show_progress 100 100 "Scanning PCI devices - complete"
    echo
    
    IFS=${oldifs}
}

# Parse attributes for a specific PCI device
function parse_pci_attr_item() {
    local item=$1
    local attr
    local -a dev_attrs
    local oldifs=${IFS}
    IFS=$'\n'
    
    # Extract device attributes
    eval dev_attrs=\(${PCI_DEVS[$item]}\)
    
    # Map attributes to variables
    for attr in "${!PCI_ATTR_IDX[@]}"; do
        local idx=${PCI_ATTR_IDX[${attr}]}
        local attr_val="${dev_attrs[${idx}]}"
        eval PCI_${attr}=\"${attr_val}\"
    done
    
    IFS=${oldifs}
}

# Print information about all detected PCI devices
function print_pci_devs() {
    local PCINUM=${#PCI_DEVS[@]}
    local output_file="$1"
    
    echo "======== PCI Device Summary ========" >> "$output_file"
    echo "Total devices detected: $PCINUM" >> "$output_file"
    echo "" >> "$output_file"
    
    for ((i=0;i<$PCINUM;i++)); do
        parse_pci_attr_item ${i}
        printf "%6s (BDF: ${PCI_BDF}, Speed: ${PCI_SPEED}, NUMA: ${PCI_NUMA}): ${PCI_DEV_ADDR} ${PCI_NAME}\n" "${PCI_DEV_NAME}" >> "$output_file"
    done
}

#######################
# Data Collection Functions
#######################

# Collect basic system information
function get_basic_info() {
    local log_dir="$1"
    local hw_info="${log_dir}/basic_info/hw_info.log"
    local sw_info="${log_dir}/basic_info/sw_info.log"
    
    # Create directories
    mkdir -p "${log_dir}/basic_info"
    
    show_progress 0 100 "Collecting basic system information"
    
    # Hardware information
    echo "============ CPU Information ===============" >> "$hw_info"
    log_cmd "lscpu" "$hw_info"
    
    echo "============ Board Information ===============" >> "$hw_info"
    log_cmd "cat /sys/class/dmi/id/board_name" "$hw_info"
    log_cmd "cat /sys/class/dmi/id/product_name" "$hw_info"
    log_cmd "cat /sys/class/dmi/id/sys_vendor" "$hw_info"
    
    echo "============ Memory Information ===============" >> "$hw_info"
    log_cmd "free -m" "$hw_info"
    log_cmd "dmidecode -t 17" "$hw_info"
    echo "RAM x $(dmidecode -t 17 | grep "Memory Technology: DRAM" | wc -l)" >> "$hw_info"
    
    echo "============ PCI Device Listing ===============" >> "$hw_info"
    log_cmd "lspci -nn -vvv -PP" "$hw_info"
    
    echo "============ PCI Device Tree ===============" >> "$hw_info"
    log_cmd "lspci -tnnvPP" "$hw_info"
    
    echo "============ DMI Information ===============" >> "$hw_info"
    log_cmd "dmidecode" "$hw_info"
    
    # NVIDIA information if available
    if which nvidia-smi &>/dev/null; then
        echo "============ NVIDIA GPU Information ===============" >> "$hw_info"
        log_cmd "nvidia-smi -q" "${log_dir}/basic_info/nv_info.log"
    fi
    
    # Software information
    echo "============ OS Version =============" >> "$sw_info"
    log_cmd "cat /etc/*release" "$sw_info"
    
    echo "============ Kernel Version =========" >> "$sw_info"
    log_cmd "uname -r" "$sw_info"
    
    # Module information
    echo "============ NVIDIA Modules =========" >> "$sw_info"
    log_cmd "modinfo nvidia" "$sw_info"
    log_cmd "modinfo nvidia-modeset" "$sw_info"
    log_cmd "modinfo nvidia-drm" "$sw_info"
    
    echo "============ SupremeRAID Modules =========" >> "$sw_info"
    log_cmd "modinfo graid" "$sw_info"
    log_cmd "modinfo graid_nvidia" "$sw_info"
    log_cmd "modinfo nvme" "$sw_info"
    
    # GPU information
    if which nvidia-smi &>/dev/null; then
        echo "============ NVIDIA Serial Numbers =========" >> "$sw_info"
        log_cmd "nvidia-smi --query-gpu=index,name,serial,pcie.link.gen.current,pcie.link.width.current --format=csv" "$sw_info"
    fi
    
    # DKMS status
    echo "============ DKMS Status =========" >> "$sw_info"
    log_cmd "dkms status" "$sw_info"
    
    # Loaded modules
    echo "============ Loaded Modules ==========" >> "$sw_info"
    log_cmd "lsmod" "$sw_info"
    
    # System services
    echo "============ System Services ==========" >> "$sw_info"
    log_cmd "systemctl list-unit-files" "$sw_info"
    
    show_progress 100 100 "Basic system information collected"
    echo
}

# Collect resource usage information
function collect_resource_usage() {
    local log_dir="$1"
    mkdir -p "${log_dir}/resources"
    
    show_progress 0 100 "Collecting resource usage information"
    
    # System resource usage
    log_cmd "top -b -n 1" "${log_dir}/resources/top.log"
    log_cmd "ps aux --sort=-%mem | head -20" "${log_dir}/resources/high_mem_processes.log"
    log_cmd "ps aux --sort=-%cpu | head -20" "${log_dir}/resources/high_cpu_processes.log"
    log_cmd "vmstat 1 5" "${log_dir}/resources/vmstat.log"
    
    # I/O statistics if available
    if which giostat &>/dev/null; then
        log_cmd "giostat -x 1 5" "${log_dir}/resources/iostat.log"
    elif which giostat &>/dev/null; then
        log_cmd "iostat -x 1 5" "${log_dir}/resources/iostat.log"
    fi
    
    # CPU statistics if available
    if which mpstat &>/dev/null; then
        log_cmd "mpstat -P ALL 1 5" "${log_dir}/resources/mpstat.log"
    fi
    
    show_progress 100 100 "Resource usage information collected"
    echo
}

# Collect network information
function collect_network_info() {
    local log_dir="$1"
    mkdir -p "${log_dir}/network"
    
    show_progress 0 100 "Collecting network information"
    
    # Basic network info
    log_cmd "ip a" "${log_dir}/network/ip_addr.log"
    log_cmd "ip route" "${log_dir}/network/ip_route.log"
    log_cmd "ip rule" "${log_dir}/network/ip_rule.log"
    log_cmd "ip route show table all" "${log_dir}/network/ip_route_tables.log"
    
    # Network connections
    if which ss &>/dev/null; then
        log_cmd "ss -tuplan" "${log_dir}/network/connections.log"
    elif which netstat &>/dev/null; then
        log_cmd "netstat -tuplan" "${log_dir}/network/connections.log"
    else
        echo "Neither ss nor netstat commands available" >> "${log_dir}/network/connections.log"
    fi
    
    # DNS configuration
    log_cmd "cat /etc/resolv.conf" "${log_dir}/network/resolv.conf.log"
    log_cmd "cat /etc/hosts" "${log_dir}/network/hosts.log"
    
    # Network interface statistics
    for iface in $(ls /sys/class/net/ 2>/dev/null); do
        if which ethtool &>/dev/null; then
	    log_cmd "ethtool $iface" "${log_dir}/network/ethtool_${iface}.log"

            if ethtool -S $iface &>/dev/null; then
                log_cmd "ethtool -S $iface" "${log_dir}/network/ethtool_stats_${iface}.log"
            else
                echo "Interface $iface doesn't support statistics" >> "${log_dir}/network/ethtool_stats_${iface}.log"
            fi
        fi
    done
    
    # InfiniBand information if available
    if which ibstat &>/dev/null; then
        log_cmd "ibstat" "${log_dir}/network/ibstat.log"
    fi
    
    if which ibv_devinfo &>/dev/null; then
        log_cmd "ibv_devinfo -v" "${log_dir}/network/ibv_devinfo.log"
    fi

    if which iblinkinfo &>/dev/null; then
        log_cmd "iblinkinfo -p" "${log_dir}/network/iblinkinfo.log"
    fi

    if which ibdev2netdev &>/dev/null; then
        log_cmd "ibdev2netdev" "${log_dir}/network/ibdev2netdev.log"
    fi
    
    show_progress 100 100 "Network information collected"
    echo
}

# Collect system logs
function collect_system_logs() {
    local log_dir="$1"
    mkdir -p "${log_dir}/logs"
    
    show_progress 0 100 "Collecting system logs"
    
    # Detect Linux distribution for log file paths
    local OS_TYPE=$(get_distro)
    declare -a LOG_FILES
    
    # Define log file patterns based on distribution
    case $OS_TYPE in
        "ubuntu"|"debian"|"linuxmint"|"pop"|"elementary")
            # Debian-based distributions
            LOG_FILES=(
                "/var/log/syslog*"
                "/var/log/kern.log*"
                "/var/log/dmesg*"
                "/var/log/boot.log*"
                "/var/log/auth.log*"
            )
            ;;
        "rhel"|"centos"|"fedora"|"rocky"|"almalinux"|"ol")
            # Red Hat-based distributions
            LOG_FILES=(
                "/var/log/messages*"
                "/var/log/dmesg*"
                "/var/log/secure*"
                "/var/log/boot.log*"
            )
            ;;
        "suse"|"opensuse-leap"|"opensuse-tumbleweed")
            # SUSE-based distributions
            LOG_FILES=(
                "/var/log/messages*"
                "/var/log/dmesg*"
                "/var/log/boot.log*"
            )
            ;;
        *)
            # Generic fallback for other distributions
            LOG_FILES=(
                "/var/log/syslog*"
                "/var/log/messages*"
                "/var/log/dmesg*"
                "/var/log/kern.log*"
                "/var/log/boot.log*"
                "/var/log/auth.log*"
                "/var/log/secure*"
            )
            ;;
    esac
    
    # Save current dmesg output
    log_cmd "dmesg" "${log_dir}/logs/dmesg_current.log"
    log_cmd "dmesg --time-format iso" "${log_dir}/dmesg.log"
    
    # Copy system logs
    local file_count=0
    local total_files=$(find ${LOG_FILES[@]} -type f 2>/dev/null | wc -l)
    
    echo "Collecting system logs..."
    for pattern in "${LOG_FILES[@]}"; do
        for file in $pattern; do
            if [ -f "$file" ]; then
                if [ "$verbose" == "1" ]; then
                    echo "Copying $file"
                fi
                cp -af "$file" "${log_dir}/logs/" 2>/dev/null
                file_count=$((file_count+1))
                show_progress $file_count $total_files "Copying system logs"
            fi
        done
    done
    
    # Collect additional system info
    log_cmd "uptime" "${log_dir}/logs/uptime.txt"
    
    # Copy NVIDIA installer log if exists
    if [ -f "/var/log/nvidia-installer.log" ]; then
        cp "/var/log/nvidia-installer.log" "${log_dir}/logs/"
    fi
    
    # Copy fstab
    cp /etc/fstab "${log_dir}/basic_info/" 2>/dev/null
    
    # Mount information
    log_cmd "mount" "${log_dir}/logs/mount_info.log"
    
    # Block device information
    log_cmd "lsblk -a" "${log_dir}/logs/lsblk.log"
    log_cmd "lsblk --fs" "${log_dir}/logs/lsblk.log"
    log_cmd "lsblk -T" "${log_dir}/logs/lsblk.log"
    log_cmd "lsblk --discard" "${log_dir}/logs/lsblk.log"
    
    # Device mapper information
    log_cmd "dmsetup table" "${log_dir}/logs/dm_list.log"
    
    # Disk usage
    log_cmd "df -h" "${log_dir}/logs/df.log"
    
    # Command history
    cp /root/.bash_history "${log_dir}/history_root_print.txt" 2>/dev/null
    cp /home/*/.bash_history "${log_dir}/history_user_print.txt" 2>/dev/null
    log_cmd "history" "${log_dir}/history_root_print_1.log"
    
    show_progress 100 100 "System logs collected"
    echo
}

# Collect BeeGFS information
function collect_beegfs_info() {
    local log_dir="$1"
    mkdir -p "${log_dir}/beegfs"
    
    show_progress 0 100 "Collecting BeeGFS information"
    
    # Check if BeeGFS is installed
    if [ -d "/etc/beegfs" ]; then
        # Copy BeeGFS configuration
        cp -a /etc/beegfs/ "${log_dir}/beegfs/" 2>/dev/null
        
        # Copy BeeGFS manager config if exists
        if [ -f "/opt/beegfs_setup_manager/beegfs_manager_config.yaml" ]; then
            cp -a /opt/beegfs_setup_manager/beegfs_manager_config.yaml "${log_dir}/beegfs/" 2>/dev/null
        fi
        
        # Copy BeeGFS logs
        cp -a /var/log/beegfs* "${log_dir}/logs/" 2>/dev/null
        
        # Copy cluster logs if exist
        cp -a /var/log/pcsd/ "${log_dir}/logs/" 2>/dev/null
        cp -a /var/log/pacemaker/ "${log_dir}/logs/" 2>/dev/null
        
        # Run BeeGFS commands if available
        if which beegfs-check-servers &>/dev/null; then
            log_cmd "beegfs-check-servers" "${log_dir}/beegfs/beegfs-check-servers.log"
        fi
        
        if which beegfs-df &>/dev/null; then
            log_cmd "beegfs-df" "${log_dir}/beegfs/beegfs-df.log"
        fi
        
        if which beegfs-ctl &>/dev/null; then
            log_cmd "beegfs-ctl --listnodes --nodetype=management --nicdetails --route" "${log_dir}/beegfs/beegfs-ctl-mgmt.log"
            log_cmd "beegfs-ctl --listnodes --nodetype=metadata --nicdetails --route" "${log_dir}/beegfs/beegfs-ctl-meta.log"
            log_cmd "beegfs-ctl --listnodes --nodetype=storage --nicdetails --route" "${log_dir}/beegfs/beegfs-ctl-storage.log"
            log_cmd "beegfs-ctl --listtargets --nodetype=meta --state --spaceinfo --longnodes --pools" "${log_dir}/beegfs/beegfs-ctl-meta-targets.log"
            log_cmd "beegfs-ctl --listtargets --nodetype=storage --state --spaceinfo --longnodes --pools" "${log_dir}/beegfs/beegfs-ctl-storage-targets.log"
        fi
    else
        echo "BeeGFS not detected, skipping..." >> "${log_dir}/beegfs/status.log"
    fi
    
    show_progress 100 100 "BeeGFS information collected"
    echo
}

# Collect SupremeRAID information
function collect_graid_info() {
    local log_dir="$1"
    mkdir -p "${log_dir}/graid_r"
    
    show_progress 0 100 "Collecting SupremeRAID information"
    
    # Copy SupremeRAID logs if they exist
    cp -a /var/log/graid/ "${log_dir}/graid_r/" 2>/dev/null
    cp -a /var/log/graidmgr/ "${log_dir}/graid_r/" 2>/dev/null
    cp -a /var/log/graid-preinstaller/ "${log_dir}/graid_r/" 2>/dev/null
    cp -a /var/log/graid-installer/ "${log_dir}/graid_r/" 2>/dev/null
    cp -a /usr/share/graid/led_conf/ "${log_dir}/graid_r/" 2>/dev/null
    
    # Check if SupremeRAID service is active
    if systemctl is-active --quiet graid 2>/dev/null; then
        echo "SupremeRAID service is active" >> "${log_dir}/graid_r/graid_basic_info.log"

        # execute griadctl
        if which graidctl &>/dev/null; then
            log_cmd "graidctl desc lic" "${log_dir}/graid_r/graid_basic_info.log"
            log_cmd "graidctl version" "${log_dir}/graid_r/graid_basic_info.log"
            log_cmd "graidctl ls vd --format json" "${log_dir}/graid_r/graid_basic_info.log"
            log_cmd "graidctl ls dg --format json" "${log_dir}/graid_r/graid_basic_info.log"
            log_cmd "graidctl ls pd --format json" "${log_dir}/graid_r/graid_basic_info.log"
            log_cmd "graidctl ls cx --format json" "${log_dir}/graid_r/graid_basic_info.log"
            log_cmd "graidctl desc conf led --format json" "${log_dir}/graid_r/graid_basic_info.log"
        else
            echo "graidctl command not available" >> "${log_dir}/graid_r/graid_basic_info.log"
        fi

        if which graid-mgr &>/dev/null; then
            log_cmd "graid-mgr version" "${log_dir}/graid_r/graid_basic_info.log"
        else
            echo "graid-mgr command not available" >> "${log_dir}/graid_r/graid_basic_info.log"
        fi

        # check service status
        if systemctl status graid.service &>/dev/null; then
            log_cmd "systemctl status graid.service" "${log_dir}/graid_r/graid_basic_info.log"
        else
            echo "graid.service status not available" >> "${log_dir}/graid_r/graid_basic_info.log"
        fi

        if systemctl status graid-mgr &>/dev/null; then
            log_cmd "systemctl status graid-mgr" "${log_dir}/graid_r/graid_basic_info.log"
        else
            echo "graid-mgr service not available or not running" >> "${log_dir}/graid_r/graid_basic_info.log"
        fi
    else
        echo "SupremeRAID service is inactive" >> "${log_dir}/graid_r/graid_basic_info.log"

        # try to get version
        if which graidctl &>/dev/null; then
            log_cmd "graidctl version" "${log_dir}/graid_r/graid_basic_info.log"
        fi

        if which graid-mgr &>/dev/null; then
            log_cmd "graid-mgr version" "${log_dir}/graid_r/graid_basic_info.log"
        fi
    fi
    # Collect journal logs with size management
    show_progress 25 100 "Collecting SupremeRAID journal logs"
    
    # Function to split large log files
    function collect_journal_log() {
        local service="$1"
        local output_prefix="$2"
        
        journalctl -u "$service" | split -b 100M --numeric-suffixes=1 --suffix-length=1 --additional-suffix=.log - "$output_prefix"
    }
    
    # Collect various journal logs
    collect_journal_log "graid" "${log_dir}/graid_r/graid_server_journal."
    collect_journal_log "graidcore@0.service" "${log_dir}/graid_r/graid_core0_journal."
    collect_journal_log "graidcore@1.service" "${log_dir}/graid_r/graid_core1_journal."
    collect_journal_log "graid-mgr" "${log_dir}/graid_r/graid_mgr_journal."
    
    # Collect kernel logs from journal
    journalctl -k -b all | split -b 100M --numeric-suffixes=1 --suffix-length=1 --additional-suffix=.log - "${log_dir}/dmesg_journal."
    
    # Additional checks
    log_cmd "cat /proc/cmdline" "${log_dir}/graid_r/check_cmdline.log"
    
    show_progress 100 100 "SupremeRAID information collected"
    echo
}

# Collect NVMe device information
function get_nvme_info() {
    local log_dir="$1"
    mkdir -p "${log_dir}/nvme"
    
    show_progress 0 100 "Collecting NVMe device information"
    
    # Check if nvme command is available
    if ! which nvme &>/dev/null; then
        echo "nvme-cli not found, skipping NVMe device information collection" >> "${log_dir}/nvme/status.log"
        show_progress 100 100 "NVMe information collection skipped"
        echo
        return 1
    fi
    
    # Basic NVMe list
    log_cmd "nvme list" "${log_dir}/nvme/nvme_lst.log" || true
    
    # Check for SupremeRAID service
    local graid_cmd=0
    if systemctl status graid &>/dev/null; then
        graid_cmd=1
    fi
    
    # Process NVMe devices
    local device_count=0
    local total_devices=$(ls -d /sys/block/nvme*n* /sys/block/gpd*n* 2>/dev/null | wc -l)
    
    # Function to extract device number from path
    function extract_device_num() {
        local path="$1"
        local pattern="$2"
        local regex_pattern="^\/sys\/block\/${pattern}([0-9]+)(c[0-9]+)?n([0-9]+)\/.*$"
        
        if [[ $path =~ $regex_pattern ]]; then
            echo "${BASH_REMATCH[1]}"
        else
            echo ""
        fi
    }
    
    # Process regular NVMe devices
    for nvme_node in /sys/block/*/device/device/numa_node; do
        if [[ ${nvme_node:11:4} == "nvme" ]]; then
            local nvmen=$(extract_device_num "$nvme_node" "nvme")
            
            if [ -z "$nvmen" ]; then
                continue
            fi
            
            device_count=$((device_count+1))
            show_progress $device_count $total_devices "Processing NVMe devices"
            
            # Log NVMe version
            nvme --version >> "${log_dir}/nvme/nvme.log" 2>/dev/null
            
            # Collect basic information
            echo "======================" >> "${log_dir}/nvme/nvme.log"
            echo "nvme${nvmen}_node: $(cat ${nvme_node} 2>/dev/null)" >> "${log_dir}/nvme/nvme.log"
            echo "nvme${nvmen}_nqn: $(cat /sys/class/block/nvme${nvmen}*/device/subsysnqn 2>/dev/null)" >> "${log_dir}/nvme/nvme.log"
            echo "nvme${nvmen}_address: $(cat /sys/class/block/nvme${nvmen}*/device/address 2>/dev/null)" >> "${log_dir}/nvme/nvme.log"
            echo "nvme${nvmen}_device_id: $(cat /sys/class/block/nvme${nvmen}*/device/device/device 2>/dev/null)" >> "${log_dir}/nvme/nvme.log"
            echo "nvme${nvmen}_vender_id: $(cat /sys/class/block/nvme${nvmen}*/device/device/vendor 2>/dev/null)" >> "${log_dir}/nvme/nvme.log"
            echo "nvme${nvmen}_queue_count: $(cat /sys/class/block/nvme${nvmen}*/device/queue_count 2>/dev/null)" >> "${log_dir}/nvme/nvme.log"
            echo "nvme${nvmen}_current_link_speed: $(cat /sys/class/block/nvme${nvmen}*/device/device/current_link_speed 2>/dev/null)" >> "${log_dir}/nvme/nvme.log"
            echo "nvme${nvmen}_current_link_width: $(cat /sys/class/block/nvme${nvmen}*/device/device/current_link_width 2>/dev/null)" >> "${log_dir}/nvme/nvme.log"
            echo "nvme${nvmen}_max_link_speed: $(cat /sys/class/block/nvme${nvmen}*/device/device/max_link_speed 2>/dev/null)" >> "${log_dir}/nvme/nvme.log"
            echo "nvme${nvmen}_max_link_width: $(cat /sys/class/block/nvme${nvmen}*/device/device/max_link_width 2>/dev/null)" >> "${log_dir}/nvme/nvme.log"
            
            # Create device-specific directory
            mkdir -p "${log_dir}/nvme/nvme${nvmen}"
            
            # Collect detailed NVMe information if not in critical-only mode
            if [ "$critical_only" != "1" ]; then
                log_cmd "nvme id-ctrl /dev/nvme${nvmen}n1 -H | grep 'ver '" "${log_dir}/nvme/nvme.log"
                log_cmd "nvme id-ctrl -H /dev/nvme${nvmen}n1 | grep 'Data Set'" "${log_dir}/nvme/nvme.log"
                log_cmd "nvme id-ns -H -n 1 /dev/nvme${nvmen}n1 | grep 'Bytes Read'" "${log_dir}/nvme/nvme.log"
                
                log_cmd "nvme get-feature -f 7 -s 0 -H /dev/nvme${nvmen}n1" "${log_dir}/nvme/nvme${nvmen}/nvme_info_detail.log"
                echo "======================" >> "${log_dir}/nvme/nvme${nvmen}/nvme_info_detail.log"
                log_cmd "nvme get-feature -f 7 -s 1 -H /dev/nvme${nvmen}n1" "${log_dir}/nvme/nvme${nvmen}/nvme_info_detail.log"
                echo "======================" >> "${log_dir}/nvme/nvme${nvmen}/nvme_info_detail.log"
                log_cmd "nvme id-ctrl -H /dev/nvme${nvmen}n1" "${log_dir}/nvme/nvme${nvmen}/nvme_info_detail.log"
                echo "======================" >> "${log_dir}/nvme/nvme${nvmen}/nvme_info_detail.log"
                log_cmd "nvme id-ns -n 1 -H /dev/nvme${nvmen}n1" "${log_dir}/nvme/nvme${nvmen}/nvme_info_detail.log"
                echo "======================" >> "${log_dir}/nvme/nvme${nvmen}/nvme_info_detail.log"
                log_cmd "nvme show-regs -H /dev/nvme${nvmen}n1" "${log_dir}/nvme/nvme${nvmen}/nvme_info_detail.log"
            fi
            
            # Always collect SMART and error logs
            log_cmd "nvme smart-log /dev/nvme${nvmen}n1" "${log_dir}/nvme/nvme${nvmen}/nvme_smartlog.log"
            log_cmd "nvme error-log /dev/nvme${nvmen}n1" "${log_dir}/nvme/nvme${nvmen}/nvme_errorlog.log"
            
        # Process SupremeRAID devices
        elif [[ ${nvme_node:11:3} == "gpd" ]]; then
            local nvmen=$(extract_device_num "$nvme_node" "gpd")
            
            if [ -z "$nvmen" ]; then
                continue
            fi
            
            device_count=$((device_count+1))
            show_progress $device_count $total_devices "Processing SupremeRAID devices"
            
            # Collect basic information
            echo "======================" >> "${log_dir}/nvme/nvme.log"
            echo "gpd${nvmen}_node: $(cat ${nvme_node} 2>/dev/null)" >> "${log_dir}/nvme/nvme.log"
            echo "gpd${nvmen}_nqn: $(cat /sys/class/block/gpd${nvmen}*/device/subsysnqn 2>/dev/null)" >> "${log_dir}/nvme/nvme.log"
            echo "gpd${nvmen}_address: $(cat /sys/class/block/gpd${nvmen}*/device/address 2>/dev/null)" >> "${log_dir}/nvme/nvme.log"
            echo "gpd${nvmen}_device_id: $(cat /sys/class/block/gpd${nvmen}*/device/device/device 2>/dev/null)" >> "${log_dir}/nvme/nvme.log"
            echo "gpd${nvmen}_vender_id: $(cat /sys/class/block/gpd${nvmen}*/device/device/vendor 2>/dev/null)" >> "${log_dir}/nvme/nvme.log"
            echo "gpd${nvmen}_queue_count: $(cat /sys/class/block/gpd${nvmen}*/device/queue_count 2>/dev/null)" >> "${log_dir}/nvme/nvme.log"
            echo "gpd${nvmen}_current_link_speed: $(cat /sys/class/block/gpd${nvmen}*/device/device/current_link_speed 2>/dev/null)" >> "${log_dir}/nvme/nvme.log"
            echo "gpd${nvmen}_current_link_width: $(cat /sys/class/block/gpd${nvmen}*/device/device/current_link_width 2>/dev/null)" >> "${log_dir}/nvme/nvme.log"
            echo "gpd${nvmen}_max_link_speed: $(cat /sys/class/block/gpd${nvmen}*/device/device/max_link_speed 2>/dev/null)" >> "${log_dir}/nvme/nvme.log"
            echo "gpd${nvmen}_max_link_width: $(cat /sys/class/block/gpd${nvmen}*/device/device/max_link_width 2>/dev/null)" >> "${log_dir}/nvme/nvme.log"
            
            # Create device-specific directory
            mkdir -p "${log_dir}/nvme/gpd${nvmen}"
            
            # Collect detailed SupremeRAID information if not in critical-only mode
            if [ "$critical_only" != "1" ]; then
                log_cmd "nvme id-ctrl -H /dev/gpd${nvmen} | grep 'ver '" "${log_dir}/nvme/nvme.log"
                log_cmd "nvme id-ctrl -H /dev/gpd${nvmen} | grep 'Data Set'" "${log_dir}/nvme/nvme.log"
                log_cmd "nvme id-ns -H -n 1 /dev/gpd${nvmen} | grep 'Bytes Read'" "${log_dir}/nvme/nvme.log"
                
                log_cmd "nvme get-feature -f 7 -s 0 -H /dev/gpd${nvmen}" "${log_dir}/nvme/gpd${nvmen}/nvme_info_detail.log"
                echo "======================" >> "${log_dir}/nvme/gpd${nvmen}/nvme_info_detail.log"
                log_cmd "nvme get-feature -f 7 -s 1 -H /dev/gpd${nvmen}" "${log_dir}/nvme/gpd${nvmen}/nvme_info_detail.log"
                echo "======================" >> "${log_dir}/nvme/gpd${nvmen}/nvme_info_detail.log"
                log_cmd "nvme id-ctrl -H /dev/gpd${nvmen}" "${log_dir}/nvme/gpd${nvmen}/nvme_info_detail.log"
                echo "======================" >> "${log_dir}/nvme/gpd${nvmen}/nvme_info_detail.log"
                log_cmd "nvme id-ns -n 1 -H /dev/gpd${nvmen}" "${log_dir}/nvme/gpd${nvmen}/nvme_info_detail.log"
                echo "======================" >> "${log_dir}/nvme/gpd${nvmen}/nvme_info_detail.log"
            fi
            
            # Always collect SMART and error logs
            log_cmd "nvme smart-log /dev/gpd${nvmen}" "${log_dir}/nvme/gpd${nvmen}/nvme_info_detail.log"
            log_cmd "nvme error-log /dev/gpd${nvmen}" "${log_dir}/nvme/gpd${nvmen}/nvme_errorlog.log"
        fi
    done
    
    show_progress 100 100 "NVMe device information collected"
    echo
}

# Collect NVMe LED information
function nvme_led_info() {
    local log_dir="$1"
    
    show_progress 0 100 "Collecting NVMe LED configuration information"
    
    # Skip if lspci is not available
    if ! which lspci &>/dev/null; then
        echo "lspci not found, skipping NVMe LED configuration" >> "${log_dir}/status.log"
        show_progress 100 100 "NVMe LED configuration collection skipped"
        echo
        return 1
    fi
    
    # Find server information
    local vendor_name=$(dmidecode -t system | awk -F': ' '/Manufacturer:/ {print $2}' 2>/dev/null)
    local server_product_name=$(dmidecode -t system | awk -F': ' '/Product Name:/ {print $2}' 2>/dev/null | tr ' ' '_')
    local server_pn=$(dmidecode -t system | awk -F': ' '/Product Name:/ {print $2}' 2>/dev/null)
    
    # Ensure we have a valid server product name
    if [ -z "$server_product_name" ]; then
        server_product_name="unknown_server"
    fi
    
    # Find all NVMe devices
    local NVME_DEVICES=$(lspci -d ::0108 | awk '{print $1}' 2>/dev/null)
    
    # Check if any NVMe devices were found
    if [ -z "$NVME_DEVICES" ]; then
        echo "No NVMe devices found" >> "${log_dir}/${server_product_name}.log"
        show_progress 100 100 "NVMe LED configuration collection skipped - no devices"
        echo
        return 1
    fi
    
    # Create base information file
    echo "vendor: ${vendor_name}" > "${log_dir}/${server_product_name}.log"
    echo "product: ${server_pn}" >> "${log_dir}/${server_product_name}.log"
    echo "led_bdf:" >> "${log_dir}/${server_product_name}.log"
    
    # Initialize yaml log files
    > "${log_dir}/${server_product_name}_yaml.log"
    > "${log_dir}/${server_product_name}_yaml_v2.log"
    
    # Process each NVMe device
    local i=0
    local device_count=0
    local total_devices=$(echo "$NVME_DEVICES" | wc -w)
    
    for BDF in $NVME_DEVICES; do
        device_count=$((device_count+1))
        show_progress $device_count $total_devices "Processing NVMe devices for LED configuration"
        
        echo "Processing NVMe device: $BDF" >> "${log_dir}/${server_product_name}.log"
        
        # Get the full path including root port using lspci -PP
        local FULL_PATH=$(lspci -s $BDF -PP | awk '{print $1}' 2>/dev/null)
        echo "Full path: $FULL_PATH" >> "${log_dir}/${server_product_name}.log"
        
        # Extract the parent (Root Port) from the path
        # Format is like "93:01.0/94:00.0/95:00.0/96:00.0"
        local ROOT_PORT=$(echo $FULL_PATH | awk -F'/' '{if (NF>=2) print $(NF-1); else print $1}' 2>/dev/null)
        echo "Root Port: $ROOT_PORT" >> "${log_dir}/${server_product_name}.log"
        
        # Convert Root Port to the required format (0x000950000)
        if [[ $ROOT_PORT =~ ([0-9a-f]+):([0-9a-f]+)\.([0-9a-f]+) ]]; then
            local BUS=${BASH_REMATCH[1]}
            local DEV=${BASH_REMATCH[2]}
            local FUNC=${BASH_REMATCH[3]}
            
            # Format the BDF as 0x0000BBDDFF (BB=bus, DD=device, FF=function)
            local FORMATTED_BDF=$(printf "0x000%02x%02x%02x" "0x$BUS" "0x$DEV" "0x$FUNC")
            echo "Formatted BDF: $FORMATTED_BDF" >> "${log_dir}/${server_product_name}.log"
            
            # Write to yaml logs
            echo "  - $FORMATTED_BDF # Slot ${i}" >> "${log_dir}/${server_product_name}_yaml.log"
            echo "  - $FORMATTED_BDF # Slot ${i}" >> "${log_dir}/${server_product_name}_yaml_v2.log"
        else
            echo "Error: Could not parse Root Port BDF format for $ROOT_PORT" >> "${log_dir}/${server_product_name}.log"
            # Fallback to original BDF if parsing fails
            local FALLBACK_BDF=$(echo "0x000${BDF}" | tr -d ":" | tr '.' '0')
            echo "  - $FALLBACK_BDF # Slot ${i}" >> "${log_dir}/${server_product_name}_yaml.log"
            echo "  - $FALLBACK_BDF # Slot ${i}" >> "${log_dir}/${server_product_name}_yaml_v2.log"
        fi
        
        i=$((i+1))
    done
    
    # Get the first Root Port for capability detection
    local FIRST_BDF=$(echo "$NVME_DEVICES" | head -n1)
    local FIRST_PATH=$(lspci -s $FIRST_BDF -PP | awk '{print $1}' 2>/dev/null)
    local FIRST_ROOT_PORT=$(echo $FIRST_PATH | awk -F'/' '{if (NF>=2) print $(NF-1); else print $1}' 2>/dev/null)
    
    # Skip if setpci is not available
    if ! which setpci &>/dev/null; then
        echo "setpci not found, skipping capability detection" >> "${log_dir}/${server_product_name}.log"
    else
        echo "Using Root Port $FIRST_ROOT_PORT for capability detection" >> "${log_dir}/${server_product_name}.log"
        
        # Get the capability pointer value at offset 0x34
        local Cap_Ptr_Val=$(setpci -s $FIRST_ROOT_PORT 0x34.b 2>/dev/null)
        
        # Extract the capability pointer address from the value
        local Cap_Ptr_Addr=$(setpci -s $FIRST_ROOT_PORT 0x"$Cap_Ptr_Val".b 2>/dev/null)
        
        # Loop through the capability list to find the PCIe capability
        local i=0
        while [ $i -lt 30 ]; do
            # Check if it's the PCIe capability
            if [[ $Cap_Ptr_Addr == "10" ]]; then
                # Get the Power State register and extract the indicator address
                local PWR_ADDR=$(printf "0x%x" $((0x$Cap_Ptr_Val + 0x19)))
                
                # Get the Attention State register and extract the indicator address
                local ATT_ADDR=$(printf "0x%x" $((0x$Cap_Ptr_Val + 0x18)))
                
                # Print the results
                echo "PWR_ADDR: $PWR_ADDR" >> "${log_dir}/${server_product_name}.log"
                echo "ATT_ADDR: $ATT_ADDR" >> "${log_dir}/${server_product_name}.log"
                
                # Exit the loop
                break
            fi
            
            # Get the next capability pointer address
            local Cap_ID=$Cap_Ptr_Val+$Cap_Ptr_Addr
            Cap_Ptr_Val=$(setpci -s $FIRST_ROOT_PORT 0x"$Cap_ID".b 2>/dev/null)
            Cap_Ptr_Addr=$(setpci -s $FIRST_ROOT_PORT 0x"$Cap_Ptr_Val".b 2>/dev/null)
            
            # Check if it's the end of the capability list
            if [[ $Cap_Ptr_Addr == 0 ]]; then
                echo "PCIe capability not found." >> "${log_dir}/${server_product_name}.log"
                break
            fi
            i=$((i+1))
        done
    fi
    
    show_progress 100 100 "NVMe LED configuration collected"
    echo
}

# Run log analysis if script is available
function log_analysis() {
    local log_dir="$1"
    local ANALYSIS_SCRIPT="./log_analysis.py"
    
    show_progress 0 100 "Running log analysis"
    
    if [ -f "$ANALYSIS_SCRIPT" ]; then
        if which python3 &>/dev/null; then
            # Run analysis script
            python3 "$ANALYSIS_SCRIPT" --log-dir="${log_dir}" --html --output "${log_dir}/graid_analysis_report.html" 2>/dev/null
            echo "Log analysis complete."
            
            # Move any generated reports to the log directory
            if [ -f "dmesg_detailed_report.txt" ]; then
                mv dmesg_detailed_report.txt "${log_dir}/"
            fi
            
            if [ -f "graid_analysis_report.html" ]; then
                mv graid_analysis_report.html "${log_dir}/"
            fi
            
            if [ -f "graid_analysis_report.txt" ]; then
                mv graid_analysis_report.txt "${log_dir}/"
            fi
        else
            echo "Python3 not found, skipping log analysis" >> "${log_dir}/status.log"
        fi
    else
        echo "Log analysis script not found: $ANALYSIS_SCRIPT" >> "${log_dir}/status.log"
    fi
    
    show_progress 100 100 "Log analysis completed"
    echo
}

# Compress logs into a tarball
function compress_log() {
    local log_dir="$1"
    local timestamp=$(date '+%Y-%m-%d')
    local tar_file="graid_log_${timestamp}.tar.gz"
    
    show_progress 0 100 "Compressing logs"
    
    # Check if the target compression file already exists
    if [ -f "$tar_file" ]; then
        echo "Target compression file $tar_file already exists."
        # Generate a unique filename with timestamp
        tar_file="graid_log_${timestamp}_$(date '+%H%M%S').tar.gz"
    fi
    
    # Copy script execution log to log directory first
    echo "----------------------------------------" >> "$output_log"
    echo "Finishing at: $(date)" >> "$output_log"
    
    # Compress the logs
    tar -czf "$tar_file" "${log_dir}" 2>/dev/null
    
    # Check if compression was successful
    if [ $? -eq 0 ]; then
        echo "Compression completed: $tar_file"
        
        # Calculate MD5 checksum
        calculate_checksum "$tar_file"
        
        # Delete original log files unless keep_temp_files is set
        if [ "$keep_temp_files" != "1" ]; then
            rm -rf "${log_dir}"
            # Indicate that output_log is no longer available
            output_log="/dev/null"
            echo "Temporary files removed"
        else
            echo "Temporary files kept in ${log_dir}"
        fi
    else
        echo "Compression failed. Log files remain in ${log_dir}"
    fi
    
    show_progress 100 100 "Logs compressed: $tar_file"
    echo
    
    # Reset locale
    unset LC_ALL
}

# Collect detailed Device Mapper information
function collect_dm_info() {
    local log_dir="$1"
    mkdir -p "${log_dir}/dm_info"

    show_progress 0 100 "Collecting Device Mapper information"

    # Check dmsetup is available

    if ! which dmsetup &>/dev/null; then
        echo "dmsetup command not available, skipping DM information collection" >> "${log_dir}/dm_info/status.log"
        show_progress 100 100 "Device Mapper information collection skipped"
        echo
        return 0
    fi

    # basic DM info
    log_cmd "dmsetup info -c" "${log_dir}/dm_info/dm_info.log"
    log_cmd "dmsetup table" "${log_dir}/dm_info/dm_table.log"
    log_cmd "dmsetup status" "${log_dir}/dm_info/dm_status.log"
    log_cmd "dmsetup ls --tree" "${log_dir}/dm_info/dm_tree.log"

    # DM statisic, check available
    if dmsetup stats &>/dev/null; then
        log_cmd "dmsetup stats" "${log_dir}/dm_info/dm_stats.log"
    else
        echo "dmsetup stats not supported on this system" >> "${log_dir}/dm_info/dm_stats.log"
    fi

    # dmstats command check
    if which dmstats &>/dev/null; then
        log_cmd "dmstats list" "${log_dir}/dm_info/dmstats_list.log"

        if dmstats print &>/dev/null; then
            log_cmd "dmstats print" "${log_dir}/dm_info/dmstats_print.log"
        else
            echo "dmstats print not supported or no statistics available" >> "${log_dir}/dm_info/dmstats_print.log"
        fi
    else
        echo "dmstats command not available" >> "${log_dir}/dm_info/dmstats_status.log"
    fi

    # detail infomation
    if [ "$critical_only" != "1" ]; then
        local dm_devices=$(dmsetup ls 2>/dev/null | awk '{print $1}')
        local device_count=0
        local total_devices=$(echo "$dm_devices" | wc -l)

        if [ -n "$dm_devices" ]; then
            mkdir -p "${log_dir}/dm_info/devices"

            for device in $dm_devices; do
                device_count=$((device_count+1))
                show_progress $device_count $total_devices "Processing DM device: $device"

                local device_log="${log_dir}/dm_info/devices/${device}.log"

                echo "Device: $device" > "$device_log"
                echo "===========================================" >> "$device_log"

                log_cmd "dmsetup info $device" "$device_log"
                log_cmd "dmsetup table $device" "$device_log"
                log_cmd "dmsetup status $device" "$device_log"
                log_cmd "dmsetup deps $device" "$device_log"

                # get echo device
                local target_type=$(dmsetup table $device 2>/dev/null | awk '{print $3}')
                echo "Target Type: $target_type" >> "$device_log"
                echo "===========================================" >> "$device_log"

                
                case "$target_type" in
                    "multipath")
                        if which multipath &>/dev/null; then
                            log_cmd "multipath -ll $device" "$device_log"
                        else
                            echo "multipath command not available" >> "$device_log"
                        fi
                        ;;
                    "crypt")
                        if which cryptsetup &>/dev/null; then
                            log_cmd "cryptsetup status $device" "$device_log"
                        else
                            echo "cryptsetup command not available" >> "$device_log"
                        fi
                        ;;
                    "snapshot"|"snapshot-origin"|"thin"|"thin-pool"|"cache"|"cache-pool"|"mirror")
                        log_cmd "dmsetup status --verbose $device" "$device_log"
                        ;;
                    *)
                        echo "No target-specific commands for $target_type" >> "$device_log"
                        ;;
                esac

                echo "===========================================" >> "$device_log"
                echo "Underlying Block Device Information:" >> "$device_log"
                log_cmd "ls -l /dev/mapper/$device" "$device_log"

                if which blockdev &>/dev/null; then
                    log_cmd "blockdev --getsize64 /dev/mapper/$device" "$device_log"
                    log_cmd "blockdev --getbsz /dev/mapper/$device" "$device_log"
                    log_cmd "blockdev --getro /dev/mapper/$device" "$device_log"
                else
                    echo "blockdev command not available" >> "$device_log"
                fi
            done
        else
            echo "No DM devices found" >> "${log_dir}/dm_info/status.log"
        fi
    fi




    # LVM information (if available)
    if which vgs &>/dev/null; then
        mkdir -p "${log_dir}/dm_info/lvm"

        # Basic LVM information
        log_cmd "pvs" "${log_dir}/dm_info/lvm/pvs.log"
        log_cmd "vgs" "${log_dir}/dm_info/lvm/vgs.log"
        log_cmd "lvs" "${log_dir}/dm_info/lvm/lvs.log"

        # Detailed LVM information
        log_cmd "pvs -v" "${log_dir}/dm_info/lvm/pvs_verbose.log"
        log_cmd "vgs -v" "${log_dir}/dm_info/lvm/vgs_verbose.log"
        log_cmd "lvs -v" "${log_dir}/dm_info/lvm/lvs_verbose.log"

        # LVM configuration
        log_cmd "lvmconfig" "${log_dir}/dm_info/lvm/lvmconfig.log"

        # LVM archive and backup
        cp -a /etc/lvm "${log_dir}/dm_info/lvm/etc_lvm" 2>/dev/null
    fi

    # Multipath information (if available)
    if which multipath &>/dev/null; then
       mkdir -p "${log_dir}/dm_info/multipath"
        
        log_cmd "multipath -ll" "${log_dir}/dm_info/multipath/multipath_ll.log"
        log_cmd "multipath -v3" "${log_dir}/dm_info/multipath/multipath_v3.log"
        
        if which multipathd &>/dev/null; then
            log_cmd "multipathd show paths" "${log_dir}/dm_info/multipath/multipathd_paths.log"
            log_cmd "multipathd show maps" "${log_dir}/dm_info/multipath/multipathd_maps.log"
            log_cmd "multipathd show config" "${log_dir}/dm_info/multipath/multipathd_config.log"
        else
            echo "multipathd command not available" >> "${log_dir}/dm_info/multipath/status.log"
        fi
        
        cp -a /etc/multipath.conf "${log_dir}/dm_info/multipath/" 2>/dev/null
    else
        echo "Multipath commands not available" >> "${log_dir}/dm_info/multipath_status.log"
    
    fi

    # SCSI information for underlying devices
    mkdir -p "${log_dir}/dm_info/scsi"

    if which lsscsi &>/dev/null; then
        log_cmd "lsscsi" "${log_dir}/dm_info/scsi/lsscsi.log"
        log_cmd "lsscsi -l" "${log_dir}/dm_info/scsi/lsscsi_long.log"
        log_cmd "lsscsi -H" "${log_dir}/dm_info/scsi/lsscsi_hosts.log"
    else
        echo "lsscsi command not available, using alternatives" >> "${log_dir}/dm_info/scsi/status.log"
        # 替代方案
        log_cmd "ls -la /sys/class/scsi_host/" "${log_dir}/dm_info/scsi/scsi_hosts.log"
        log_cmd "ls -la /sys/class/scsi_device/" "${log_dir}/dm_info/scsi/scsi_devices.log"
        log_cmd "cat /proc/scsi/scsi" "${log_dir}/dm_info/scsi/proc_scsi.log"
    fi



    # Collect udev information for DM devices
    if which udevadm &>/dev/null; then
        mkdir -p "${log_dir}/dm_info/udev"
	    if compgen -G "/dev/dm-*" > /dev/null; then
            local dm_devs=$(ls -1 /dev/dm-* 2>/dev/null)
            
            for dev in $dm_devs; do
                local dev_name=$(basename $dev)
                log_cmd "udevadm info --query=all --name=$dev" "${log_dir}/dm_info/udev/${dev_name}_info.log"
            done
        else
            echo "No DM devices found in /dev/" >> "${log_dir}/dm_info/udev/status.log"
        fi
    else
        echo "udevadm command not available" >> "${log_dir}/dm_info/udev_status.log"
    fi
    
    show_progress 100 100 "Device Mapper information collected"
    echo
}


function check_for_update() {
    if [ "$skip_update" == "1" ]; then
        echo "Skipping update check (--no-update flag set)"
        return 1
    fi
    if [ -f "/tmp/.just_updated" ]; then
        LAST_UPDATE_TIME=$(cat "/tmp/.just_updated")
        CURRENT_TIME=$(date +%s)
        if [ $((CURRENT_TIME - LAST_UPDATE_TIME)) -lt 300 ]; then
            echo "Script was just updated. Skipping update check."
            return 1
        fi
    fi

    if ! which curl &>/dev/null && ! which wget &>/dev/null; then
        echo "Warning: Neither curl nor wget found. Cannot check for updates."
        return 1
    fi

    if ! which md5sum &>/dev/null; then
        echo "Warning: md5sum not found. Cannot verify updates."
        return 1
    fi

    if ! check_network_availability; then
        echo "Warning: Network is not available. Skipping update check."
        return 1
    fi

    echo "Checking for script updates..."

    CURRENT_MD5=$(md5sum "$0" | awk '{print $1}')

    if which wget &>/dev/null; then
        REMOTE_MD5=$(wget -q -O - "${UPDATE_MD5_URL}")
        
    else
        REMOTE_MD5=$(curl -s "${UPDATE_MD5_URL}")
    fi

    if [ -z "$REMOTE_MD5" ]; then
        echo "Warning: Could not retrieve remote MD5. Update check failed."
        return 1
    fi
    # echo "$CURRENT_MD5" "$REMOTE_MD5"
    if [ "$CURRENT_MD5" != "$REMOTE_MD5" ] || [ "$enforce_update" == "1" ]; then
        echo "Update available. Current version: $VERSION"
        return 0
    else
        echo "No update available. Current version: $VERSION"
        return 1
    fi
}

function check_network_availability() {
    local test_host="download.graidtech.com"
    local timeout=3 
    echo "Checking network connectivity..."
    
    if ping -c 1 -W $timeout $test_host &>/dev/null; then
        echo "Network is available."
        return 0
    fi
    
    echo "Network is not available."
    return 1
}


function update_script() {
    echo "Downloading script update..."

    BACKUP_FILE="${0}.backup"
    cp "$0" "$BACKUP_FILE"
    echo "Backup created: $BACKUP_FILE"
    echo "Downloading from: ${UPDATE_SCRIPT_URL}"
    local timeout=30 
    if which wget &>/dev/null; then
        wget -q -T "$timeout" "${UPDATE_SCRIPT_URL}" -O "$0.new"
        
    else
        curl -s --connect-timeout "$timeout" "${UPDATE_SCRIPT_URL}" -o "$0.new"
    fi

    if [ ! -s "$0.new" ]; then
        echo "Error: Downloaded file is empty or download failed."
        return 1
    fi

    NEW_MD5=$(md5sum "$0.new" | awk '{print $1}')
    
    if which wget &>/dev/null; then
        REMOTE_MD5=$(wget -q -O - "${UPDATE_MD5_URL}")
    else
        REMOTE_MD5=$(curl -s "${UPDATE_MD5_URL}")
    fi

    # echo "$NEW_MD5" "$REMOTE_MD5"

    if [ "$NEW_MD5" != "$REMOTE_MD5" ]; then
        echo "Error: Downloaded file integrity check failed."
        rm "$0.new"
        return 1
    fi

    chmod +x "$0.new"
    mv "$0.new" "$0"
    echo "Script updated successfully. Restarting..."
    date +%s > "$LAST_UPDATE_CHECK"
    exec "$(readlink -f "$0")" "$@"

}

function collect_nfs_info() {
    local log_dir="$1"
    mkdir -p "${log_dir}/nfs"
    
    show_progress 0 100 "Collecting NFS information"
    

    if systemctl list-unit-files | grep -q nfs-server; then
        echo "NFS server detected" >> "${log_dir}/nfs/nfs_status.log"
        systemctl status nfs-server >> "${log_dir}/nfs/nfs_status.log" 2>&1
    else
        echo "NFS server not detected" >> "${log_dir}/nfs/nfs_status.log"
    fi
    

    log_cmd "cat /etc/exports" "${log_dir}/nfs/exports.log"
    log_cmd "cat /etc/nfsmount.conf" "${log_dir}/nfs/nfsmount.log"
    log_cmd "cat /etc/idmapd.conf" "${log_dir}/nfs/idmapd.log"
    

    log_cmd "mount | grep nfs" "${log_dir}/nfs/nfs_mounts.log"
    log_cmd "showmount -e" "${log_dir}/nfs/exports_active.log"
    log_cmd "showmount -a" "${log_dir}/nfs/clients.log"
    

    log_cmd "nfsstat" "${log_dir}/nfs/nfsstat.log"
    log_cmd "nfsstat -l" "${log_dir}/nfs/nfsstat_list.log"
    log_cmd "nfsstat -s" "${log_dir}/nfs/nfsstat_server.log"
    log_cmd "nfsstat -c" "${log_dir}/nfs/nfsstat_client.log"
    

    log_cmd "rpcinfo -p" "${log_dir}/nfs/rpcinfo.log"
    

    cp -a /var/log/nfs* "${log_dir}/nfs/" 2>/dev/null
    

    if [ -f /proc/fs/nfsd/versions ]; then
        log_cmd "cat /proc/fs/nfsd/versions" "${log_dir}/nfs/kernel_versions.log"
    fi
    

    if [ -f /proc/mounts ]; then
        log_cmd "cat /proc/mounts | grep nfs" "${log_dir}/nfs/proc_mounts.log"
    fi
    

    if which journalctl &>/dev/null; then
        log_cmd "journalctl -u nfs-server --since '24 hours ago'" "${log_dir}/nfs/journal_nfs_server.log"
        log_cmd "journalctl -u nfs-client --since '24 hours ago'" "${log_dir}/nfs/journal_nfs_client.log"
    fi
    
    show_progress 100 100 "NFS information collected"
    echo
}

function collect_samba_info() {
    local log_dir="$1"
    mkdir -p "${log_dir}/samba"
    
    show_progress 0 100 "Collecting Samba information"
    

    if systemctl list-unit-files | grep -q smb; then
        echo "Samba server detected" >> "${log_dir}/samba/samba_status.log"
        systemctl status smb >> "${log_dir}/samba/samba_status.log" 2>&1
    else
        echo "Samba server not detected" >> "${log_dir}/samba/samba_status.log"
    fi
    

    log_cmd "cat /etc/samba/smb.conf" "${log_dir}/samba/smb_conf.log"
    

    if which smbstatus &>/dev/null; then
        log_cmd "smbstatus" "${log_dir}/samba/smbstatus.log"
        log_cmd "smbstatus -S" "${log_dir}/samba/smbstatus_shares.log"
        log_cmd "smbstatus -p" "${log_dir}/samba/smbstatus_processes.log"
        log_cmd "smbstatus -B" "${log_dir}/samba/smbstatus_byterange.log"
    fi
    
    if which tsmb-status &>/dev/null; then
        log_cmd "tsmb-status -v" "${log_dir}/samba/tsmb-version.log"
        log_cmd "tsmb-status stats" "${log_dir}/samba/tsmb-status.log"
    fi

    if which smbclient &>/dev/null; then
        log_cmd "smbclient -L localhost -N" "${log_dir}/samba/shares_list.log"
    fi
    

    if which pdbedit &>/dev/null; then
        log_cmd "pdbedit -L" "${log_dir}/samba/users.log"
    fi
    
    cp -a /var/log/samba/* "${log_dir}/samba/" 2>/dev/null
    
    cp -a /var/log/tsmb/* "${log_dir}/tsmb/" 2>/dev/null

    if which lsof &>/dev/null; then
        log_cmd "lsof -i | grep smb" "${log_dir}/samba/lsof_smb.log"
    fi
    

    if which journalctl &>/dev/null; then
        log_cmd "journalctl -u smb --since '24 hours ago'" "${log_dir}/samba/journal_smb.log"
        log_cmd "journalctl -u nmb --since '24 hours ago'" "${log_dir}/samba/journal_nmb.log"
    fi
    
    log_cmd "mount | grep cifs" "${log_dir}/samba/cifs_mounts.log"
    
    show_progress 100 100 "Samba information collected"
    echo
}


# Create a basic summary file
function create_summary() {
    local log_dir="$1"
    local summary_file="${log_dir}/basic.log"
    
    show_progress 0 100 "Creating system summary"
    
    # Server information
    local server_manufacturer=$(dmidecode -t system | grep Manufacturer | cut -f 2 -d ":" | awk '{$1=$1}1' 2>/dev/null)
    local server_model_name=$(dmidecode -t system | grep 'Product Name' | cut -f 2 -d ":" | awk '{$1=$1}1' 2>/dev/null)
    
    # CPU information
    local cpu_model_name=$(lscpu | grep 'Model name' | cut -f 2 -d ":" | awk '{$1=$1}1' 2>/dev/null)
    local cpu_socket=$(lscpu | grep ^Socket | uniq | awk '{print $2}' 2>/dev/null)
    local cpu_count=$(lscpu | grep ^Core | uniq | awk '{print $4}' 2>/dev/null)
    
    # Memory information
    local memory_manufacturer=$(dmidecode -t memory | grep 'Manufacturer' | grep -v 'Unknown' | head -n 1 | cut -f 2 -d ":" | awk '{$1=$1}1' 2>/dev/null)
    local memory_part=$(dmidecode -t memory | grep 'Part Number' | grep -v 'Unknown' | head -n 1 | cut -f 2 -d ":" | awk '{$1=$1}1' 2>/dev/null)
    local memory_count=$(dmidecode -t 17 | grep "Memory Technology: DRAM" | wc -l 2>/dev/null)
    
    # OS information
    local os=$(cat /etc/os-release 2>/dev/null | grep "^PRETTY_NAME=*" | cut -f 2 -d "=" | awk '{$1=$1}1')
    
    # Security information
    local secureboot=$(mokutil --sb-state 2>/dev/null)
    
    # Write summary to file
    echo "======== System Summary ========" > "$summary_file"
    echo "ServerVendor: $server_manufacturer" >> "$summary_file"
    echo "ServerModel: $server_model_name" >> "$summary_file"
    echo "CPU: $cpu_model_name x $cpu_socket" >> "$summary_file"
    echo "Memory: $memory_manufacturer $memory_part x $memory_count" >> "$summary_file"
    echo "Secureboot: $secureboot" >> "$summary_file"
    echo "SME: $(dmesg | grep -i sme)" >> "$summary_file"
    echo "SEV: $(dmesg | grep -i sev)" >> "$summary_file"
    echo "OS: $os" >> "$summary_file"
    echo "Kernel version: $(uname -r)" >> "$summary_file"
    
    # Add GPU information if available
    if which nvidia-smi &>/dev/null; then
        echo "NVcard Status:" >> "$summary_file"
        nvidia-smi --query-gpu=index,name,serial,pcie.link.gen.current,pcie.link.width.current --format=csv >> "$summary_file"
    fi
    
    # Add DKMS status
    echo "DKMS status:" >> "$summary_file"
    dkms status >> "$summary_file" 2>/dev/null
    
    # Add SupremeRAID information if available
    if which graidctl &>/dev/null; then
        echo "SupremeRAID info:" >> "$summary_file"
        graidctl version >> "$summary_file" 2>/dev/null
        graid-mgr version >> "$summary_file" 2>/dev/null
        graidctl desc lic >> "$summary_file" 2>/dev/null
    fi
    
    # Add detailed system information
    dmidecode -t 1 >> "$summary_file" 2>/dev/null
    
    show_progress 100 100 "System summary created"
    echo
}

#######################
# Main Script Execution
#######################

# Parse command line options
while getopts ":hVo:ncdSkyvBFMUE" option; do
    case "$option" in
        h) # Display help
            print_help
            exit 0
            ;;
        V) # Display version
            version
            exit 0
            ;;
        o) # Set output directory
            foldname="$OPTARG"
            ;;
        n) # Skip heavy operations
            no_heavy_ops=1
            ;;
        c) # Collect only critical logs
            critical_only=1
            ;;
        d) # Dry run
            dry_run=1
            ;;
        k) # Keep temporary files
            keep_temp_files=1
            ;;
        v) # Verbose output
            verbose=1
            ;;
        y) # Accept disclaimer
            accept_disclaimer=1
            ;;
        S) # skip sosreport
            create_sosreport=0
            ;;
        B) # skip beegfs
            create_beegfs=0
            ;;
        F) # skip NFS
            create_nfs=0
            ;;
        M) # skip SMBA
            create_smba=0
            ;;
        U) # skip update check
            skip_update=1
            ;;
        E) # disable enforce update
            enforce_update=0
            ;;
        :) # Missing argument
            echo "Error: Option -$OPTARG requires an argument."
            print_help
            exit 1
            ;;
        \?) # Unknown option
            echo "Error: Invalid option -$OPTARG"
            print_help
            exit 1
            ;;
    esac
done

# Check if running as root
if [[ $(id -u) != "0" ]]; then
    echo "Error: This script must be run as root or with sudo."
    exit 1
fi

if [ "$auto_update" == "1" ]; then
    if check_for_update; then
        update_script "$@"
    fi
fi


# Show disclaimer and get confirmation
show_disclaimer

# Check for required dependencies
check_dependencies

# Setup output directory if not specified
if [ -z "$foldname" ]; then
    timestamp=$(date '+%Y%m%d')
    foldname="logs-$(hostname)-${timestamp}"
fi

# Clean up any existing files from previous runs
rm -rf graid_log_*.tar 2>/dev/null
rm -rf ./${foldname}/ 2>/dev/null
mkdir -p ./${foldname}/

# Create a log file for the script's own output
output_log="${foldname}/script_execution.log"
touch "$output_log"

# Log script start
echo "Graid Log Collection Tool" | tee -a "$output_log"
echo "Version: $VERSION" | tee -a "$output_log"
echo "Started at: $(date)" | tee -a "$output_log"
echo "Running on host: $(hostname)" | tee -a "$output_log"
echo "Output directory: ${foldname}" | tee -a "$output_log"
echo "----------------------------------------" | tee -a "$output_log"

# Begin collection process
# 0 

# 1. List PCI devices and create summary
if [ "$dry_run" != "1" ]; then
    echo "Scanning PCI devices..."
    list_pci_passthrough >> "${foldname}/pci_passthrough_list.log"
    print_pci_devs "${foldname}/print_pci_devs_list.log"
fi

# 2. Collect basic system information
get_basic_info "$foldname"

# 3. Collect system logs
collect_system_logs "$foldname"

# 4. Collect resource usage information
collect_resource_usage "$foldname"

# 5. Collect network information
collect_network_info "$foldname"

# 5.5 Collect detailed Device Mapper information
collect_dm_info "$foldname"

# 6. Collect ParallelFileSystem information
if [ "$collect_beegfs" == "1" ]; then
    collect_beegfs_info "$foldname"
fi

# 6.1. Collect NFS information
if [ "$collect_nfs" == "1" ]; then
    collect_nfs_info "$foldname"
fi

# 6.2. Collect NFS information
if [ "$collect_samba" == "1" ]; then
    collect_samba_info "$foldname"
fi

# 7. Collect SupremeRAID information
collect_graid_info "$foldname"

# 8. Collect NVMe information (if not in minimal mode)
if [ "$critical_only" != "1" ]; then
    get_nvme_info "$foldname"
    nvme_led_info "$foldname"
fi

# 9. Create summary file
create_summary "$foldname"

# 10. Run log analysis if not in minimal mode
if [ "$critical_only" != "1" ]; then
    log_analysis "$foldname"
fi

# 11. Create sosreport if requested
if [ "$create_sosreport" == "1" ]; then
    if which sosreport &>/dev/null; then
        mkdir -p "${foldname}/sosreport"
        echo "Creating sosreport (this may take some time)..."
        if which sos &>/dev/null; then
            sos report -a --batch --tmp-dir="${foldname}/sosreport" &>> "$output_log"
        else
            sosreport -a --batch --tmp-dir="${foldname}/sosreport" &>> "$output_log"
        fi
    else
        echo "sosreport command not found, skipping sosreport creation" | tee -a "$output_log"
    fi
fi

# 12. Compress log files
compress_log "$foldname"

# Log script completion
if [ "$keep_temp_files" == "1" ] || [ "$output_log" != "/dev/null" ]; then
    echo "----------------------------------------" >> "$output_log" 2>/dev/null
    echo "Script completed at: $(date)" >> "$output_log" 2>/dev/null
fi

echo "----------------------------------------"
echo "Script completed at: $(date)"
echo "Thank you for using the Graid Log Collection Tool!"
echo "Please upload the compressed log file to Graid support team for analysis."

# Collect NVMe LED information
function nvme_led_info() {
    local log_dir="$1"
    
    show_progress 0 100 "Collecting NVMe LED configuration information"
    
    # Skip if lspci is not available
    if ! which lspci &>/dev/null; then
        echo "lspci not found, skipping NVMe LED configuration" >> "${log_dir}/status.log"
        show_progress 100 100 "NVMe LED configuration collection skipped"
        echo
        return 1
    fi
    
    # Find server information
    local vendor_name=$(dmidecode -t system | awk -F': ' '/Manufacturer:/ {print $2}' 2>/dev/null)
    local server_product_name=$(dmidecode -t system | awk -F': ' '/Product Name:/ {print $2}' 2>/dev/null | tr ' ' '_')
    local server_pn=$(dmidecode -t system | awk -F': ' '/Product Name:/ {print $2}' 2>/dev/null)
    
    # Ensure we have a valid server product name
    if [ -z "$server_product_name" ]; then
        server_product_name="unknown_server"
    fi
    
    # Find all NVMe devices
    local NVME_DEVICES=$(lspci -d ::0108 | awk '{print $1}' 2>/dev/null)
    
    # Check if any NVMe devices were found
    if [ -z "$NVME_DEVICES" ]; then
        echo "No NVMe devices found" >> "${log_dir}/${server_product_name}.log"
        show_progress 100 100 "NVMe LED configuration collection skipped - no devices"
        echo
        return 1
    fi
    
    # Create base information file
    echo "vendor: ${vendor_name}" > "${log_dir}/${server_product_name}.log"
    echo "product: ${server_pn}" >> "${log_dir}/${server_product_name}.log"
    echo "led_bdf:" >> "${log_dir}/${server_product_name}.log"
    
    # Initialize yaml log files
    > "${log_dir}/${server_product_name}_yaml.log"
    > "${log_dir}/${server_product_name}_yaml_v2.log"
    
    # Process each NVMe device
    local i=0
    local device_count=0
    local total_devices=$(echo "$NVME_DEVICES" | wc -w)
    
    for BDF in $NVME_DEVICES; do
        device_count=$((device_count+1))
        show_progress $device_count $total_devices "Processing NVMe devices for LED configuration"
        
        echo "Processing NVMe device: $BDF" >> "${log_dir}/${server_product_name}.log"
        
        # Get the full path including root port using lspci -PP
        local FULL_PATH=$(lspci -s $BDF -PP | awk '{print $1}' 2>/dev/null)
        echo "Full path: $FULL_PATH" >> "${log_dir}/${server_product_name}.log"
        
        # Extract the parent (Root Port) from the path
        # Format is like "93:01.0/94:00.0/95:00.0/96:00.0"
        local ROOT_PORT=$(echo $FULL_PATH | awk -F'/' '{if (NF>=2) print $(NF-1); else print $1}' 2>/dev/null)
        echo "Root Port: $ROOT_PORT" >> "${log_dir}/${server_product_name}.log"
        
        # Convert Root Port to the required format (0x0000950000)
        if [[ $ROOT_PORT =~ ([0-9a-f]+):([0-9a-f]+)\.([0-9a-f]+) ]]; then
            local BUS=${BASH_REMATCH[1]}
            local DEV=${BASH_REMATCH[2]}
            local FUNC=${BASH_REMATCH[3]}
            
            # Format the BDF as 0x00000BBDDFF (BB=bus, DD=device, FF=function)
            local FORMATTED_BDF=$(printf "0x0000%02x%02x%02x" "0x$BUS" "0x$DEV" "0x$FUNC")
            echo "Formatted BDF: $FORMATTED_BDF" >> "${log_dir}/${server_product_name}.log"
            
            # Write to yaml logs
            echo "  - $FORMATTED_BDF # Slot ${i}" >> "${log_dir}/${server_product_name}_yaml.log"
            echo "  - $FORMATTED_BDF # Slot ${i}" >> "${log_dir}/${server_product_name}_yaml_v2.log"
        else
            echo "Error: Could not parse Root Port BDF format for $ROOT_PORT" >> "${log_dir}/${server_product_name}.log"
            # Fallback to original BDF if parsing fails
            local FALLBACK_BDF=$(echo "0x0000${BDF}" | tr -d ":" | tr '.' '0')
            echo "  - $FALLBACK_BDF # Slot ${i}" >> "${log_dir}/${server_product_name}_yaml.log"
            echo "  - $FALLBACK_BDF # Slot ${i}" >> "${log_dir}/${server_product_name}_yaml_v2.log"
        fi
        
        i=$((i+1))
    done
    
    # Get the first Root Port for capability detection
    local FIRST_BDF=$(echo "$NVME_DEVICES" | head -n1)
    local FIRST_PATH=$(lspci -s $FIRST_BDF -PP | awk '{print $1}' 2>/dev/null)
    local FIRST_ROOT_PORT=$(echo $FIRST_PATH | awk -F'/' '{if (NF>=2) print $(NF-1); else print $1}' 2>/dev/null)
    
    # Skip if setpci is not available
    if ! which setpci &>/dev/null; then
        echo "setpci not found, skipping capability detection" >> "${log_dir}/${server_product_name}.log"
    else
        echo "Using Root Port $FIRST_ROOT_PORT for capability detection" >> "${log_dir}/${server_product_name}.log"
        
        # Get the capability pointer value at offset 0x34
        local Cap_Ptr_Val=$(setpci -s $FIRST_ROOT_PORT 0x34.b 2>/dev/null)
        
        # Extract the capability pointer address from the value
        local Cap_Ptr_Addr=$(setpci -s $FIRST_ROOT_PORT 0x"$Cap_Ptr_Val".b 2>/dev/null)
        
        # Loop through the capability list to find the PCIe capability
        local i=0
        while [ $i -lt 30 ]; do
            # Check if it's the PCIe capability
            if [[ $Cap_Ptr_Addr == "10" ]]; then
                # Get the Power State register and extract the indicator address
                local PWR_ADDR=$(printf "0x%x" $((0x$Cap_Ptr_Val + 0x19)))
                
                # Get the Attention State register and extract the indicator address
                local ATT_ADDR=$(printf "0x%x" $((0x$Cap_Ptr_Val + 0x18)))
                
                # Print the results
                echo "PWR_ADDR: $PWR_ADDR" >> "${log_dir}/${server_product_name}.log"
                echo "ATT_ADDR: $ATT_ADDR" >> "${log_dir}/${server_product_name}.log"
                
                # Exit the loop
                break
            fi
            
            # Get the next capability pointer address
            local Cap_ID=$Cap_Ptr_Val+$Cap_Ptr_Addr
            Cap_Ptr_Val=$(setpci -s $FIRST_ROOT_PORT 0x"$Cap_ID".b 2>/dev/null)
            Cap_Ptr_Addr=$(setpci -s $FIRST_ROOT_PORT 0x"$Cap_Ptr_Val".b 2>/dev/null)
            
            # Check if it's the end of the capability list
            if [[ $Cap_Ptr_Addr == 0 ]]; then
                echo "PCIe capability not found." >> "${log_dir}/${server_product_name}.log"
                break
            fi
            i=$((i+1))
        done
    fi
    
    show_progress 100 100 "NVMe LED configuration collected"
    echo
}
