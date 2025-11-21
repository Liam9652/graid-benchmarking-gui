#!/bin/bash

export LC_ALL=C

LOG_FILE="./output.log"
exec > >(tee -a "$LOG_FILE") 2>&1

# Check the running shell and re-run with bash if necessary
if [ "$BASH" != "/bin/bash" ]; then
	    /bin/bash "$0" "$@"
	        exit $?
fi


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
        echo "Must be root or using sudo"
        exit 1
    fi
}

get_distro() {
    if [ -f /etc/os-release ]; then
        source /etc/os-release
        echo "$ID" | tr '[:upper:]' '[:lower:]'
    else
        echo "Error: /etc/os-release does not exist."
        exit 1
    fi
}


function check_dependencies() {
    echo -n "Checking dependencies... "
    deps=0

    # Check if LOG_COMPACT is true
    if [[ "${LOG_COMPACT}" == "true" ]]; then
        # echo "LOG_COMPACT is set to true. Skipping atop check."
        skip_atop=true
        echo '13'
    else
        skip_atop=false
    fi


    for name in fio jq nvme graidctl atop nvidia-smi pip3
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
                            *) echo "";;
                        esac)
                        if [[ "$name" == "pip3" ]]; then
                            pack='sudo dnf install'
                        else    
                            pack='sudo yum install'
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
                            *) echo "";;
                        esac)
                        pack='sudo apt install'
                        ;;
                    sled|sles|opensuse-leap)
                        package_name=$(case $name in
                            fio) echo "fio";;
                            jq) echo "jq";;
                            nvme) echo "nvme-cli";;
                            atop) echo "atop";;
                            nvidia-smi) echo "nvidia-smi";;
                            pip3) echo "python3-pip";;
                            *) echo "";;
                        esac)
                        pack='sudo zpper install'
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
        echo "OK"
    else
        echo -en "\nInstall the above and rerun this script\n"; exit 1;
    fi

    REQUIREMENTS_FILE="src/requirements.txt"
    if [ ! -f "$REQUIREMENTS_FILE" ]; then
    echo "Can't find requirements.txt"
    exit 1
    fi
    while IFS= read -r package || [[ -n "$package" ]]; do
    
    if python -c "import pkg_resources; pkg_resources.require('$package')" 2>/dev/null; then
        echo "Package $package ....ok"
    else
        echo "Installing $package"
        pip3 install "$package"
    fi
done < "$REQUIREMENTS_FILE"

}


function chk_device() {

    for device in "${NVME_LIST[@]}"; do
        # check device exist or not
        if [[ ! -b "/dev/$device" ]]; then
            echo "Device /dev/$device does not exist. Exiting script."
	    
            exit 1
        fi

        # use lsof check is use or not
        if lsof "/dev/$device" &> /dev/null; then
            echo "Device /dev/$device is busy. Exiting script."
            exit 1
        fi

        # check devcice is boot device or not
        if [[ $device == nvme* ]]; then
            if grep -q "${device}p[0-9].*/boot" /proc/mounts; then
                echo "/boot/ folder found on a partition of $device. Exiting script."
                exit 1
            fi
        elif [[ $device == sd* ]]; then
            if grep -q "${device}[0-9].*/boot" /proc/mounts; then
                echo "/boot/ folder found on a partition of $device. Exiting script."
                exit 1
            fi
        fi
    done
    result=$(graidctl ls cx --format json)

    online_count=$(echo "$result" | jq '.Result[] | select(.State=="ONLINE") | .ControllerId' | wc -l)

    if [[ $online_count -gt 0 ]]; then
        echo "graid service is active"
    else
        echo "graid service is not avaliable, please check your controller or license"
        echo "graidctl ls cx"
        echo "graidctl desc lic"
        exit 1
    fi
 

}


function get_basic_para() {
    socket=`lscpu | grep ^Socket | uniq |  awk '{print $2}'`
    cout=`lscpu | grep ^Core | uniq |  awk '{print $4}'`
    let CPU_JOBS=${socket}*${cout}

    . graid-bench.conf

    export CPU_ALLOWED_SEQ="0-$(($CPU_JOBS - 1))"
    export CPU_ALLOWED_RAND="0,4,8,12,16,20,24,28,32,36,40,44,48,52,56,60,64,68,72,76,80,84,88,92,96,100,104,108,112,116,120,124"
    timestamp=$(date '+%Y-%m-%d-%s')
    result="$NVME_INFO-result-$timestamp"
    killall -q atop fio

}

check_sanitize_done() {
    local device_path="$1"
    local device="${device_path#/dev/}"
    while true; do
        devices_status=$(nvme sanitize-log "$device_path" -o json 2>/dev/null)
        if [ $? -eq 0 ]; then  # Check if nvme command succeeded
            devices_finished=$(echo "$devices_status" | jq -r --arg device "$device" '.[$device].sprog')
            if [[ "$devices_finished" == "65535" ]]; then
                echo "Sanitization finished"
                return 0  # Indicate success with exit status 0
            else
                echo "Sanitization in progress, checking again in 5 seconds..."
                sleep 5  # Wait for 5 seconds before checking again
            fi
        else
            echo "Error reading sanitize log for device $device_path"
            return 2  # Indicate an error with a distinct non-zero exit status
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
        echo "blkdiscard failed on $device"
        exit 1
    fi
    if [[ $device == *nvme* ]]; then
        sudo nvme format -f "$device"
        sudo nvme sanitize -a 2 "$device"
        check_sanitize_done "$device"
    fi
    


}

