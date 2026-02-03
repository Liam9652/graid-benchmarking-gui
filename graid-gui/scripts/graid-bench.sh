#!/bin/bash

export LC_ALL=C

# Separate debug trace (set -x) to debug.log instead of mixing with audit log
DEBUG_LOG_FILE="./debug.log"
LOG_FILE="./output.log"

# Open fd 3 for debug log and redirect xtrace there
exec 3>> "$DEBUG_LOG_FILE"
export BASH_XTRACEFD=3
set -x

# Main output goes to output.log (audit log only)
exec > >(tee -a "$LOG_FILE") 2>&1

# Check the running shell and re-run with bash if necessary
if [ "$BASH" != "/bin/bash" ]; then
	    /bin/bash "$0" "$@"
	        exit $?
fi

trap "trap - SIGTERM && kill -- -$$ 2>/dev/null" SIGINT SIGTERM EXIT

log_info() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"
}


Help()
{
   # Display Help
   echo "Add description of the script functions here."
   echo
   echo "Syntax: scriptTemplate [-h|V]"
   echo "options:"
   echo "h     Print this Help."
   echo "V     Print software version and exit."
   echo
}

version()
{
    echo "Version: 0.1.5-20240412" 
    #add sanitize function
}

while getopts "hV" option; do
   case "$option" in
      h) # display Help
         Help
         exit;;
      V) # display version
         version
         exit;;
     \?) # incorrect option
         echo "Error: Invalid option"
         exit;;
   esac
done

function check_root_user() {
    if [[ $(whoami) != "root" ]]; then
        echo "STATUS: ERROR: Script must be run as root."
        echo "Must be root or using sudo"
        sleep 1
        exit 1
    fi
}

get_distro() {
    if [ -f /etc/os-release ]; then
        source /etc/os-release
        echo "$ID" | tr '[:upper:]' '[:lower:]'
    else
        echo "STATUS: ERROR: /etc/os-release does not exist."
        echo "Error: /etc/os-release does not exist."
        sleep 1
        exit 1
    fi
}


function check_dependencies() {
    log_info "Checking dependencies..."
    deps=0

    # Check if LOG_COMPACT is true
    if [[ "${LOG_COMPACT}" == "true" ]]; then
        # echo "LOG_COMPACT is set to true. Skipping atop check."
        skip_atop=true
        echo '13'
    else
        skip_atop=false
    fi


    for name in fio jq nvme graidctl atop nvidia-smi pip3 bc
        do
        if [[ $(which $name 2>/dev/null) ]]; then
            continue
        fi
        
        # Skip atop if LOG_COMPACT is true
        if [[ "$name" == "atop" ]] && [[ "$skip_atop" == "true" ]]; then
            continue
        fi

        case $(uname -s) in
            Linux)
                DISTRO_ID=$(get_distro)
                case $DISTRO_ID in
                    centos|almalinux|rocky|rhel|ol)
                        package_name=$(case $name in
                            fio) echo "fio";;
                            jq) echo "jq";;
                            nvme) echo "nvme-cli";;
                            atop) echo "atop";;
                            nvidia-smi) echo "nvidia-smi";;
                            pip3) echo "python3-pip";;
                            bc) echo "bc";;
                            *) echo "";;
                        esac)
                        if [[ "$name" == "pip3" ]]; then
                            pack='dnf install'
                        else    
                            pack='yum install'
                        fi
                        ;;
                    ubuntu|debian)
                        package_name=$(case $name in
                            fio) echo "fio";;
                            jq) echo "jq";;
                            nvme) echo "nvme-cli";;
                            atop) echo "atop";;
                            nvidia-smi) echo "nvidia-smi";;
                            pip3) echo "python3-pip";;
                            bc) echo "bc";;
                            *) echo "";;
                        esac)
                        pack='apt install'
                        ;;
                    sled|sles|opensuse-leap)
                        package_name=$(case $name in
                            fio) echo "fio";;
                            jq) echo "jq";;
                            nvme) echo "nvme-cli";;
                            atop) echo "atop";;
                            nvidia-smi) echo "nvidia-smi";;
                            pip3) echo "python3-pip";;
                            bc) echo "bc";;
                            *) echo "";;
                        esac)
                        pack='zpper install'
                        ;;
                    *)
                        msg="Distro '$DISTRO_ID' not supported."
                        package_name=""
                        pack=""
                        ;;
                esac

                
                if [ -z "$package_name" ]; then
                    echo -en "\n$name needs to be installed. Please run \n '$pack $package_name -y' \n";deps=1;
                else
                    echo -en "\n$name needs to be installed. Please run \n '$pack $package_name -y' \n";deps=1;
                fi
                ;;
            *)
                echo -en "\n$name needs to be installed. Please install '$name' first";deps=1;
                ;;
        esac
    done
    
    if [[ $deps -ne 1 ]]; then
        log_info "Dependency check OK"
    else
        echo "STATUS: ERROR: Missing dependencies. Check log for details."
        log_info "Error: Missing dependencies. Install the above and rerun this script"; sleep 1; exit 1;
    fi

    REQUIREMENTS_FILE="src/requirements.txt"
    if [ ! -f "$REQUIREMENTS_FILE" ]; then
    echo "STATUS: ERROR: Missing requirements.txt."
    echo "Can't find requirements.txt"
    sleep 1
    exit 1
    fi
    while IFS= read -r package || [[ -n "$package" ]]; do
    
    if python3 -c "import pkg_resources; pkg_resources.require('$package')" 2>/dev/null; then
        log_info "Package $package ....ok"
    else
        log_info "Installing $package"
        pip3 install "$package" --break-system-packages
    fi
