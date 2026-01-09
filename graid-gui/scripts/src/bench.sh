#!/bin/bash

RAID_MODE=$1
PD_NUMBER=$2
RUNTIME=$3
CPU_ALLOWED_SEQ=$4
CPU_ALLOWED_RAND=$CPU_ALLOWED_SEQ
CPUJOBS=$5
STAG=$6
STAS=$7
DEV_NAME=$8
FILESYSTEM='RAW'
PD_NAME=$9
#declare -A LAST_END_CPU_BY_NUMA
echo $DEV_NAME



. graid-bench.conf

trap cleanup INT TERM EXIT

function cleanup() {
        echo "** Trapped Signal, Cleaning up..."
        # Disable trap to avoid recursion
        trap - INT TERM EXIT
        
        kill_pid "${fio_pid_list}"
        kill_pid "${iostat_pid_list}"
        kill_pid "${atop_pid_list}"
        kill_pid "${cpu_pid_list}"
        kill_pid "${ssd_pid_list}"
        kill_pid "${gpu_pid_list}"
        
        raid_cleanup
        exit 1
}

find_numa_node() {
    local device_name=$1
    local numa_node

    # Try to extract NUMA node information from sysfs
    if [[ -f "/sys/block/${device_name}/device/numa_node" ]]; then
        numa_node=$(cat "/sys/block/${device_name}/device/numa_node")
    elif [[ -f "/sys/class/nvme/${device_name:0:-2}/numa_node" ]]; then
        numa_node=$(cat "/sys/class/nvme/${device_name:0:-2}/numa_node")
    fi

    if [[ -z $numa_node ]]; then
            numa_node=9999

    fi
    echo "$numa_node"
}


find_cpu_list_by_numa_node() {
    local numa_node=$1
    local cpu_list

    # Check if the directory for the NUMA node exists in /sys
    if [ -d "/sys/devices/system/node/node$numa_node" ]; then
        cpu_list=$(cat "/sys/devices/system/node/node$numa_node/cpulist")
    else
        # Fallback to lscpu if the above directory does not exist
        cpu_list=$(lscpu | grep "NUMA node$numa_node" | awk -F ':' '{print $2}' | sed 's/ //g')

    fi
    if [[ $numa_node = "9999" ]]; then
            socket=`lscpu | grep ^Socket | uniq |  awk '{print $2}'`
            cout=`lscpu | grep ^Core | uniq |  awk '{print $4}'`
	    CPU_JOBS=$(($socket * $cout))
            #let CPU_JOBS=${socket}*${cout}
	    cpu_list="0-$(($CPU_JOBS - 1))"

    fi

    echo $cpu_list
}

cut_cpu_list(){
        local cpu_list=$1
        local id=$2
        local cpu_id=""
        local cpu_id_lst=""
        cpu_id=$(echo $cpu_list | awk -F'[-,]' '{print $1}')
        cpu_id_lst=$(echo $cpu_list | awk -F'[-,]' '{print $2}')
        echo "$cpu_id" "$cpu_id_lst"
}

function raid_cleanup(){
    if [[ "$DEV_NAME" == "VD" ]]; then
        graidctl del vd 0 0 --confirm-to-delete 2>/dev/null
        graidctl del dg 0 --confirm-to-delete 2>/dev/null
    elif [[ "$DEV_NAME" == "MD" ]]; then
        mdadm -S /dev/$MD_NAME
    fi
}

         

# Function to determine the CPU count
function get_cpu_count() {
    cout=$(lscpu | grep ^Socket | uniq | awk '{print $4}')
    cpus_counts=`lscpu | grep ^Core | uniq |  awk '{print $4}'`
}

# Get the total number of physical cores in the system
function get_physical_cores() {
    awk -F': ' '/physical id/ { PHYSICAL_ID[$2] = 1 } /core id/ { CORE_ID[$2] = 1 } END { print length(PHYSICAL_ID) * length(CORE_ID) }' /proc/cpuinfo
}

# Function to determine the NUMA node for the given NVMe and calculate cpus_allowed
function get_numa(){
    nvmen=$1
    jobs=$2
    last_end_cpu=$3
    cpu_value=""

    # 
    # if [[ -z $last_end_cpu ]]; then
    #     # 
    #     if [[ $nvmen == nvme* ]]; then 
    #         numa=$(find_numa_node $nvmen)
    #         cpu_list=$(find_cpu_list_by_numa_node $numa)
    #     #     first_cpu=$(echo $cpu_list | awk -F'[-,]' '{print $1}')
    #     #  max_cpu=$(echo $cpu_list | awk -F'[-,]' '{print $2}')
    #         # first_cpu=$(cat /sys/devices/system/node/node"$numa"/cpulist | awk -F',' '{print $1}' | awk -F'-' '{print $1}')
    #         last_end_cpu=$(echo $cpu_list | awk -F'[-,]' '{print $1}')
    #     fi
    # fi

    if [[ $nvmen == nvme* ]]; then 
        numa=$(find_numa_node $nvmen)
        cpu_list_nvme=$(find_cpu_list_by_numa_node $numa)
        first_cpu=$(echo $cpu_list_nvme | awk -F'[-,]' '{print $1}')
        max_cpu=$(echo $cpu_list_nvme | awk -F'[-,]' '{print $2}')
        # read -r first_cpu max_cpu <<< $(cut_cpu_list "$cpu_list")
	    # max_cpu=${cpu_value[1]}
        if [[ "$jobs" -le "$max_cpu" ]]; then
            if [[ -z "$last_end_cpu" ]]; then	
                cpu_node_start_loc_nvme=$first_cpu
            elif [[ "$last_end_cpu" -ge "$max_cpu" ]]; then
                cpu_node_start_loc_nvme=$first_cpu
            else
                cpu_node_start_loc_nvme=$(($last_end_cpu + 1))
            fi
            cpu_seq_dev="$cpu_node_start_loc_nvme-$(($cpu_node_start_loc_nvme + $jobs - 1))"
	    else
		    cpu_seq_dev=$CPU_ALLOWED_SEQ
        fi
    else
        cpu_seq_dev=$CPU_ALLOWED_SEQ
    fi
    echo $cpu_seq_dev
}




function ipmi_error(){
    # Try running ipmitool and capture the error
    ipmitool_error_output=$(ipmitool 2>&1 >/dev/null)
    ipmitool_error_id=""
    # Check if the error message contains the expected error string
    if [[ $ipmitool_error_output == *"Could not open device at /dev/ipmi0 or /dev/ipmi/0 or /dev/ipmidev/0"* ]]; then
        ipmitool_error_id=1
    else
        # Place your ipmitool related commands here
        # echo "ipmitool command succeeded. Continuing with operations."
        ipmitool_error_id=0
        # ...
    fi
}

