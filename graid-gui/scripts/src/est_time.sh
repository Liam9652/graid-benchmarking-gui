#!/bin/bash

convert_seconds() {
    local total_seconds=$1
    local days=$((total_seconds / 86400))
    local hours=$(( (total_seconds % 86400) / 3600))
    local minutes=$(( (total_seconds % 3600) / 60))

    printf "%02d:%02d:%02d\n" $days $hours $minutes 
}

get_disk_size() {
    local runsize=0
    local device=$(echo "$NVME_LIST" | awk '{print $1}')
    if [[ "$device" == nvme* ]]; then
        local nvme_sector=$(nvme id-ctrl -H "/dev/${device}" 2>/dev/null | grep tnvmcap | uniq | awk '{print $3}')
        local size=$((nvme_sector / 512))
        runsize=$((size / (20 * 1000 * 1000)))
    elif [[ "$device" == sd* ]]; then
        runsize=$(($(sudo sg_readcap "/dev/$device" | grep Device | awk '{print $3}') / (20 * 1024 * 1024 * 1024)))
    fi
    echo $runsize
}

# Source the configuration file
. ./graid-bench.conf

# Define counts based on the configuration arrays
NVME_COUNT=${#NVME_LIST[@]} 
RAID_TYPE_COUNT=${#RAID_TYPE[@]} 
RAID_STATUS_COUNT=${#STA_LS[@]} 
JOB_COUNT=${#JOB_LS[@]} 
DEPTH_COUNT=${#QD_LS[@]} 
BS_COUNT=${#BS_LS[@]} 
PD_JOBS_COUNT=${#pd_jobs[@]} 
TS_LS_COUNT=${#TS_LS[@]}

# Define the additional variables and factors
TS_AP_PD_RATE=7
TS_AP_MD_RATE=5
TS_AP_MR_RATE=3
RAID_FACTOR=1.15

RAID_STATUS_FACTOR=$RAID_STATUS_COUNT

WL_FACTOR=$([[ "$QUICK_TEST" == "true" ]] && echo 7 || echo 12)

DEPTH_FACTOR=$([[ "$LS_JB" == "true" ]] && echo $DEPTH_COUNT || echo 1)
PD_JOBS_FACTOR=$([[ "$LS_JB" == "true" ]] && echo $PD_JOBS_COUNT || echo 1)
BS_FACTOR=$([[ "$LS_BS" == "true" ]] && echo $BS_COUNT || echo 1)
PD_FACTOR=$([[ "$RUN_PD" == "true" ]] && echo 1 || echo 0)
VD_FACTOR=$([[ "$RUN_VD" == "true" ]] && echo 1 || echo 0)
MD_FACTOR=$([[ "$RUN_MD" == "true" ]] && echo 1 || echo 0)
MR_FACTOR=$([[ "$RUN_MR" == "true" ]] && echo 1 || echo 0)
PD_ALL_FACTOR=$([[ "$RUN_PD_ALL" == "true" ]] && echo 1 || echo 0)

JOB_FACTOR=$([[ "$LS_JB" == "true" ]] && echo $JOB_COUNT || echo 1)

TOTAL_SIZE=$(($(get_disk_size) * NVME_COUNT))

NVME_FACTOR=$([[ $PD_ALL_FACTOR == 0 ]] && echo $NVME_COUNT || echo 1)

# Set default values for times based on test scenarios
TS_DIS=0
TS_AS=0
AP_FLAG=0
TS_AP_VD=0
TS_AP_PD=0
TS_AP_MD=0
TS_AP_MR=0

# Calculate times based on test scenarios
for test in "${TS_LS[@]}"; do
    case "$test" in
        afterdiscard)
            TS_DIS=30
            ;;
        afterprecondition)
            TS_AP_PD=$((TOTAL_SIZE/TS_AP_PD_RATE*2*PD_FACTOR))
            TS_AP_VD=$((20*60*2*VD_FACTOR))
            TS_AP_MD=$((TOTAL_SIZE/TS_AP_MD_RATE*2*MD_FACTOR))
            TS_AP_MR=$((TOTAL_SIZE/TS_AP_MR_RATE*2*MR_FACTOR))
	    AP_FLAG=1
            ;;
        aftersustain)
            TS_AS=$((3600*2))
            ;;
    esac
done

if [[ "$AP_FLAG" == 1 ]];then
	TS_AS=$((TS_AS + TS_AP_PD  + TS_AP_VD + TS_AP_MD + TS_AP_MR))
fi	



# Add additional time to PD and VD runtimes if necessary
PD_RUNTIME=$((PD_RUNTIME + 10))
VD_RUNTIME=$((VD_RUNTIME + 10))

# Calculating PD and VD runtime totals
PD_runtime_TOTAL=$(bc <<< "scale=0; $PD_RUNTIME * $TS_LS_COUNT * $WL_FACTOR * $DEPTH_FACTOR * $BS_FACTOR * $PD_JOBS_FACTOR ")
VD_runtime_TOTAL=$(bc <<< "scale=0; $VD_RUNTIME * $TS_LS_COUNT * ($VD_FACTOR + $MD_FACTOR + $MR_FACTOR) * $WL_FACTOR * $DEPTH_FACTOR * $BS_FACTOR * $JOB_COUNT * $RAID_STATUS_FACTOR * $RAID_TYPE_COUNT ")

# Calculating total preparation time
TOTAL_PREPARE_TIME=$(( (WL_FACTOR ) * (TS_DIS + TS_AP_VD + TS_AP_PD + TS_AP_MD + TS_AP_MR + TS_AS) ))

# Calculate estimated time
Estimated_Time=$(bc <<< "scale=0; $PD_runtime_TOTAL + $VD_runtime_TOTAL + $TOTAL_PREPARE_TIME")
buffered_seconds=$(bc <<< "scale=0; $Estimated_Time * $RAID_FACTOR/1")


#echo "JOB_COUNT: $JOB_COUNT, JOB_FACTOR: $JOB_FACTOR, DEPTH_COUNT: $DEPTH_COUNT"
#echo "DEPTH_FACTOR: $DEPTH_FACTOR, BS_COUNT: $BS_COUNT, BS_FACTOR: $BS_FACTOR"
#echo "PD_JOBS_COUNT: $PD_JOBS_COUNT, PD_JOBS_FACTOR: $PD_JOBS_FACTOR"

#echo "PD_runtime_TOTAL: $PD_runtime_TOTAL, PD_RUNTIME: $PD_RUNTIME, NVME_FACTOR: $NVME_FACTOR, PD_FACTOR: $PD_FACTOR, WL_FACTOR: $WL_FACTOR"

#echo "VD_runtime_TOTAL: $VD_runtime_TOTAL, VD_RUNTIME: $VD_RUNTIME, VD_FACTOR: $VD_FACTOR, MD_FACTOR: $MD_FACTOR, MR_FACTOR: $MR_FACTOR"
#echo "WL_FACTOR: $WL_FACTOR, RAID_STATUS_FACTOR: $RAID_STATUS_FACTOR, RAID_TYPE_COUNT: $RAID_TYPE_COUNT"

#echo "TOTAL_PREPARE_TIME: $TOTAL_PREPARE_TIME, TS:$((TS_DIS + TS_AP_VD + TS_AP_PD + TS_AP_MD + TS_AP_MR + TS_AS))"
#echo "$Estimated_Time"
#echo "$buffered_seconds"
# Make sure we are passing an integer to convert_seconds
FORMATTED_TIME=$(convert_seconds $buffered_seconds)
#FORMATTED_TIME=$(convert_seconds $Estimated_Time)
echo "Estimated Completion Time: $FORMATTED_TIME (dd:hh:mm)"