done < "$REQUIREMENTS_FILE"

}


function chk_device() {

    for device in "${NVME_LIST[@]}"; do
        # check device exist or not
        if [[ ! -b "/dev/$device" ]]; then
            echo "STATUS: ERROR: Device /dev/$device does not exist."
            echo "Device /dev/$device does not exist. Exiting script."
	    
            sleep 1
            exit 1
        fi

        # use lsof check is use or not
        if lsof "/dev/$device" &> /dev/null; then
            echo "STATUS: ERROR: Device /dev/$device is busy (in use)."
            echo "Device /dev/$device is busy. Exiting script."
            sleep 1
            exit 1
        fi

        # check devcice is boot device or not
        if [[ $device == nvme* ]]; then
            if grep -q "${device}p[0-9].*/boot" /proc/mounts; then
                echo "STATUS: ERROR: /boot/ folder found on $device."
                echo "/boot/ folder found on a partition of $device. Exiting script."
                sleep 1
                exit 1
            fi
        elif [[ $device == sd* ]]; then
            if grep -q "${device}[0-9].*/boot" /proc/mounts; then
                echo "STATUS: ERROR: /boot/ folder found on $device."
                echo "/boot/ folder found on a partition of $device. Exiting script."
                sleep 1
                exit 1
            fi
        fi
    done
    result=$(graidctl ls cx --format json)

    online_count=$(echo "$result" | jq '.Result[] | select(.State=="ONLINE") | .ControllerId' | wc -l)

    if [[ $online_count -gt 0 ]]; then
        log_info "graid service is active"
    else
        echo "STATUS: ERROR: GRAID service not available. Check controller/license."
        log_info "graid service is not avaliable, please check your controller or license"
        log_info "graidctl ls cx"
        log_info "graidctl desc lic"
        sleep 1
        exit 1
    fi
 

}


function get_basic_para() {
    socket=`lscpu | grep ^Socket | uniq |  awk '{print $2}'`
    cout=`lscpu | grep ^Core | uniq |  awk '{print $4}'`
    let CPU_JOBS=${socket}*${cout}

    
    # Load Advanced Configuration
    if [ -f "graid-bench-advanced.conf" ]; then
        . graid-bench-advanced.conf
    fi
    
    . graid-bench.conf

    # Initialize missing variables with defaults if not set in config
    export SCAN=${SCAN:-"false"}
    export LS_JB=${LS_JB:-"false"}
    export LS_BS=${LS_BS:-"false"}
    export LS_CUST=${LS_CUST:-"false"}
    export LS_CS=${LS_CS:-"false"}
    export WCD=${WCD:-"false"}
    export DUMMY=${DUMMY:-"false"}
    export TEMP=${TEMP:-"75"}

    export CPU_ALLOWED_SEQ="0-$(($CPU_JOBS - 1))"
    if [[ -z "$CPU_ALLOWED_RAND" ]]; then
        export CPU_ALLOWED_RAND="0,4,8,12,16,20,24,28,32,36,40,44,48,52,56,60,64,68,72,76,80,84,88,92,96,100,104,108,112,116,120,124"
    fi
    timestamp=$(date '+%Y-%m-%d-%s')
    result="$NVME_INFO-result"
    killall -q atop fio

}