# Function to collect log
function collect_log() {
    output_name=$1
    output_fio_dir=$2
    echo ---collect_log----
    # echo $output_name 
    # echo $output_fio_dir
    for u in iostat ssd_tmp cpu_tmp gpu_tmp raid_config; do
        mkdir -p $output_fio_dir/$u
    done

    iostat_pid_list=""
    cpu_pid_list=""
    ssd_pid_list=""
    gpu_pid_list=""

    giostat -dxmct 5 > ${output_fio_dir}/iostat/$output_name.iostat &
    iostat_pid_list="${iostat_pid_list} $!"

    if [[ "$LOG_COMPACT" == "false" ]]; then
	    mkdir -p  $output_fio_dir/atop
	    atop_pid_list=""
	    atop -R -w  ${output_fio_dir}/atop/$output_name.log 5 &
	    atop_pid_list="${atop_pid_list} $!"
    fi


    while true; 
    do
        if [[ $device == nvme* ]]; then
            #echo "smart-log $DEV_NAME"
            if [[ $DEV_NAME == "VD" ]]; then
                for d in /dev/gpd*; do
                    echo "$d - $(nvme smart-log $d | grep -i '^temperature')" >> ${output_fio_dir}/ssd_tmp/$output_name.log
                done
            else
                for d in /dev/nvme*n1; do
                    echo "$d - $(nvme smart-log $d | grep -i '^temperature')" >> ${output_fio_dir}/ssd_tmp/$output_name.log
                done
            fi
        elif [[ $device == sd* ]]; then
            for d in /dev/sd*; do
                echo "$d - $(smartctl -a $d |grep -i '^Current Drive Temperature')" >> ${output_fio_dir}/ssd_tmp/$output_name.log
            done
        fi
    done &
    ssd_pid_list="${ssd_pid_list} $!"

    echo "timestamp,index,name,serial,pcie.link.gen.current,pcie.link.width.current,utilization.gpu,memory.total,memory.used,power.draw,temperature.gpu,temperature.memory,clocks.max.sm,clocks.current.sm,clocks.max.memory,clocks.current.memory,clocks.max.graphics,clocks.current.graphics,clocks.current.video,ecc.mode.current,clocks_throttle_reasons.applications_clocks_setting,clocks_throttle_reasons.sw_power_cap,clocks_throttle_reasons.hw_thermal_slowdown,clocks_throttle_reasons.sw_thermal_slowdown" > query-item 
    if [[ $DEV_NAME == "VD" ]]; then
        query_item_path=$(readlink -f query-item)
        pushd ${output_fio_dir}/gpu_tmp > /dev/null
        nvidia-smi -l 5 --format=csv  --query-gpu=`cat $query_item_path` -f $output_name.log &
        gpu_pid_list="${gpu_pid_list} $!" 
        popd > /dev/null
        graidctl ls pd 2>/dev/null > ${output_fio_dir}/raid_config/$output_name.log
        graidctl ls dg 2>/dev/null >> ${output_fio_dir}/raid_config/$output_name.log
        graidctl ls vd 2>/dev/null >> ${output_fio_dir}/raid_config/$output_name.log
    elif [[ $DEV_NAME == "MD" ]]; then
        for key in "${!settings[@]}"; do
            cat "/sys/block/${MD_NAME}/md/$key" > ${output_fio_dir}/raid_config/$output_name.log
        done
            cat /proc/mdstat  >> ${output_fio_dir}/raid_config/$output_name.log
    elif [[ $DEV_NAME == "PD" ]]; then
        nvme list > ${output_fio_dir}/raid_config/$output_name.log
    fi


    # Start a background process to append the output to the log file every second
    ipmi_error
    if [[ $ipmitool_error_id == 0 ]]; then
        while true; do
            ipmitool sdr >> ${output_fio_dir}/cpu_tmp/$output_name.log
            sleep 5
        done &
        cpu_pid_list="${cpu_pid_list} $!"
    else 
        cpu_pid_list=${iostat_pid_list}
    fi
    # Store the PID of the background process

}

# Function to read CPU temperature from the sysfs
function read_cpu_temp_sysfs() {
    local cpu_number=$1
    local temp_file="/sys/class/thermal/thermal_zone${cpu_number}/temp"
    if [[ -f "$temp_file" ]]; then
        cpu_temp=$(cat "$temp_file")
        cpu_temp_celsius=$((cpu_temp / 1000))
    else
        cpu_temp_celsius=""
    fi
}

# Function to read CPU temperature using sensors
function read_cpu_temp_sensors() {
    local cpu_number=$1
    cpu_temp=$(sensors 2>/dev/null | grep "Tdie${cpu_number}:" | awk '{print $2}' | tr -d '+°C')
    cpu_temp_celsius="${cpu_temp}"
}

# Function to read CPU temperature using hwinfo (if available)
function read_cpu_temp_hwinfo() {
    local cpu_number=$1
    cpu_temp=$(hwinfo --cpu 2>/dev/null | grep "Temperature${cpu_number}:" | awk '{print $3}' | tr -d '°C')
    cpu_temp_celsius="${cpu_temp}"
}

# Function to read CPU temperature with fallback to other methods
function read_cpu_temp() {
    local cpu_number=$1

    # Try reading CPU temperature using ipmitool first
    read_cpu_temp_ipmitool $cpu_number

    # If ipmitool fails or temperature not available, try sysfs
    if [[ "$cpu_temp_celsius" == "" ]]; then
        read_cpu_temp_sysfs $cpu_number
    fi

    # If sysfs fails or temperature not available, try sensors
    if [[ "$cpu_temp_celsius" == "" ]]; then
        read_cpu_temp_sensors $cpu_number
    fi

    # If sensors fails or temperature not available, try hwinfo
    if [[ "$cpu_temp_celsius" == "" ]]; then
        read_cpu_temp_hwinfo $cpu_number
    fi
}

# Function to read CPU temperature using ipmitool
read_cpu_temp_ipmitool() {
    local cpu_number=$1
    cpu_temp=$(ipmitool sensor get "CPU${cpu_number}_TEMP" 2>/dev/null | grep "Sensor Reading" | awk '{print $4}')
    cpu_temp_celsius="${cpu_temp}"
}


# Function to wait until CPU temperatures are lower than a specified threshold
function wait_for_low_cpu_temp() {
    get_cpu_count

    while true; do
        # Declare an array to store CPU temperatures
        declare -a cpu_temps

        # Get the CPU temperatures using ipmitool, /sys, sensors, or hwinfo for each CPU
        for ((i=0; i<cout; i++)); do
            cpu_temp=""
            
            # Try reading CPU temperature using ipmitool first
            read_cpu_temp_ipmitool $i

            # If ipmitool fails or temperature not available, try sysfs
            if [[ "$cpu_temp_celsius" == "" ]]; then
                read_cpu_temp_sysfs $i
            fi

            # If sysfs fails or temperature not available, try sensors
            if [[ "$cpu_temp_celsius" == "" ]]; then
                read_cpu_temp_sensors $i
            fi

            # If sensors fails or temperature not available, try hwinfo
            if [[ "$cpu_temp_celsius" == "" ]]; then
                read_cpu_temp_hwinfo $i
            fi

            cpu_temps[$i]=$cpu_temp_celsius
        done

        # Check if all CPU temperatures are lower than the threshold (75.000°C)
        all_temps_low=true
        for temp in "${cpu_temps[@]}"; do
            if [[ "$temp" == "N/A" || (( $(echo "$temp >= $TEMP" | bc -l) )) ]]; then
                all_temps_low=false
                break
            fi
        done

        # Check if all CPU temperatures are lower than the threshold
        if $all_temps_low; then
            echo "All CPU Temperatures are lower than $TEMP°C. Proceeding..."
            break
        else
            echo "Some CPU Temperatures are still above $TEMP°C. Waiting..."
            sleep 5  #sleep 5 sec
        fi
    done
}



function trigger_snapshot() {
    local of_name=$1
    local fio_dir=$2
    # Call backend to take snapshot
    curl -X POST -H "Content-Type: application/json" -d "{\"test_name\": \"$of_name\", \"output_dir\": \"$fio_dir\"}" http://localhost:50071/api/benchmark/trigger_snapshot >/dev/null 2>&1
}

