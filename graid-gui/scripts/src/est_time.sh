#!/bin/bash

convert_seconds() {
    local total_seconds=$1
    local days=$((total_seconds / 86400))
    local hours=$(( (total_seconds % 86400) / 3600))
    local minutes=$(( (total_seconds % 3600) / 60))

    printf "%02d:%02d:%02d\n" $days $hours $minutes 
}

get_disk_size() {
    local runsize=64  # Default fallback 64GB
    local found=0
    for device in "${NVME_LIST[@]}"; do
        if [[ -b "/dev/${device}" ]]; then
            if [[ "$device" == nvme* ]]; then
                local tnvmcap=$(nvme id-ctrl -H "/dev/${device}" 2>/dev/null | grep tnvmcap | uniq | awk '{print $3}' | tr -d ',')
                if [[ -n "$tnvmcap" ]]; then
                    local size=$((tnvmcap / 512))
                    runsize=$((size / (20 * 1000 * 1000)))
                    found=1
                    break
                fi
            elif [[ "$device" == sd* ]]; then
                local cap=$(sg_readcap "/dev/$device" 2>/dev/null | grep Device | awk '{print $3}')
                if [[ -n "$cap" ]]; then
                    runsize=$((cap / (20 * 1024 * 1024 * 1024)))
                    found=1
                    break
                fi
            fi
        fi
    done
    
    # If no device found, try to get from any nvme device as fallback
    if [[ $found -eq 0 ]]; then
        local backup_dev=$(ls /dev/nvme*n1 2>/dev/null | head -n 1)
        if [[ -n "$backup_dev" ]]; then
            local tnvmcap=$(nvme id-ctrl -H "$backup_dev" 2>/dev/null | grep tnvmcap | uniq | awk '{print $3}' | tr -d ',')
            if [[ -n "$tnvmcap" ]]; then
                local size=$((tnvmcap / 512))
                runsize=$((size / (20 * 1000 * 1000)))
            fi
        fi
    fi
    echo $runsize
}

# Source the configuration file
if [ -f "graid-bench-advanced.conf" ]; then
    . ./graid-bench-advanced.conf
fi
. ./graid-bench.conf