check_sanitize_done() {
    local device_path="$1"
    local device="${device_path#/dev/}"
    
    while true; do
        local sprog=""
        
        # 1. Try JSON output
        local json_out
        json_out=$(nvme sanitize-log "$device_path" -o json 2>/dev/null)
        
        if [[ -n "$json_out" ]]; then
            # Attempt to parse as JSON, handling both flat and nested structure
            sprog=$(echo "$json_out" | jq -r --arg device "$device" '.sprog // .[$device].sprog' 2>/dev/null)
        fi
        
        # 2. Fallback to text output if JSON failed to produce value
        if [[ -z "$sprog" || "$sprog" == "null" ]]; then
             local text_out
             text_out=$(nvme sanitize-log "$device_path" 2>/dev/null)
             # Parse 'Sanitize Progress (SPROG) : 65535'
             sprog=$(echo "$text_out" | grep -i "SPROG" | awk -F':' '{print $2}' | tr -d '[:space:]')
        fi

        if [[ "$sprog" == "65535" ]]; then
             echo "Sanitization finished on $device"
             return 0
        else
             echo "Sanitization in progress on $device. Status: '${sprog}'"
             sleep 5
        fi
    done
}

function discard_device() {
    local device="$1"
    echo $device
    # Try with "-f" option
    blkdiscard "$device" -f > /dev/null 2>&1
    local RESULT=$?

    # If the "-f" option fails, try without it
    if [ $RESULT -ne 0 ]; then
        blkdiscard "$device" > /dev/null 2>&1
        RESULT=$?
    fi

    # Check if either attempt was successful
    if [ $RESULT -eq 0 ]; then
        echo "blkdiscard success on $device"
    else
        echo "STATUS: ERROR: blkdiscard failed on $device."
        echo "blkdiscard failed on $device"
        sleep 1
        exit 1
    fi
    if [[ $device == *nvme* ]]; then
        nvme format -f "$device"
        nvme sanitize -a 2 "$device"
        check_sanitize_done "$device"
    fi
    


}