function output_name_dic() {
    # graid-a2000-ntfs-1vd-12pd-randread-j32b4kd32
    timestamp=$(date '+%Y-%m-%d')
    result="$NVME_INFO-result"
    out_dir=./$result/$NVME_INFO/${STAG}/${DEV_NAME}
    mkdir -p ${out_dir}
    out_dir_tmp=./$result/$NVME_INFO/

    for ts in "${TS_LS[@]}"; do
        # mkdir -p "${out_dir}/$ts"
        if [[ $RUN_PD == true ]]; then
            mkdir -p "${out_dir_tmp}/$ts/PD"
        fi
        if [[ $RUN_VD == true ]]; then
            mkdir -p "${out_dir_tmp}/$ts/VD"
        fi
        if [[ $RUN_MD == true ]]; then
            mkdir -p "${out_dir_tmp}/$ts/MD"
        fi
        if [[ $RUN_MR == true ]]; then
            mkdir -p "${out_dir_tmp}/$ts/MR"
        fi
    done 



    
    if [[ "$DEV_NAME" == "MD" ]]; then
	    OUTPUT_NAME="graid-mdadm-$FILESYSTEM-$RAID_MODE-1VD-${PD_NUMBER}PD-S-${NVME_INFO}-D-${STAG}"
    elif [[ "$DEV_NAME" == "MR" ]]; then
        OUTPUT_NAME="graid-storcli-$FILESYSTEM-$RAID_MODE-1VD-${PD_NUMBER}PD-S-${NVME_INFO}-D-${STAG}"
    else
        OUTPUT_NAME="graid-$RAID_CTRLR-$FILESYSTEM-$RAID_MODE-1VD-${PD_NUMBER}PD-S-${NVME_INFO}-D-${STAG}"
    fi

}

# Function to wait until the device is detected in the system
function wait_for_device() {
    local device=$1
    local max_wait=24
    local count=0
    
    local dg_num=${VD_NAME:3:1}
    while [[ ! -e $device ]]; do
        if (( count >= max_wait )); then
            echo "Over 2mins recreate $device..."
            create_vd
            count=0
        else
            echo "Checking for $device ..."
            sleep 5
            ((count++))
        fi
    done
    if [[ $device == *gdg* ]]; then
        graidctl ls dg --dg-id="$dg_num" --format json > dg.log
        status=$(jq '.Result[0].State' dg.log | tr -d '"')
        while [[ $status == "OPTIMAL" ]] && [[ $status == "RECOVERY" ]]; do

            echo "Waiting for $device to finish initializing...sleeping for 3 minutes"
            sleep 180
            graidctl ls dg --dg-id="$dg_num" --format json > dg.log
            status=$(jq '.Result[0].State' dg.log | tr -d '"')
        done
        rm -rf dg.log
    fi
}

create_raid_group() {
    local raid_mode=$1
    local pd_number=$2
    local strip_size=$3
    local force_flag=$4

    local strip_option=""
    if [[ $LS_CS == "true" && ($raid_mode != "RAID5" && $raid_mode != "RAID6" || $strip_size == "4") ]]; then
        strip_option="-s $strip_size"
    fi

    graidctl create dg $raid_mode 0-$(($pd_number - 1)) $strip_option $force_flag 2>/dev/null
}

create_virtual_disk() {
    local vd_name_c=$1

    graidctl create vd 0 2>/dev/null
    wait_for_device "/dev/$vd_name_c"
    sleep 15
}

handle_nvme_devices() {
    local device=$1

    if [[ $device == nvme* ]]; then
        create_raid_group "$RAID_MODE" "$PD_NUMBER" "$STRIP_SIZE" ""
        create_virtual_disk "$VD_NAME"
    fi
}

handle_sd_devices() {
    # for I in "${NVME_LIST[@]}"; do
    #     discard_device "/dev/$I"
    #     wait
    # done

    create_raid_group "$RAID_MODE" "$PD_NUMBER" "$STRIP_SIZE" "-f"
    create_virtual_disk "$VD_NAME"
}


function create_vd(){
    echo "----Create $RAID_MODE DG with $PD_NUMBER PD----"
    device=$(echo $NVME_LIST | awk '{print $1}')

    if [[ $DEV_NAME == "VD" ]]; then
        if [[ $device == nvme* ]]; then
            handle_nvme_devices "$device"
        elif [[ $device == sd* ]]; then
            handle_sd_devices
        fi
    elif [[ $DEV_NAME == "MD" ]]; then

        if [[ $RAID != 1  ]]; then
            yes | mdadm  --create /dev/$MD_NAME --auto=yes --chunk=${MD_BS}K --verbose  --level=$RAID --assume-clean -n $PD_NUMBER $MD_NVME_LIST
        else
            yes | mdadm  --create /dev/$MD_NAME --auto=yes --verbose  --level=$RAID --assume-clean -n $PD_NUMBER $MD_NVME_LIST
        fi
        wait_for_device "/dev/$MD_NAME"
	    sleep 15
        if [[ $RAID == 5 ]] || [[ $RAID == 6 ]]; then
            declare -A settings
            settings["group_thread_cnt"]=12
            settings["sync_speed_min"]=1000000
            settings["sync_speed_max"]=2000000

            for key in "${!settings[@]}"; do
                echo "${settings[$key]}" > "/sys/block/${MD_NAME}/md/$key"
                sleep 5
                cat "/sys/block/${MD_NAME}/md/$key"
            done
        fi

    
    elif [[ $DEV_NAME == "PD"  ]]; then
        # TBC
        echo "PD"
        sleep 5
    fi
    
    # size=`jq '.Result.Capacity' test.json`
    # let runsize=${size}/20/1024/1024/1024
    # let offsetsize=${size}/${CPUJOBS}/1024/1024/1024
}

function get_disk_size() {
    if [[ "$DEV_NAME" == "VD" ]]; then
        size=$(graidctl desc dg 0 --format json 2>/dev/null | jq '.Result.Capacity')
        runsize=$((size / (20 * 1024 * 1024 * 1024)))
        offsetsize=$((size / (CPUJOBS * 1024 * 1024 * 1024)))
        if [[ "$offsetsize" -lt 0 ]]; then
            offsetsize=100
        fi
    elif [[ "$DEV_NAME" == "MD" ]]; then
        size=$(mdadm -D "/dev/$MD_NAME" | grep "Array Size" | uniq | awk '{print $4}')
        runsize=$((size / (20 * 1024 * 1024)))
        offsetsize=$((size / (CPUJOBS * 1024 * 1024)))
        if [[ "$offsetsize" -lt 0 ]]; then
            offsetsize=100
        fi
    elif [[ "$DEV_NAME" == "PD" ]]; then
        device=$(echo "$NVME_LIST" | awk '{print $1}')
        if [[ "$device" == nvme* ]]; then
            nvme_sector=$(nvme id-ctrl -H "/dev/${device}" 2>/dev/null | grep tnvmcap | uniq | awk '{print $3}')
            size=$((nvme_sector / 512))
            runsize=$((size / (20 * 1000 * 1000)))
        elif [[ "$device" == sd* ]]; then
            runsize=$(($(sg_readcap "/dev/$device" | grep Device | awk '{print $3}') / (20 * 1024 * 1024 * 1024)))
        fi
    fi
    
}