# Define counts based on the configuration arrays
NVME_COUNT=${#NVME_LIST[@]} 
RAID_TYPE_COUNT=${#RAID_TYPE[@]} 
RAID_STATUS_COUNT=${#STA_LS[@]} 
JOB_LS_COUNT=${#JOB_LS[@]} 
DEPTH_COUNT=${#QD_LS[@]} 
BS_COUNT=${#BS_LS[@]} 
PD_JOBS_COUNT=${#pd_jobs[@]} 
TS_LS_COUNT=${#TS_LS[@]}

# Accurate Workload counts (matching bench.sh)
if [[ "$QUICK_TEST" == "true" ]]; then
    WL_COUNT_VD=4
    WL_COUNT_PD=$([[ "$DUMMY" == "true" ]] && echo 4 || echo 7)
else
    WL_COUNT_VD=12
    WL_COUNT_PD=13
fi

# Multipliers based on LS flags
VD_LOOP_FACTOR=1
if [[ "$LS_JB" == "true" ]]; then
    VD_LOOP_FACTOR=$((DEPTH_COUNT * JOB_LS_COUNT))
elif [[ "$LS_BS" == "true" ]]; then
    VD_LOOP_FACTOR=$((BS_COUNT + 1))
elif [[ "$LS_CUST" == "true" ]]; then
    VD_LOOP_FACTOR=$((DEPTH_COUNT * DEPTH_COUNT * JOB_LS_COUNT))
fi

PD_LOOP_FACTOR=1
if [[ "$LS_JB" == "true" ]]; then
    PD_LOOP_FACTOR=$((DEPTH_COUNT * PD_JOBS_COUNT))
fi

# Device factors
PD_RUN=$([[ "$RUN_PD" == "true" ]] && echo 1 || echo 0)
VD_RUN=$([[ "$RUN_VD" == "true" || "$RUN_MD" == "true" ]] && echo 1 || echo 0)

# Parallel vs Sequential PD
PD_PARALLEL_FACTOR=$([[ "$RUN_PD_ALL" == "true" ]] && echo 1 || echo $NVME_COUNT)

# Preparation times (per occurrence)
RUNSIZE_GB=$(get_disk_size)
PRECOND_TIME=0
if [[ "$DUMMY" == "true" ]]; then
    PRECOND_TIME=10  # 5s + buffer
    SUSTAIN_TIME=40  # 36s + buffer
else
    # Estimate preconditioning rate ~ 500MB/s (for 4PDs 128MB/s each?) 
    # Let's use a more conservative rate: 1GB per 10s -> 100MB/s
    PRECOND_TIME=$((RUNSIZE_GB * 10)) 
    SUSTAIN_TIME=3605
fi

# Initialization buffers
DISCARD_TIME=30
RAID_INIT_BUFFER=200 # Waiting for DG optimal + 15s sleep

# Total Estimated Time Calculation
TOTAL_SECONDS=0

# 1. PD Test Phase
if [[ "$PD_RUN" == 1 ]]; then
    # Loops in graid-bench.sh: for STAG in "${TS_LS[@]}"
    for STAG in "${TS_LS[@]}"; do
        # bench.sh is called once with all PDs if RUN_PD_ALL=true, or N times if false
        # But inside bench.sh, it loops over task_list
        # For each task, it runs prestat and then FIO
        
        # Discard happens once per bench.sh call
        TOTAL_SECONDS=$((TOTAL_SECONDS + DISCARD_TIME * PD_PARALLEL_FACTOR))
        
        # Tasks
        PHASE_TIME=0
        for task_idx in $(seq 1 $WL_COUNT_PD); do
            # Preparation in prestat
            PREP_TIME=0
            if [[ "$STAG" == "afterprecondition" ]]; then
                PREP_TIME=$((PREP_TIME + PRECOND_TIME))
            elif [[ "$STAG" == "aftersustain" ]]; then
                PREP_TIME=$((PREP_TIME + PRECOND_TIME + SUSTAIN_TIME))
            fi
            
            # Sub-test FIO loop (QD/Jobs)
            TEST_TIME=$(( (PD_RUNTIME + 10) * PD_LOOP_FACTOR ))
            
            PHASE_TIME=$((PHASE_TIME + PREP_TIME + TEST_TIME))
        done
        
        TOTAL_SECONDS=$((TOTAL_SECONDS + PHASE_TIME * PD_PARALLEL_FACTOR))
    done
fi

# 2. VD/MD Test Phase
if [[ "$VD_RUN" == 1 ]]; then
    # Loops in graid-bench.sh: for STATUS x for STAG x for RAID
    RAID_TYPES_ACTIVE=$RAID_TYPE_COUNT
    STATUS_ACTIVE=$RAID_STATUS_COUNT
    STAG_ACTIVE=$TS_LS_COUNT
    
    # Each combination calls bench.sh
    COMBO_COUNT=$((RAID_TYPES_ACTIVE * STATUS_ACTIVE * STAG_ACTIVE))
    
    # Let's recalibrate the VD loop more accurately
    VD_PHASE_TIME=0
    for STAG in "${TS_LS[@]}"; do
        # Time for one STAG phase (e.g., afterprecondition)
        STAG_PREP=0
        if [[ "$STAG" == "afterprecondition" ]]; then
            STAG_PREP=$PRECOND_TIME
        elif [[ "$STAG" == "aftersustain" ]]; then
            STAG_PREP=$((PRECOND_TIME + SUSTAIN_TIME))
        fi
        
        # One bench.sh run for this STAG x RAID x STATUS
        ONE_RUN_TIME=$(( (DISCARD_TIME + RAID_INIT_BUFFER) + (STAG_PREP + (VD_RUNTIME + 10) * VD_LOOP_FACTOR) * WL_COUNT_VD ))
        
        VD_PHASE_TIME=$((VD_PHASE_TIME + ONE_RUN_TIME * RAID_TYPES_ACTIVE * STATUS_ACTIVE))
    done
    TOTAL_SECONDS=$((TOTAL_SECONDS + VD_PHASE_TIME))
fi

# Final adjustment with RAID_FACTOR
buffered_seconds=$(bc <<< "scale=0; ($TOTAL_SECONDS * 1.15) / 1")

FORMATTED_TIME=$(convert_seconds $buffered_seconds)
echo "Estimated Completion Time: $FORMATTED_TIME (dd:hh:mm)"