main() {
    rm -rf $result
    # mkdir $result
    # mkdir -p $result/$NVME_INFO/pd
    # mkdir -p $result/$NVME_INFO/vd
    NVME_COUNT=${#NVME_LIST[@]}
    
    # Calculate Global Total Steps
    if [[ "$QUICK_TEST" == "true" ]]; then
        WL_COUNT_VD=4
        if [[ "$DUMMY" == "true" ]]; then WL_COUNT_PD=4; else WL_COUNT_PD=7; fi
    else
        WL_COUNT_VD=12
        WL_COUNT_PD=13
    fi

    TOTAL_BENCH_STEPS=0
    # PD Steps
    if [[ "$RUN_PD" == "true" ]]; then
        for test in "${TS_LS[@]}"; do
            NUM_CALLS=$([[ "$RUN_PD_ALL" == "true" ]] && echo 1 || echo $NVME_COUNT)
            if [[ "$LS_JB" == "true" ]]; then
                TICKS_PER_CALL=$(( WL_COUNT_PD * ${#QD_LS[@]} * ${#pd_jobs[@]} ))
            else
                TICKS_PER_CALL=$WL_COUNT_PD
            fi
            TOTAL_BENCH_STEPS=$((TOTAL_BENCH_STEPS + NUM_CALLS * TICKS_PER_CALL))
        done
    fi

    # VD/MD Steps
    PD_STEP_MOD=1
    if [[ "$SCAN" == "true" ]]; then
        PD_STEP_MOD=$(($NVME_COUNT / 4))
    fi

    if [[ "$RUN_VD" == "true" || "$RUN_MD" == "true" ]]; then
        for test in "${TS_LS[@]}"; do
            if [[ "$LS_JB" == "true" ]]; then
                TICKS_PER_CONFIG=$(( WL_COUNT_VD * ${#QD_LS[@]} * ${#JOB_LS[@]} ))
            elif [[ "$LS_BS" == "true" ]]; then
                 TICKS_PER_CONFIG=$(( WL_COUNT_VD * ${#BS_LS[@]} + WL_COUNT_VD ))
            elif [[ "$LS_CUST" == "true" ]]; then
                 TICKS_PER_CONFIG=$(( WL_COUNT_VD * ${#QD_LS[@]} * ${#QD_LS[@]} * ${#JOB_LS[@]} ))
            else
                 TICKS_PER_CONFIG=$WL_COUNT_VD
            fi
            TOTAL_BENCH_STEPS=$((TOTAL_BENCH_STEPS + ${#STA_LS[@]} * ${#RAID_TYPE[@]} * ${#QD_LS[@]} * TICKS_PER_CONFIG * PD_STEP_MOD))
        done
    fi
    
    log_info "STATUS: TOTAL_STEPS: $TOTAL_BENCH_STEPS"
    bash src/est_time.sh
    
    if [[ $RUN_PD == "true" ]]; then
        log_info "STATUS: STAGE_PD_START"
    fi

    if [[ $RUN_PD == "true" && $RUN_PD_ALL == "false" ]]; then
        for STAG in  "${TS_LS[@]}"; do
            for NVME_DEVICE in "${NVME_LIST[@]}"
            do
            #    cat /sys/class/block/${NVME_DEVICE}/device/model >> $result/$NVME_INFO/pd/${NVME_DEVICE}-INFO
            #    cat /sys/class/block/${NVME_DEVICE}/device/address >> $result/$NVME_INFO/pd/${NVME_DEVICE}-INFO
            #    echo $NVME_DEVICE $PD_RUNTIME $CPU_ALLOWED_SEQ $CPU_ALLOWED_RAND $CPU_JOBS $NVME_INFO $RAID_CTRLR $FILESYSTEM
                for iodepth in "${QD_LS[@]}"; do
                    export IODEPTH=$iodepth
                    bash src/bench.sh SingleTest $NVME_COUNT $PD_RUNTIME $CPU_ALLOWED_SEQ $CPU_JOBS $STAG $STA_LS PD $NVME_DEVICE
                done
            done
        done
    elif [[ $RUN_PD == "true" && $RUN_PD_ALL == "true" ]]; then
        # echo TTT
        # for I in "${NVME_LIST[@]}"
        # do
        # 	OUT=${OUT:+$OUT }/dev/$I:
        # done
        # fio_name=`echo "${OUT%?}" | sed -e 's/ //g'`
        # #echo $fio_name
        # val=`expr 4 \* $NVME_COUNT`
        #echo $val
        #echo $val
        for STAG in  "${TS_LS[@]}"; do
            for iodepth in "${QD_LS[@]}"; do
                export IODEPTH=$iodepth
                bash src/bench.sh SingleTest $NVME_COUNT $PD_RUNTIME $CPU_ALLOWED_SEQ $CPU_JOBS $STAG $STA_LS PD $NVME_LIST
            done
        done
        
    fi

    if [[ $RUN_VD == "true" ]]; then
        log_info "STATUS: STAGE_VD_START"
        log_info "DEV_NAME: $NVME_INFO"
        pids=()
        for NVME_DEVICE in "${NVME_LIST[@]}"
        do
            discard_device /dev/$NVME_DEVICE &
            pids+=($!)
        done
        wait "${pids[@]}"
        log_info "Sanitization finished"
        for NVME_DEVICE in "${NVME_LIST[@]}"
        do
            log_info "Creating PD for $NVME_DEVICE"
            log_info "Creating PD for $NVME_DEVICE"
            yes | graidctl create pd /dev/$NVME_DEVICE
        done
        # graidctl create pd /dev/nvme0-$(($NVME_COUNT - 1))
        #run 4PD/n x all RAID x percondition
        for STAS in  "${STA_LS[@]}"; do
            for STAG in  "${TS_LS[@]}"; do
                for RAID in "${RAID_TYPE[@]}"; do
                    for iodepth in "${QD_LS[@]}"; do
                        export IODEPTH=$iodepth
                        if [[ $SCAN == "false" ]]; then
                            for PD_NUMBER in $NVME_COUNT; do
                                echo "---$RAID x $PD_NUMBER---$NVME_INFO-$CPU_JOBS-QD${IODEPTH}"
                                bash src/bench.sh $RAID $PD_NUMBER $VD_RUNTIME $CPU_ALLOWED_SEQ $CPU_JOBS $STAG $STAS VD
                            done
                        elif [[ $SCAN == "true" ]]; then
                            for PD_NUMBER in $(seq 4 4 $NVME_COUNT); do
                                echo "---$RAID x $PD_NUMBER---$NVME_INFO-$CPU_JOBS-QD${IODEPTH}"
                                bash src/bench.sh $RAID $PD_NUMBER $VD_RUNTIME $CPU_ALLOWED_SEQ $CPU_JOBS $STAG $STAS VD
                            done
                        fi
                    done
                done
            done
        done
        for PD_NUM in $(seq 0 $(($NVME_COUNT - 1))); 
        do
            graidctl del pd $PD_NUM  > /dev/null 2>&1
        done
    fi

    if [[ $RUN_MD == "true" ]]; then
        echo $NVME_INFO
        #run 4PD/n x all RAID x percondition
        #run 4PD/n x all RAID x percondition
        for STAS in  "${STA_LS[@]}"; do
            for STAG in  "${TS_LS[@]}"; do
                for RAID in "${RAID_TYPE[@]}"; do
                    for iodepth in "${QD_LS[@]}"; do
                        export IODEPTH=$iodepth
                        # for PD_NUMBER in $(seq 4 4 $NVME_COUNT); do
                        if [[ $SCAN == "false" ]]; then
                            for PD_NUMBER in $NVME_COUNT; do
                                echo "---$RAID x $PD_NUMBER---$NVME_INFO-$CPU_JOBS-QD${IODEPTH}"
                                bash src/bench.sh $RAID $PD_NUMBER $VD_RUNTIME $CPU_ALLOWED_SEQ $CPU_JOBS $STAG $STAS MD
                            done
                        elif [[ $SCAN == "true" ]]; then
                            for PD_NUMBER in $(seq 4 4 $NVME_COUNT); do
                                echo "---$RAID x $PD_NUMBER---$NVME_INFO-$CPU_JOBS-QD${IODEPTH}"
                                bash src/bench.sh $RAID $PD_NUMBER $VD_RUNTIME $CPU_ALLOWED_SEQ $CPU_JOBS $STAG $STAS MD
                            done
                        fi
                    done
                done

            done
        done
    fi


    # if [[ $RUN_MR == "true" ]]; then
    #     #run 4PD/n x all RAID x percondition
    #     for STAS in  "${STA_LS[@]}"; do
    #         for STAG in  "${TS_LS[@]}"; do
    #             for RAID in "${RAID_TYPE[@]}"; do
    #                     for WP in  "${WP_LS[@]}"; do
    #                         bash src/storcli-bench.sh $RAID $WP $VD_RUNTIME $CPU_ALLOWED_SEQ $CPU_JOBS $STAG $STAS
    #                     done
    #             done

    #         done
    #     done
    # fi

    #pip3 install pandas
    #pip3 install pathlib
    #python3 parser.py
    python_paser
    bash ./src/graid-log-collector.sh -y -U

    tar_name="graid_bench_result_$(hostname)_$NVME_INFO_$timestamp.tar.gz"
    
    # Create the archive with files from different locations but clean paths
    # We use -C to change directory context for specific items
    tar czf "$tar_name" ./graid_log_* ./output.log -C "../results/.test-temp-data" "$NVME_INFO-result"

    echo "Moving results to ../results/"
    mv "$tar_name" ../results/
    rm -rf "../results/.test-temp-data/$NVME_INFO-result" ./graid_log_* ./output.log
}

python_paser(){
    PYTHON_SCRIPT="src/fio_parser.py"
    timestamp=$(date '+%Y-%m-%d')
    # Point parser to the hidden temporary results directory
    result_path="../results/.test-temp-data/$NVME_INFO-result"
    
    python3 $PYTHON_SCRIPT "$result_path"

}


check_root_user
get_basic_para
check_dependencies
chk_device
main

unset LC_ALL