function list_file(){
    if [[ $DEV_NAME != "PD" ]]; then
        # echo $runsize $offsetsize
        if [[ $QUICK_TEST == "true" ]]; then
            src_path=src/fio-loop
            # echo "$DUMMY"
            if [[ $DUMMY == "false" ]]; then
                task_list=(${src_path}/00-randread-graid ${src_path}/01-seqread-graid ${src_path}/02-seqwrite-graid ${src_path}/09-randwrite-graid)
            	cp ${src_path}/01-seqread-graid ${src_path}/01-seqread-graid.bak
            	sed -i 's/offset_increment=\([0-9]*\)g/offset_increment='"$offsetsize"'g/' ${src_path}/01-seqread-graid
            	sed -i 's/size=\([0-9]*\)g/size='"$offsetsize"'g/' ${src_path}/01-seqread-graid

            else
                task_list=(${src_path}/00-randread-graid ${src_path}/01-seqread-graid ${src_path}/02-seqwrite-graid ${src_path}/09-randwrite-graid)
            	cp ${src_path}/01-seqread-graid ${src_path}/01-seqread-graid.bak
            	sed -i 's/offset_increment=\([0-9]*\)g/offset_increment=1g/' ${src_path}/01-seqread-graid
            	sed -i 's/size=\([0-9]*\)g/size=1g/' ${src_path}/01-seqread-graid
	   fi
	   sleep_time=5
        elif [[ $QUICK_TEST == "false" ]]; then
            task_list=($(ls -d src/fio-loop/*))
            cp src/fio-loop/01-seqread-graid src/fio-loop/01-seqread-graid.bak
            sed -i 's/offset_increment=\([0-9]*\)g/offset_increment='"$offsetsize"'g/' src/fio-loop/01-seqread-graid
            sed -i 's/size=\([0-9]*\)g/size='"$offsetsize"'g/' src/fio-loop/01-seqread-graid
            sleep_time=10
        fi
    else
        if [[ $QUICK_TEST == "true" ]]; then
            src_path=src/fio-loop-pd
             
            if [[ $DUMMY == "false" ]]; then
                task_list=(${src_path}/00-randread-graid ${src_path}/01-seqread-graid ${src_path}/02-seqwrite-graid ${src_path}/013-seqread-graid ${src_path}/03-randrw73-graid ${src_path}/06-randrw55-graid ${src_path}/09-randwrite-graid)
            else
                task_list=(${src_path}/00-randread-graid  ${src_path}/01-seqread-graid ${src_path}/02-seqwrite-graid ${src_path}/09-randwrite-graid)
            fi
            sleep_time=5
        elif [[ $QUICK_TEST == "false" ]]; then
            src_path=src/fio-loop-pd
            task_list=($(ls -d src/fio-loop-pd/*))
            sleep_time=10
        fi
    fi
}

function prestat() {
    get_disk_size
    
    
    new_stript=$1
    # echo $FIO_NAME
    if [[ "$FIO_NAME"  == "gdg0n1" ]]; then 
        vid=$(nvme id-ctrl /dev/gpd0  | grep -i "ssvid " | awk -F':' '{print $2}')
    else
        device=$(echo $NVME_LIST | awk '{print $1}')
        vid=$(nvme id-ctrl /dev/$device  | grep -i "ssvid " | awk -F':' '{print $2}')
    fi
    vid=$(echo $vid | tr -d '[:space:]')
    if [[ $DUMMY == "false" ]]; then
        sustain_time=3600
        #Micron 7450
        tvid="0x1344"
        local common_args="--size=${runsize}g --offset_increment=${runsize}g "
    else
        echo $vid
        sustain_time=36
        tvid="0x1af4"
        local common_args="--size=${runsize}g --offset_increment=${runsize}g --runtime=5"
    fi
    
    if [[ "${STAG}" == "afterprecondition" ]];  then
            echo "----precondition(1st)----"
            echo "STATUS: STATE: PRECONDITIONING"
            echo "STATUS: WORKLOAD: Precondition"
        if [[ "$DEV_NAME" != "PD" ]]; then
            fio src/precondition.fio --filename="/dev/$FIO_NAME" $common_args --output="$out_dir/$OUTPUT_NAME-precondition.log"
            sleep 5
        elif [[ "$DEV_NAME" == "PD" ]]; then
            if [[ $RUN_PD_ALL == "true" ]]; then
                sed -e 's/\[precondition\]//' src/precondition.fio > tfie
                for PD_NAME in "${NVME_LIST[@]}"; do
                    printf "[${PD_NAME}]\nfilename=/dev/${PD_NAME}\n" >> tfie
                done
                fio tfie $common_args --output="$out_dir/$OUTPUT_NAME-PD_ALL-precondition.log"
                rm -rf tfie
            else
                fio src/precondition.fio --filename=/dev/"$PD_NAME" $common_args --output="$out_dir/$OUTPUT_NAME-$PD_NAME-precondition.log"
            fi
        fi
    fi
    # if [[ "${STAG}" == "aftersustain" ]] && [[ "$vid" != '' ]]; then
    if [[ "${STAG}" == "aftersustain" ]] && [[ "$vid" != "$tvid" ]]; then
        echo "----precondition----"
        echo "STATUS: STATE: PRECONDITIONING"
        echo "STATUS: WORKLOAD: Precondition"
        if [[ "$DEV_NAME" != "PD" ]]; then
            fio src/precondition.fio --filename="/dev/$FIO_NAME" $common_args --output="$out_dir/$OUTPUT_NAME-precondition.log" &
            fio_pid=$!
            # Precondition can be long, but we just need one capture while it's running
            sleep 10
            trigger_snapshot "${OUTPUT_NAME}-${STAG}-precondition" "${fio_dir:-$out_dir}"
            wait $fio_pid
            sleep 2
        elif [[ "$DEV_NAME" == "PD" ]]; then
            if [[ $RUN_PD_ALL == "true" ]]; then
                sed -e 's/\[precondition\]//' src/precondition.fio > tfie
                for PD_NAME in "${NVME_LIST[@]}"; do
                    printf "[${PD_NAME}]\nfilename=/dev/${PD_NAME}\n" >> tfie
                done
                fio tfie $common_args --output="$out_dir/$OUTPUT_NAME-PD_ALL-precondition.log"
                rm -rf tfie
            else
                fio src/precondition.fio --filename=/dev/"$PD_NAME" $common_args --output="$out_dir/$OUTPUT_NAME-$PD_NAME-precondition.log"
            fi
        fi
        echo "----aftersustain----"
        echo "STATUS: STATE: SUSTAINING"
        echo "STATUS: WORKLOAD: Sustain Write"
        if [[ "$DEV_NAME" != "PD" ]]; then
            fio src/fio-loop/09-randwrite-graid --filename="/dev/$FIO_NAME" --runtime=$sustain_time --numjobs="$CPUJOBS" --cpus_allowed="$CPU_ALLOWED_SEQ" --output="$out_dir/$OUTPUT_NAME-sustain.log"
            sleep 5
        elif [[ "$DEV_NAME" == "PD" ]]; then
            if [[ $RUN_PD_ALL == "true" ]]; then
                rm -rf tfie
                sed -e 's/\[graid-test\]//' "$src_path/09-randwrite-graid" > tfie
                for PD_NAME in "${NVME_LIST[@]}"; do
                    printf "[${PD_NAME}]\nfilename=/dev/${PD_NAME}\n" >> tfie
                done
                fio tfie --runtime=$sustain_time --numjobs=8 --output="$result/$OUTPUT_NAME-PD_ALL-sustain.log"
                rm -rf tfie
            else
                fio "$src_path/09-randwrite-graid" --filename=/dev/"$PD_NAME" --runtime=$sustain_time --numjobs=8 --output="$out_dir/$OUTPUT_NAME-$PD_NAME-sustain.log"
            fi
        fi

    fi

    # if [[ "${STAG}" == "aftersustain" ]] && [[ "$vid" == '0x1af4' ]]; then
    if [[ "${STAG}" == "aftersustain" ]] && [[ "$vid" == "$tvid" ]]; then
        echo "----aftersustain----"
        echo "STATUS: STATE: SUSTAINING"
        echo "STATUS: WORKLOAD: Sustain Write"
        if [[ "$DEV_NAME" != "PD" ]]; then
            fio src/fio-loop/09-randwrite-graid --filename="/dev/$FIO_NAME" --runtime=$sustain_time --numjobs="$CPUJOBS" --cpus_allowed="$CPU_ALLOWED_SEQ" --output="$out_dir/$OUTPUT_NAME-sustain.log" &
            fio_pid=$!
            if (( sustain_time > 15 )); then
                sleep $((sustain_time - 12))
            else
                sleep $((sustain_time / 2))
            fi
            trigger_snapshot "${OUTPUT_NAME}-${STAG}-sustain" "${fio_dir:-$out_dir}"
            wait $fio_pid
            sleep 2
        elif [[ "$DEV_NAME" == "PD" ]]; then
            if [[ $RUN_PD_ALL == "true" ]]; then
                rm -rf tfie
                sed -e 's/\[graid-test\]//' "$src_path/09-randwrite-graid" > tfie
                for PD_NAME in "${NVME_LIST[@]}"; do
                    printf "[${PD_NAME}]\nfilename=/dev/${PD_NAME}\n" >> tfie
                done
                fio tfie --runtime=$sustain_time --numjobs=8 --output="$result/$OUTPUT_NAME-PD_ALL-sustain.log"
                rm -rf tfie
            else
                fio "$src_path/09-randwrite-graid" --filename=/dev/"$PD_NAME" --runtime=$sustain_time --numjobs=8 --output="$out_dir/$OUTPUT_NAME-$PD_NAME-sustain.log"
            fi
        fi
    fi
    # No generic trigger at the end anymore, move it inside FIO runs if appropriate
    # trigger_snapshot "${OUTPUT_NAME}-${STAG}" "$out_dir"
}


function kill_pid(){
    kill -9 $1 >/dev/null 2>&1
    wait $1 2>/dev/null
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
        nvme format -f "$device"
        nvme sanitize -a 2 "$device"
        check_sanitize_done "$device"
    fi
    


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

function run_task(){
        fio_file=$1
        device=$2
        run_time=$3
        job=$4
        cpus=$5
        fio_dir=$6
        of_name=$7
        qd=$8
        # echo ---run task----
        echo $1 $2 $3 $4 $5 $6 $7 $8
        fio_cmd_dir=${fio_dir}/cmd
        mkdir -p $fio_cmd_dir
        fio_pid_list=""
        # echo $fio_dir
        # echo $fio_cmd_dir
        if [[ $qd != "" ]] && [[ "$DEV_NAME" == "VD" || "$DEV_NAME" == "MD" ]]; then
            fio $fio_file --filename=/dev/$device --runtime=$run_time --numjobs=$job --cpus_allowed=$cpus --iodepth=$qd   --showcmd >> ${fio_cmd_dir}/${of_name}
            fio $fio_file --filename=/dev/$device --runtime=$run_time --numjobs=$job --cpus_allowed=$cpus --iodepth=$qd  --output=$fio_dir/$of_name.txt  &
            fio_pid_list="${fio_pid_list} $!"

        elif [[ $qd == "" ]] && [[ "$DEV_NAME" != "PD" ]] ; then
            # Default to first configured QD if not in batch mode loop
            local final_qd=${QD_LS[0]:-64}
            fio $fio_file --filename=/dev/$device --runtime=$run_time --numjobs=$job --cpus_allowed=$cpus --iodepth=$final_qd --showcmd >> ${fio_cmd_dir}/${of_name}
            fio $fio_file --filename=/dev/$device --runtime=$run_time --numjobs=$job --cpus_allowed=$cpus --iodepth=$final_qd --output=$fio_dir/$of_name.txt  &
            fio_pid_list="${fio_pid_list} $!"

        elif [[ $qd == "" ]] && [[ $RUN_PD_ALL == "true" ]]; then
	    
            fio $fio_file --runtime=$run_time --showcmd >> ${fio_cmd_dir}/${of_name}
            fio $fio_file --runtime=$run_time --output=$fio_dir/$of_name.txt  &
            fio_pid_list="${fio_pid_list} $!"
        elif [[ $qd == "" ]] && [[ $RUN_PD_ALL != "true" ]]; then
	    
            fio $fio_file --filename=/dev/$device --runtime=$run_time --numjobs=$job --cpus_allowed=$cpus  --showcmd >> ${fio_cmd_dir}/${of_name}
            fio $fio_file --filename=/dev/$device --runtime=$run_time --numjobs=$job --cpus_allowed=$cpus  --output=$fio_dir/$of_name.txt  &
            fio_pid_list="${fio_pid_list} $!"

        else
            #fio $fio_file --filename=/dev/$device --runtime=$run_time --numjobs=$job --cpus_allowed=$cpus --iodepth=$qd --showcmd >> ${fio_cmd_dir}/${of_name}
            fio $fio_file  --runtime=$run_time --numjobs=$job --cpus_allowed=$cpus --iodepth=$qd --showcmd >> ${fio_cmd_dir}/${of_name}
	    #cat $fio_file
            #fio $fio_file --filename=/dev/$device --runtime=$run_time --numjobs=$job --cpus_allowed=$cpus --iodepth=$qd --output=$fio_dir/$of_name.txt  &
            fio $fio_file  --runtime=$run_time --numjobs=$job --cpus_allowed=$cpus --iodepth=$qd --output=$fio_dir/$of_name.txt  &
            fio_pid_list="${fio_pid_list} $!"
        fi
        
        # echo ${iostat_pid_list}

        # Trigger Snapshot roughly 12 seconds before the end of the run
        if (( run_time > 15 )); then
            sleep $((run_time - 12))
            trigger_snapshot "$of_name" "$fio_dir"
            # Wait for FIO to finish (remaining 12s + some buffer)
            wait ${fio_pid_list}
        else
            # For short runs, capture in the middle
            sleep $((run_time / 2))
            trigger_snapshot "$of_name" "$fio_dir"
            wait ${fio_pid_list}
        fi
        
        # Give some time for frontend to process before cleanup
        sleep 2
        sync
        if [[ "$LOG_COMPACT" == "false" ]]; then
            kill_pid ${atop_pid_list}
        fi

        kill_pid ${iostat_pid_list}
        kill_pid ${ssd_pid_list}
        kill_pid ${cpu_pid_list}
        kill_pid ${gpu_pid_list}

        sleep $sleep_time

}

function run_test(){
    fio_dir=${out_dir}/${STAS}
    get_cpu_count
    # fio_cmd_dir=${vd_dir}/cmd
    # mkdir -p $fio_cmd_dir
    if [[ $DEV_NAME != "PD" ]]; then
        if [[ $LS_JB == "true" ]]; then
            for task in "${task_list[@]}"; do 
                echo "---$NVME_INFO-${STAS}-$RAID_MODE-${PD_NUMBER}PD-${task}---"
                rm -rf tfie 
                create_vd
                prestat ${task}
                if [[ $STAS == "Rebuild" ]]; then
                    rebuild_raid
                fi
                if [[ "$DEV_NAME" == "PD" ]]; then echo "STATUS: STATE: BENCHMARKING: ${STAS^^}"; else echo "STATUS: STATE: BENCHMARKING: ${RAID_MODE} - ${STAS^^}"; fi
                for QD in  "${QD_LS[@]}"; do
                    for JOBS in "${JOB_LS[@]}"; do
                        echo "STATUS: WORKLOAD: $(basename $task) - QD${QD} - ${JOBS}J"
                        update_progress
                        cp $task tfie
                        sed -i 's/iodepth=\([0-9]*\)//' tfie
                        cpu_seq=""
                        #get all cpu list and get the cpu_seq by added diff jobs
                        cpu_lst_node=$(cat /sys/devices/system/node/online | awk -F'-' '{print $NF}')
                        for node in $(seq 0 $cpu_lst_node); do
                            cpu_list=$(find_cpu_list_by_numa_node $node)
                            cpu_value=($(cut_cpu_list $cpu_list))
                            cpu_node_start_loc="${cpu_value[0]}"
                            cpu_seq=$cpu_seq,"$cpu_node_start_loc-$(($cpu_node_start_loc+"$JOBS"-1))"
                        done

                        if [[ "$JOBS" -eq 1 ]]; then
                            CPU_ALLOWED=0
                        elif [[ "$JOBS" -ge "$cpus_counts" ]]; then
                            CPU_ALLOWED=$CPU_ALLOWED_SEQ
                        else
                            CPU_ALLOWED=${cpu_seq:1}
                        fi

                        # echo "$JOBS" "$cpus_counts"
                        # echo $CPU_ALLOWED
                        OUTPUT_NAME_NEW="${OUTPUT_NAME}-${task:16:-1}-${STAS}-${JOBS}J-${QD}D"
                        # output_name=$1
                        # output_fio_dir=$2

                        collect_log $OUTPUT_NAME_NEW $fio_dir
                        run_task tfie $FIO_NAME $RUNTIME $JOBS $CPU_ALLOWED $fio_dir $OUTPUT_NAME_NEW $QD
                        if [[ $WCD == "true" ]]; then
                            wait_for_low_cpu_temp
                        fi
                    done
                done
                del_devcie
            done
        elif [[ $LS_BS == "true" ]]; then
            for task in "${task_list[@]}"; do 
                echo "---$NVME_INFO-${STAS}-$RAID_MODE-${PD_NUMBER}PD-${task}---"
                rm -rf tfie 
                create_vd
                prestat ${task}
                if [[ $STAS == "Rebuild" ]]; then
                    rebuild_raid
                fi
                if [[ "$DEV_NAME" == "PD" ]]; then echo "STATUS: STATE: BENCHMARKING: ${STAS^^}"; else echo "STATUS: STATE: BENCHMARKING: ${RAID_MODE} - ${STAS^^}"; fi
                for bs in  "${BS_LS[@]}"; do
                    echo "STATUS: WORKLOAD: $(basename $task) - ${bs}k"
                    update_progress
                    cp $task tfie
                    sed -i "s/^bs=.*/bs="$bs"k/" tfie
                    OUTPUT_NAME_NEW="$OUTPUT_NAME-${task:16:-1}-${STAS}-${bs}k"
                    collect_log $OUTPUT_NAME_NEW $fio_dir
                    run_task tfie $FIO_NAME $RUNTIME $CPUJOBS $CPU_ALLOWED_SEQ $fio_dir $OUTPUT_NAME_NEW $QD
                    if [[ $WCD == "true" ]]; then
                        wait_for_low_cpu_temp
                    fi
                done
                del_devcie
            done
        elif [[ $LS_CUST == "true" ]]; then
            for task in "${task_list[@]}"; do 
                if [[ "$DEV_NAME" == "PD" ]]; then echo "STATUS: STATE: BENCHMARKING: ${STAS^^}"; else echo "STATUS: STATE: BENCHMARKING: ${RAID_MODE} - ${STAS^^}"; fi
                rm -rf tfie 
                create_vd
                prestat ${task}
                if [[ $STAS == "Rebuild" ]]; then
                    rebuild_raid
                fi
                for bs in  "${QD_LS[@]}"; do
                    for QD in  "${QD_LS[@]}"; do
                        for JOBS in "${JOB_LS[@]}"; do
                            echo "STATUS: WORKLOAD: $(basename $task) - ${bs}k - QD${QD} - ${JOBS}J"
                            update_progress
                            cp $task tfie
                            sed -i 's/iodepth=\([0-9]*\)//' tfie
                            sed -i "s/^bs=.*/bs="$bs"k/" tfie
                            cpu_seq=""
                            #get all cpu list and get the cpu_seq by added diff jobs
                            cpu_lst_node=$(cat /sys/devices/system/node/online | awk -F'-' '{print $NF}')
                            for node in $(seq 0 $cpu_lst_node); do
                                cpu_list=$(find_cpu_list_by_numa_node $node)
                                cpu_value=($(cut_cpu_list $cpu_list))
                                cpu_node_start_loc="${cpu_value[0]}"
                                cpu_seq=$cpu_seq,"$cpu_node_start_loc-$(($cpu_node_start_loc+"$JOBS"-1))"
                            done

                            if [[ "$JOBS" -eq 1 ]]; then
                                CPU_ALLOWED=0
                            elif [[ "$JOBS" -ge "$cpus_counts" ]]; then
                                CPU_ALLOWED=$CPU_ALLOWED_SEQ
                            else
                                CPU_ALLOWED=${cpu_seq:1}
                            fi

                            OUTPUT_NAME_NEW="${OUTPUT_NAME}-${task:16:-1}-${STAS}-${JOBS}J-${QD}D-${bs}k"
                            collect_log $OUTPUT_NAME_NEW $fio_dir
                            run_task tfie $FIO_NAME $RUNTIME $JOBS $CPU_ALLOWED $fio_dir $OUTPUT_NAME_NEW $QD
                            if [[ $WCD == "true" ]]; then
                                wait_for_low_cpu_temp
                            fi
                        done
                    done
                done
                del_devcie
            done          
        else
            for task in "${task_list[@]}"; do 
                create_vd
                wait_for_device "/dev/$FIO_NAME"
                prestat ${task}
                if [[ $STAS == "Rebuild" ]]; then
                    rebuild_raid
                fi
                if [[ "$DEV_NAME" == "PD" ]]; then echo "STATUS: STATE: BENCHMARKING: ${STAS^^}"; else echo "STATUS: STATE: BENCHMARKING: ${RAID_MODE} - ${STAS^^}"; fi
                echo "STATUS: WORKLOAD: $(basename $task)"
                update_progress
                echo "---$NVME_INFO-${STAS}-$RAID_MODE-${PD_NUMBER}PD-${task}---"
                OUTPUT_NAME_NEW="$OUTPUT_NAME-${task:16:-1}-${STAS}"
                collect_log $OUTPUT_NAME_NEW $fio_dir
                run_task $task $FIO_NAME $RUNTIME $CPUJOBS $CPU_ALLOWED_SEQ $fio_dir $OUTPUT_NAME_NEW $QD
                del_devcie
            done
        fi

        
    elif [[ $DEV_NAME == "PD" ]]; then
        
        if [[ $LS_JB == "true" ]]; then
            #declare -A LAST_END_CPU_BY_NUMA
            for task in "${task_list[@]}"; do 
                # echo $PD_NAME
		        declare -A LAST_END_CPU_BY_NUMA
                discard_dev
                prestat ${task}
                if [[ "$DEV_NAME" == "PD" ]]; then echo "STATUS: STATE: BENCHMARKING: ${STAS^^}"; else echo "STATUS: STATE: BENCHMARKING: ${RAID_MODE} - ${STAS^^}"; fi
                rm -rf tfie
                for QD in  "${QD_LS[@]}"; do
                    unset LAST_END_CPU_BY_NUMA
                    declare -A LAST_END_CPU_BY_NUMA
                    
                    # sed -i 's/iodepth=\([0-9]*\)//' tfie
                    # echo "iodepth=${QD}" >> tfie
                    for JOBS in "${pd_jobs[@]}"; do
                        echo "STATUS: WORKLOAD: $(basename $task) - QD${QD} - ${JOBS}J"
                        update_progress
                    unset LAST_END_CPU_BY_NUMA
                    declare -A LAST_END_CPU_BY_NUMA
                        cpu_seq=""
                        #get all cpu list and get the cpu_seq by added diff jobs
                        cpu_lst_node=$(cat /sys/devices/system/node/online | awk -F'-' '{print $NF}')
                        for node in $(seq 0 $cpu_lst_node); do
                            cpu_list=$(find_cpu_list_by_numa_node $node)
                            cpu_value=($(cut_cpu_list $cpu_list))
                            cpu_node_start_loc="${cpu_value[0]}"
                            cpu_seq=$cpu_seq,"$cpu_node_start_loc-$(($cpu_node_start_loc+"$JOBS"-1))"
                        done

                        

                        if [[ $RUN_PD_ALL == "true" ]]; then
                            # Get the maximum physical core id in the system
                            MAX_CPU=$(get_physical_cores)
                            MAX_CPU=$((MAX_CPU - 1))
                            sed -e 's/\[graid-test\]//' $task > tfie
                            sed -i 's/iodepth=\([0-9]*\)//' tfie
                            echo "iodepth=${QD}" >> tfie
                            for PD_NAME in "${NVME_LIST[@]}"
                            do
                                echo "[${PD_NAME}]" >> tfie
                                echo "filename=/dev/${PD_NAME}" >> tfie
                                echo "numjobs=${JOBS}" >> tfie
                                # Output cpus_allowed only if the total required cores are within the physical core limit
                                if [[ "$JOBS" -le "$MAX_CPU" ]]; then
                                    # Use get_numa function to get the cpus_allowed value
                                    NUMA=$(find_numa_node "$PD_NAME")
                                    # Before calling get_numa
                                    LAST_END_CPU_BY_NUMA[$NUMA]=${LAST_END_CPU_BY_NUMA[$NUMA]:-}
				    
                                    # Then call get_numa as before
                                    CPU_ALLOWED=$(get_numa $PD_NAME $JOBS ${LAST_END_CPU_BY_NUMA[$NUMA]})
                                    LAST_END_CPU_BY_NUMA[$NUMA]=$(echo $CPU_ALLOWED | awk -F'-' '{print $2}')

                                    END_CPU=$(echo $CPU_ALLOWED | awk -F'-' '{print $2}')
                                    echo "DEBUG: NVMe Device: $PD_NAME"
                                    echo "DEBUG: NUMA Node: $NUMA"
                                    echo "DEBUG: Last End CPU for NUMA $NUMA: ${LAST_END_CPU_BY_NUMA[$NUMA]}"
                                    echo "DEBUG: CPU Allowed: $CPU_ALLOWED"
                                    echo "cpus_allowed=${CPU_ALLOWED}" >> tfie
                                    # Update the last CPU id for the corresponding NUMA node
                                    LAST_END_CPU_BY_NUMA[$NUMA]=$END_CPU
                                fi
                            done
                            
                            OUTPUT_NAME_NEW="$OUTPUT_NAME-BSALL-${task:16:-1}-${STAS}-${JOBS}J-${QD}D"
                            collect_log $OUTPUT_NAME_NEW $fio_dir
                            run_task tfie $PD_NAME $RUNTIME $JOBS $CPU_ALLOWED $fio_dir $OUTPUT_NAME_NEW
                            if [[ $WCD == "true" ]]; then
                                wait_for_low_cpu_temp
                            fi
                        else
                            OUTPUT_NAME_NEW="$OUTPUT_NAME-${PD_NAME}-${task:16:-1}-${STAS}-${JOBS}J-${QD}D"
                            CPU_ALLOWED=$(get_numa $PD_NAME $JOBS )
                            cp $task tfie
                            sed -i 's/iodepth=\([0-9]*\)//'  tfie
                            echo "iodepth=${QD}" >> tfie
                            #echo $JOBS

                            collect_log $OUTPUT_NAME_NEW $fio_dir 
                            run_task tfie $PD_NAME $RUNTIME $JOBS $CPU_ALLOWED $fio_dir $OUTPUT_NAME_NEW $QD
                            if [[ $WCD == "true" ]]; then
                                wait_for_low_cpu_temp
                            fi
                        fi
                    done
                done
            done


        else
            for task in "${task_list[@]}"; do 
                # echo $PD_NAME
                discard_dev
                prestat ${task}
                if [[ "$DEV_NAME" == "PD" ]]; then echo "STATUS: STATE: BENCHMARKING: ${STAS^^}"; else echo "STATUS: STATE: BENCHMARKING: ${RAID_MODE} - ${STAS^^}"; fi
                echo "STATUS: WORKLOAD: $(basename $task)"
                update_progress
                if [[ $RUN_PD_ALL == "true" ]]; then
                    rm -rf tfie
		    unset LAST_END_CPU_BY_NUMA
		    declare -A LAST_END_CPU_BY_NUMA

		    MAX_CPU=$(get_physical_cores)
		    MAX_CPU=$((MAX_CPU - 1))
                    sed -e 's/\[graid-test\]//' $task > tfie
                    
                    for PD_NAME in "${NVME_LIST[@]}"
                    do
                        echo "[${PD_NAME}]" >> tfie
                        echo "filename=/dev/${PD_NAME}" >> tfie
                        echo "numjobs=${pd_jobs}" >> tfie
                        if [[ "$pd_jobs" -le "$MAX_CPU" ]]; then
                            # Use get_numa function to get the cpus_allowed value
                            NUMA=$(find_numa_node "$PD_NAME")
                            # Before calling get_numa
                            LAST_END_CPU_BY_NUMA[$NUMA]=${LAST_END_CPU_BY_NUMA[$NUMA]:-}
                            echo "DEBUG: Last End CPU for NUMA $NUMA: ${LAST_END_CPU_BY_NUMA[$NUMA]}"
                            # Then call get_numa as before
                            CPU_ALLOWED=$(get_numa $PD_NAME $pd_jobs ${LAST_END_CPU_BY_NUMA[$NUMA]})
                            echo  $PD_NAME $JOBS ${LAST_END_CPU_BY_NUMA[$NUMA]}
                            LAST_END_CPU_BY_NUMA[$NUMA]=$(echo $CPU_ALLOWED | awk -F'-' '{print $2}')

                            END_CPU=$(echo $CPU_ALLOWED | awk -F'-' '{print $2}')
                            echo "DEBUG: NVMe Device: $PD_NAME"
                            echo "DEBUG: NUMA Node: $NUMA"
                            echo "DEBUG: Last End CPU for NUMA $NUMA: ${LAST_END_CPU_BY_NUMA[$NUMA]}"
                            echo "DEBUG: CPU Allowed: $CPU_ALLOWED"
                            echo "cpus_allowed=${CPU_ALLOWED}" >> tfie
                            # Update the last CPU id for the corresponding NUMA node
                            LAST_END_CPU_BY_NUMA[$NUMA]=$END_CPU
                        fi
                        
                    done

                    OUTPUT_NAME_NEW="$OUTPUT_NAME-BSALL-${task:16:-1}-${STAS}"
                    # CPU_ALLOWED=$(get_numa $PD_NAME $pd_jobs )
                    collect_log $OUTPUT_NAME_NEW $fio_dir
                    run_task tfie $PD_NAME $RUNTIME $pd_jobs $CPU_ALLOWED $fio_dir $OUTPUT_NAME_NEW $QD
                    if [[ $WCD == "true" ]]; then
                        wait_for_low_cpu_temp
                    fi
                else
                    OUTPUT_NAME_NEW="$OUTPUT_NAME-BS-${PD_NAME}-${task:16:-1}-${STAS}"
                    CPU_ALLOWED=$(get_numa $PD_NAME $pd_jobs )
                    collect_log $OUTPUT_NAME_NEW $fio_dir 
                    run_task $task $PD_NAME $RUNTIME $pd_jobs $CPU_ALLOWED_SEQ $fio_dir $OUTPUT_NAME_NEW $QD
                    if [[ $WCD == "true" ]]; then
                        wait_for_low_cpu_temp
                    fi
                fi
            done
        fi
    fi

}                   

function graid_bench(){

    if [[ $STAS == "Normal" ]]; then
        echo "----Running ${STAS}----"
        run_test
    elif [[ $STAS == "Rebuild" ]] && [[ $DEV_NAME == "VD" ]]; then
        echo "----Running ${STAS}----"
        if [ "${RAID_MODE}" != "RAID0" ]; then
            run_test
            tail -n 60 /var/log/graid/graid_server.log > ${out_dir}/${STAS}/Rebuild_$OUTPUT_NAME.log
        fi
    elif [[ $STAS == "Rebuild" ]] && [[ $DEV_NAME == "MD" ]]; then
        echo "----Running ${STAS}----"
        if [ "${RAID_MODE}" != "RAID0" ]; then
            run_test
            mdadm -D /dev/$MD_NAME > ${out_dir}/${STAS}/Rebuild_$OUTPUT_NAME.log
        fi
    fi
    del_devcie
    
}

function rebuild_raid(){
    echo "----Set RAID to rebuild---"
    # echo $DEV_NAME 
    if [[ $DEV_NAME == "VD" ]]; then
        graidctl edit pd $(($PD_NUMBER - 1)) marker offline 2>/dev/null
        graidctl edit pd $(($PD_NUMBER - 1)) marker online 2>/dev/null
    elif [[ $DEV_NAME == "MD" ]]; then
        # Get the last device from the NVME_LIST array
        lst_device="${NVME_LIST[${#NVME_LIST[@]}-1]}"
        echo "Managing device: $lst_device"
        # Mark the device as failed in the RAID array
        mdadm --fail "/dev/$MD_NAME" "/dev/$lst_device"
        # Remove the device from the RAID array
        mdadm --manage "/dev/$MD_NAME" -r "/dev/$lst_device"
        # Zero out the superblock on the device to make it usable as a standalone drive
        mdadm --zero-superblock "/dev/${lst_device}"
        # Wipe all filesystem signatures on the device to make sure it's clean
        wipefs -a "/dev/$lst_device"
        # Add the device back to the RAID array
        mdadm --manage "/dev/$MD_NAME" -a "/dev/$lst_device"
        # mdadm -D "/dev/$MD_NAME" 
    fi

}

function del_devcie(){
    if [[ "$DEV_NAME" == "VD" ]]; then
        echo "----Delete VD----"
        graidctl delete vd 0 0 --confirm-to-delete 2>/dev/null
        echo "----Delete DG----"
        graidctl delete dg 0 --confirm-to-delete 2>/dev/null
    elif [[ "$DEV_NAME" == "MD" ]]; then
        echo "----Delete MD----"
        mdadm -S /dev/$MD_NAME 2>/dev/null
        for device in "${NVME_LIST[@]}"
        do
            mdadm --zero-superblock "/dev/${device}" 2>/dev/null
            wait
            sleep 5
            wipefs -a /dev/${device} 2>/dev/null
            wait
            sleep 5
        done
    fi
        rm -rf test.json 
        rm -rf tfie
        rm -rf query-item
}



function detect_dev(){
    if [[ "$DEV_NAME" == "PD" ]]; then
        if [[ $RUN_PD_ALL == "false" ]]; then
            
            FIO_NAME=$PD_NVME
            echo $FIO_NAME
        else
            device=$(echo $NVME_LIST | awk '{print $1}')
            FIO_NAME=$device
            echo $FIO_NAME
        
        fi
    elif [[ "$DEV_NAME" == "VD" ]]; then
            echo $VD_NAME
            FIO_NAME=$VD_NAME
    elif [[ "$DEV_NAME" == "MD" ]]; then
            FIO_NAME=$MD_NAME
            case "$RAID_MODE" in
                RAID5) RAID=5
                    ;;
                RAID6) RAID=6
                    ;;
                RAID10) RAID=10
                    ;;
                RAID0) RAID=0
                    ;;
                RAID1) RAID=1
                    ;;
                *) echo "$RAID_MODE : unknow."
            esac
            echo start md
            sleep 5
    fi

}