main() {
    rm -rf $result
    # mkdir $result
    # mkdir -p $result/$NVME_INFO/pd
    # mkdir -p $result/$NVME_INFO/vd
    NVME_COUNT=${#NVME_LIST[@]}
    bash src/est_time.sh

    if [[ $RUN_PD == "true" && $RUN_PD_ALL == "false" ]]; then
        for STAG in  "${TS_LS[@]}"; do
            for NVME_DEVICE in "${NVME_LIST[@]}"
            do
            #    cat /sys/class/block/${NVME_DEVICE}/device/model >> $result/$NVME_INFO/pd/${NVME_DEVICE}-INFO
            #    cat /sys/class/block/${NVME_DEVICE}/device/address >> $result/$NVME_INFO/pd/${NVME_DEVICE}-INFO
            #    echo $NVME_DEVICE $PD_RUNTIME $CPU_ALLOWED_SEQ $CPU_ALLOWED_RAND $CPU_JOBS $NVME_INFO $RAID_CTRLR $FILESYSTEM
                bash src/bench.sh SingleTest $NVME_COUNT $PD_RUNTIME $CPU_ALLOWED_SEQ $CPU_JOBS $STAG $STA_LS PD $NVME_DEVICE
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
        for STAG in  "${TS_LS[@]}"; do
            bash src/bench.sh SingleTest $NVME_COUNT $PD_RUNTIME $CPU_ALLOWED_SEQ $CPU_JOBS $STAG $STA_LS PD $NVME_LIST
        done
        
    fi

    if [[ $RUN_VD == "true" ]]; then
        echo $NVME_INFO
        for NVME_DEVICE in "${NVME_LIST[@]}"
            do
                discard_device /dev/$NVME_DEVICE
                graidctl create pd /dev/$NVME_DEVICE  > /dev/null 2>&1
            done
        # graidctl create pd /dev/nvme0-$(($NVME_COUNT - 1))
        #run 4PD/n x all RAID x percondition
        for STAS in  "${STA_LS[@]}"; do
            for STAG in  "${TS_LS[@]}"; do
                for RAID in "${RAID_TYPE[@]}"; do
                    if [[ $SCAN == "false" ]]; then
                        for PD_NUMBER in $NVME_COUNT; do
                            echo "---$RAID x $PD_NUMBER---$NVME_INFO-$CPU_JOBS"
                            bash src/bench.sh $RAID $PD_NUMBER $VD_RUNTIME $CPU_ALLOWED_SEQ $CPU_JOBS $STAG $STAS VD
                        done
                    elif [[ $SCAN == "true" ]]; then
                        for PD_NUMBER in $(seq 4 4 $NVME_COUNT); do
                            echo "---$RAID x $PD_NUMBER---$NVME_INFO-$CPU_JOBS"
                            bash src/bench.sh $RAID $PD_NUMBER $VD_RUNTIME $CPU_ALLOWED_SEQ $CPU_JOBS $STAG $STAS VD
                        done
                    fi
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
        for STAS in  "${STA_LS[@]}"; do
            for STAG in  "${TS_LS[@]}"; do
                for RAID in "${RAID_TYPE[@]}"; do
                    # for PD_NUMBER in $(seq 4 4 $NVME_COUNT); do
                    if [[ $SCAN == "false" ]]; then
                        for PD_NUMBER in $NVME_COUNT; do
                            echo "---$RAID x $PD_NUMBER---$NVME_INFO-$CPU_JOBS"
                            bash src/bench.sh $RAID $PD_NUMBER $VD_RUNTIME $CPU_ALLOWED_SEQ $CPU_JOBS $STAG $STAS MD
                        done
                    elif [[ $SCAN == "true" ]]; then
                        for PD_NUMBER in $(seq 4 4 $NVME_COUNT); do
                            echo "---$RAID x $PD_NUMBER---$NVME_INFO-$CPU_JOBS"
                            bash src/bench.sh $RAID $PD_NUMBER $VD_RUNTIME $CPU_ALLOWED_SEQ $CPU_JOBS $STAG $STAS MD
                        done
                    fi
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
    bash ./src/graid_log_script.sh

	# Find files smaller than 100MB and store their paths in the temporary file
	#find "./$NVME_INFO-result-*" -type f -size -100M > "$temp_file"

	# Create tar archive excluding files over 100MB
	#tar -czvf archive.tar.gz -T "$temp_file"

    python_paser
    tar czPf "graid_bench_result_$(hostname)_$NVME_INFO_$timestamp.tar" ./$NVME_INFO* ./graid_log_* ./output.log
    echo "Moving results to ../results/"
    mv "$tar_name" ../results/


}

python_paser(){
    PYTHON_SCRIPT="src/fio_parser.py"
    timestamp=$(date '+%Y-%m-%d')
    result="$NVME_INFO-result"
    
    python3 $PYTHON_SCRIPT "./$result"

}


check_root_user
get_basic_para
check_dependencies
chk_device
main

unset LC_ALL