function discard_dev(){
    echo $DEV_NAME
    echo "STATUS: STATE: DISCARD"
    echo "STATUS: WORKLOAD: Initializing..."
    if [[ "$DEV_NAME" == "PD" ]]; then
        if [[ $RUN_PD_ALL == "true" ]]; then
            PD_NAME=""
            # echo '12312'
            echo ${NVME_LIST[@]}
            for PD_NAME in "${NVME_LIST[@]}"
            do
                discard_device /dev/$PD_NAME &
            done
            wait
        else
            # blkdiscard $PD_NAME
            discard_device /dev/$PD_NAME
            wait
        fi

    elif [[ "$DEV_NAME" == "MD" ]] || [[ "$DEV_NAME" == "VD" ]]; then
        MD_NVME_LIST=""
        for I in "${NVME_LIST[@]}"; 
        do
            MD_NVME_LIST=${MD_NVME_LIST:+$MD_NVME_LIST }/dev/$I
            discard_device /dev/$I &
            
        done
        wait
    fi
}

function update_progress() {
    echo "STATUS: TICK"
}

detect_dev

output_name_dic
discard_dev
create_vd
get_disk_size
list_file
graid_bench





if [[ "$DEV_NAME" != "PD" ]]; then
    if [[ $QUICK_TEST == "true" ]]; then
        mv src/fio-loop/01-seqread-graid.bak src/fio-loop/01-seqread-graid
    elif [[ $QUICK_TEST == "false" ]]; then
        mv 01-seqread-graid.bak src/fio-loop/01-seqread-graid
    fi
fi

