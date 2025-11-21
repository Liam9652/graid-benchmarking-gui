#!/bin/bash
export LC_ALL=C

CLASS_VGA="0300"
CLASS_NVME="0108"
VENDOR_NVIDIA="10de"

rm -rf ./${foldname} 2> /dev/null

version()
{
    echo "Version: 0.0.11-20231019"
}

# Check the running shell and re-run with bash if necessary
if [ "$BASH" != "/bin/bash" ]; then
    /bin/bash "$0" "$@"
    exit $?
fi

while getopts "V" option; do
   case "$option" in
      V) # display version
         version
         exit;;
     \?) # incorrect option
         echo "Error: Invalid option"
         exit;;
   esac
done


if [[ $(whoami) != "root" ]]; then
	echo "Must be root or using sudo"
	exit 1
fi

function check_dependencies() {
    echo -n "Checking dependencies... "
    deps=0
    for name in jq nvme graidctl nvidia-smi
    do
        if [[ $(which $name 2>/dev/null) ]]; then
            continue
        fi
        
        case $(uname -s) in
            Linux)
                DISTRO_ID=$(get_distro)
                case $DISTRO_ID in
                    centos|almalinux|rocky|rhel|ol)
                        package_name=$(case $name in
                            jq) echo "jq";;
                            nvme) echo "nvme-cli";;
                            nvidia-smi) echo "nvidia-smi";;
                            *) echo "";;
                        esac)
                        pack='sudo yum install'
                        ;;
                    ubuntu|debian)
                        package_name=$(case $name in
                            jq) echo "jq";;
                            nvme) echo "nvme-cli";;
                            nvidia-smi) echo "nvidia-smi";;
                            *) echo "";;
                        esac)
                        pack='sudo apt install'
                        ;;
                    sled|sles|opensuse-leap)
                        package_name=$(case $name in
                            jq) echo "jq";;
                            nvme) echo "nvme-cli";;
                            nvidia-smi) echo "nvidia-smi";;
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
}


#PCI_DEVS+=("\"${class}\" \"${bdf}\" \"${name}\" \"${vendor}\" \"${device}\" \"${devname}\" \"${devaddr}\"")
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

declare -a PCI_DEVS
declare -A PCI_DRIVER


#IFS is still $'\n'
function gpu_id() {
	local bdf=${1^^}
#	echo "GPU_${bdf}"
	local gpu
	for line in $(nvidia-smi); do
		if ! [[ ${line} =~ ^\|\ *([0-9]+)\ .+[0]{8}:${bdf} ]]; then
			continue
		fi
		gpu=${BASH_REMATCH[1]}
		break
	done
	for line in $(nvidia-smi -L); do
		if ! [[ ${line} =~ ^GPU\ ${gpu}:.+UUID:\ ([^\)]+)\) ]]; then
			continue
		fi
		echo ${BASH_REMATCH[1]}
		break
	done
}

function list_pci_passthrough() {
	#0f:00.0 VGA compatible controller [0300]: NVIDIA Corporation TU117GLM [Quadro T1000 Mobile] [10de:1fb0] (rev a1)
	local PCI_DEVS_STR=
	local oldifs=${IFS}
	IFS=$'\n'
	local pcidev
	for pcidev in $(lspci -nn); do
		if [[ ${pcidev} =~ ^([0-9a-f]{2}:[0-9a-f]{2}.[0-9a-f])\ .+\ \[([0-9a-f]{4})\]:\ (.+)\ \[([0-9a-f]{4}):([0-9a-f]{4})\] ]]; then
			local bdf=${BASH_REMATCH[1]}
			local class=${BASH_REMATCH[2]}
			local name=${BASH_REMATCH[3]}
			local vendor=${BASH_REMATCH[4]}
			local device=${BASH_REMATCH[5]}
			local driver

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

			PCI_DBDF="0000:${bdf}"
			local numa_node=$(cat /sys/bus/pci/devices/${PCI_DBDF}/numa_node)
			local link_speed=$(cat /sys/bus/pci/devices/${PCI_DBDF}/current_link_speed)
			local link_width=$(cat /sys/bus/pci/devices/${PCI_DBDF}/current_link_width)
			local speed
			case ${link_speed} in
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

			local devname
			local devaddr
			case ${class} in
				${CLASS_NVME})
					devname=$(ls /sys/bus/pci/devices/${PCI_DBDF}/nvme 2>/dev/null)
					if ! [[ -f /sys/bus/pci/devices/${PCI_DBDF}/nvme/${devname}/subsysnqn ]]; then
						devname=$(ls /sys/bus/pci/devices/${PCI_DBDF}/gd 2>/dev/null)
						if ! [[ -f /sys/bus/pci/devices/${PCI_DBDF}/gd/${devname}/subsysnqn ]]; then
							continue
						else
							devaddr=$(cat /sys/bus/pci/devices/${PCI_DBDF}/gd/${devname}/subsysnqn)
						fi
					else
						devaddr=$(cat /sys/bus/pci/devices/${PCI_DBDF}/nvme/${devname}/subsysnqn)
					fi
					if [[ ${devaddr} =~ ^(.+[^\ ])[\ ]+$ ]]; then
						devaddr=${BASH_REMATCH[1]}
					fi
					;;
				${CLASS_VGA})
					devname=GPU
					devaddr=$(gpu_id ${bdf})
					if [[ -z ${devaddr} ]]; then
						continue
					fi
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

			if [[ -z ${PCI_DEVS_STR} ]]; then
				NL=
			else
				NL=$'\n'
			fi
			PCI_DEVS_STR="${PCI_DEVS_STR}${NL}\"${class}\" \"${bdf}\" \"${name}\" \"${vendor}\" \"${device}\" \"${devname}\" \"${devaddr}\" \"${numa_node}\" \"${speed}\""
		fi
	done
	for pcidev in $(echo "${PCI_DEVS_STR}" | sort); do
		PCI_DEVS+=(${pcidev})
	done
	IFS=${oldifs}
}

function parse_pci_attr_item() {
	local item=$1
	local attr
	local -a dev_attrs
	local oldifs=${IFS}
	IFS=$'\n'
	eval dev_attrs=\(${PCI_DEVS[$item]}\)
	for attr in "${!PCI_ATTR_IDX[@]}"; do
		local idx=${PCI_ATTR_IDX[${attr}]}
		local attr_val="${dev_attrs[${idx}]}"
		eval PCI_${attr}=\"${attr_val}\"
	done
	IFS=${oldifs}
}

function print_pci_devs() {
	local PCINUM=${#PCI_DEVS[@]}
	for ((i=0;i<$PCINUM;i++)); do
		parse_pci_attr_item ${i}
		printf "%6s(${PCI_BDF},${PCI_SPEED},NUMA:${PCI_NUMA}): ${PCI_DEV_ADDR} ${PCI_NAME}\n" ${PCI_DEV_NAME}
	done
}

function get_related_log() {
  
		mkdir -p ./${foldname}/basic_info
		mkdir -p ./${foldname}/graid_r
		mkdir -p ./${foldname}/logs
		mkdir -p ./${foldname}/logs/dkms_lib
        echo "============cpu info===============" >> ./${foldname}/basic_info/hw_info.log 
        lscpu >> ./${foldname}/basic_info/hw_info.log 2>/dev/null
        echo "============board name===============" >> ./${foldname}/basic_info/hw_info.log
        cat /sys/class/dmi/id/board_name >> ./${foldname}/basic_info/hw_info.log 2>/dev/null
		echo "============product name===============" >> ./${foldname}/basic_info/hw_info.log
        cat /sys/class/dmi/id/product_name >> ./${foldname}/basic_info/hw_info.log 2>/dev/null
		echo "============Vendor name===============" >> ./${foldname}/basic_info/hw_info.log
        cat /sys/class/dmi/id/sys_vendor >> ./${foldname}/basic_info/hw_info.log 2>/dev/null
        echo "============memory size===============" >> ./${foldname}/basic_info/hw_info.log
        free -m >> ./${foldname}/basic_info/hw_info.log 2>/dev/null
        dmidecode -t 17 >> ./${foldname}/basic_info/hw_info.log 2>/dev/null
        echo "RAM x `dmidecode -t 17 | grep "Memory Technology: DRAM" | wc -l`" >> ./${foldname}/basic_info/hw_info.log 2>/dev/null
		echo "============pci device list===============" >> ./${foldname}/basic_info/hw_info.log
		lspci -nn -vvv -PP >> ./${foldname}/basic_info/hw_info.log 2>/dev/null
		echo "============pci device tree list===============" >> ./${foldname}/basic_info/hw_info.log
		lspci -tnnvPP >> ./${foldname}/basic_info/hw_info.log 2>/dev/null
		echo "============dmiinfo===============" >> ./${foldname}/basic_info/hw_info.log
		dmidecode >> ./${foldname}/basic_info/hw_info.log 2>/dev/null

        echo "============os version=============" >> ./${foldname}/basic_info/sw_info.log
        cat /etc/*release >> ./${foldname}/basic_info/sw_info.log 2>/dev/null
        echo "============kernel version=========" >> ./${foldname}/basic_info/sw_info.log
        uname -r >> ./${foldname}/basic_info/sw_info.log 2>/dev/null
		echo "============nvidia-smi=============" >> ./${foldname}/basic_info/nv_info.log
        nvidia-smi -q >> ./${foldname}/basic_info/nv_info.log 2>/dev/null
        echo "============NV serial number=========" >> ./${foldname}/basic_info/sw_info.log
        nvidia-smi --query-gpu=index,name,serial,pcie.link.gen.current,pcie.link.width.current --format=csv >> ./${foldname}/basic_info/sw_info.log
		echo "============dkms version=========" >> ./${foldname}/basic_info/sw_info.log
        dkms status >> ./${foldname}/basic_info/sw_info.log 2>/dev/null

        os=`cat /etc/*release | grep "^NAME=*"`
        echo "OS : ${os:6:-1}"
        dmesg --time-format iso >> ./${foldname}/dmesg.log
        cp -a /var/log/graid/ ./${foldname}/graid_r/
        # cp -a /var/log/graid_pre_install/ ./${foldname}/graid_r/
		cp -a /var/log/graid-preinstaller/ ./${foldname}/graid_r/
		# get dmesg log 
		DMESG_PATH="/var/log/dmesg*"
		MESSAGES_PATH="/var/log/messages*"

		# check dmesg file exist or not
		for file in $DMESG_PATH
		do
			if [ -f "$file" ]; then
				cp "$file" ./${foldname}/logs/
			else
				echo "dmesg is not exist"
			fi
		done

		for file in $MESSAGES_PATH
		do
			if [ -f "$file" ]; then
				cp "$file" ./${foldname}/logs/
			else
				echo "messages is not exist"
			fi
		done

		cp /var/log/boot* ./${foldname}/logs/
		cp /etc/fstab ./${foldname}/basic_info/
		cp -r /var/lib/dkms/* ./${foldname}/logs/dkms_lib/

		sudo graidctl desc lic 2>/dev/null >> ./${foldname}/graid_r/graid_basic_info.log
		sudo graidctl version 2>/dev/null >> ./${foldname}/graid_r/graid_basic_info.log
		sudo graidctl ls vd --format json 2>/dev/null >> ./${foldname}/graid_r/graid_basic_info.log
		sudo graidctl ls dg --format json 2>/dev/null >> ./${foldname}/graid_r/graid_basic_info.log	
		sudo graidctl ls pd --format json 2>/dev/null >> ./${foldname}/graid_r/graid_basic_info.log
		sudo graidctl desc conf led --format json 1>> ./${foldname}/graid_r/graid_basic_info.log 2>/dev/null						
		journalctl -u graid >> ./${foldname}/graid_r/graid_server_journal.log
		journalctl -u graidcore@0.service >> ./${foldname}/graid_r/graid_core0_journal.log
		journalctl -u graidcore@1.service >> ./${foldname}/graid_r/graid_core1_journal.log
		journalctl -k -b all >> ./${foldname}/dmesg_journal.log
		sudo cat /proc/cmdline >> ./${foldname}/graid_r/check_cmdline.log
		cp /root/.bash_history  ./${foldname}/history_root_print.txt
		cp /home/*/.bash_history  ./${foldname}/history_user_print.txt

		# lscpu | grep 'Model name' | cut -f 2 -d ":" | awk '{$1=$1}1' >> ./${foldname}/basic.log
		server_manfacturer=`dmidecode -t system | grep Manufacturer  | awk '{print $0}'|cut -f 2 -d ":" | awk '{$1=$1}1'`
		server_model_name=`dmidecode -t system | grep 'Product Name'  | awk '{print $0}'|cut -f 2 -d ":" | awk '{$1=$1}1'` 
		cpu_model_name=`lscpu | grep 'Model name'| cut -f 2 -d ":" | awk '{$1=$1}1' ` 
		cpu_socket=`lscpu | grep ^Socket | uniq |  awk '{print $2}'`
		cpu_cout=`lscpu | grep ^Core | uniq |  awk '{print $4}'`
		memory_manfacturer=`dmidecode -t memory | grep 'Manufacturer' | grep -v 'Unknown' |head -n 1 |cut -f 2 -d ":" | awk '{$1=$1}1'`
		memory_part=`dmidecode -t memory | grep 'Part Number' | grep -v 'Unknown' |head -n 1 | cut -f 2 -d ":" | awk '{$1=$1}1'`
		memory_count=`dmidecode -t 17 | grep "Memory Technology: DRAM" | wc -l`
		os=`cat /etc/os-release | grep "^PRETTY_NAME=*" |cut -f 2 -d "=" | awk '{$1=$1}1'`
		secureboot=`mokutil --sb-state 2>/dev/null` 
		echo ServerVendor: $server_manfacturer >> ./${foldname}/basic.log
		echo ServerModel: $server_model_name >> ./${foldname}/basic.log
		echo CPU: $cpu_model_name x $cpu_socket >> ./${foldname}/basic.log
		echo Memory: $memory_manfacturer $memory_part x $memory_count >> ./${foldname}/basic.log
		echo Secureboot: $secureboot >> ./${foldname}/basic.log
		echo OS : $os >> ./${foldname}/basic.log
		echo Kernel version: `uname -r` >> ./${foldname}/basic.log
		echo NVcard Status: >> ./${foldname}/basic.log
		nvidia-smi --query-gpu=index,name,serial,pcie.link.gen.current,pcie.link.width.current --format=csv >> ./${foldname}/basic.log
		echo dkms status:  >> ./${foldname}/basic.log
		dkms status >> ./${foldname}/basic.log
		echo graid info: >> ./${foldname}/basic.log
		sudo graidctl version 2>/dev/null >> ./${foldname}/basic.log
		sudo graidctl desc lic 2>/dev/null >> ./${foldname}/basic.log
		dmidecode -t 1 >> ./${foldname}/basic.log


}

function get_nvme_info () {

	mkdir -p ./${foldname}/nvme
	local graid_cmd
	systemctl status graid >> /dev/null
	if [ $? -eq 0 ]; then
		graid_cmd=1
	fi
	echo "logging nvme info"
	nvme list > ./${foldname}/nvme/nvme_lst.log
	for nvme_node in /sys/block/*/device/device/numa_node; do

		if [[ ${nvme_node:11:4} == "nvme" ]]; then
			if ! [[ ${nvme_node} =~ ^\/sys\/block\/nvme([0-9]+)(c[0-9]+)?n([0-9]+)\/device\/device\/numa_node$ ]]; then
    			continue
			fi
			nvmen=${BASH_REMATCH[1]}
			echo "======================" >> ./${foldname}/nvme/nvme.log
			echo "nvme${nvmen}_node: $(cat ${nvme_node})" >> ./${foldname}/nvme/nvme.log
			echo "nvme${nvmen}_nqn:" `cat /sys/class/block/nvme${nvmen}*/device/subsysnqn` >> ./${foldname}/nvme/nvme.log
			echo "nvme${nvmen}_address:" `cat /sys/class/block/nvme${nvmen}*/device/address` >> ./${foldname}/nvme/nvme.log
			echo "nvme${nvmen}_device_id:" `cat /sys/class/block/nvme${nvmen}*/device/device/device` >> ./${foldname}/nvme/nvme.log
			echo "nvme${nvmen}_vender_id:" `cat /sys/class/block/nvme${nvmen}*/device/device/vendor` >> ./${foldname}/nvme/nvme.log
			echo "nvme${nvmen}_queue_count:" `cat /sys/class/block/nvme${nvmen}*/device/queue_count` >> ./${foldname}/nvme/nvme.log
			echo "nvme${nvmen}_current_link_speed:" `cat /sys/class/block/nvme${nvmen}*/device/device/current_link_speed` >> ./${foldname}/nvme/nvme.log
			echo "nvme${nvmen}_current_link_width:" `cat /sys/class/block/nvme${nvmen}*/device/device/current_link_width` >> ./${foldname}/nvme/nvme.log
			echo "nvme${nvmen}_max_link_speed:" `cat /sys/class/block/nvme${nvmen}*/device/device/max_link_speed` >> ./${foldname}/nvme/nvme.log
			echo "nvme${nvmen}_max_link_width:" `cat /sys/class/block/nvme${nvmen}*/device/device/max_link_width` >> ./${foldname}/nvme/nvme.log
			echo "nvme${nvmen}:" `sudo nvme id-ctrl /dev/nvme${nvmen}n1 -H | grep "ver "` >> ./${foldname}/nvme/nvme.log
			echo "nvme${nvmen}_Data Set Management:" `sudo nvme id-ctrl -H /dev/nvme${nvmen}n1 | grep "Data Set"` >> ./${foldname}/nvme/nvme.log
			echo "nvme${nvmen}_Deallocated:" `sudo nvme id-ns -H -n 1 /dev/nvme${nvmen}n1 | grep "Bytes Read"` >> ./${foldname}/nvme/nvme.log
			
			mkdir ./${foldname}/nvme/nvme${nvmen}
			sudo nvme get-feature -f 7 -s 0 -H /dev/nvme${nvmen}n1 >> ./${foldname}/nvme/nvme${nvmen}/nvme_info_detail.log
			echo "======================" >> ./${foldname}/nvme/nvme${nvmen}/nvme_info_detail.log
			sudo nvme get-feature -f 7 -s 1 -H /dev/nvme${nvmen}n1 >> ./${foldname}/nvme/nvme${nvmen}/nvme_info_detail.log
			echo "======================" >> ./${foldname}/nvme/nvme${nvmen}/nvme_info_detail.log
			sudo nvme id-ctrl -H /dev/nvme${nvmen}n1 >> ./${foldname}/nvme/nvme${nvmen}/nvme_info_detail.log
			echo "======================" >> ./${foldname}/nvme/nvme${nvmen}/nvme_info_detail.log
			sudo nvme id-ns -n 1 -H /dev/nvme${nvmen}n1 >> ./${foldname}/nvme/nvme${nvmen}/nvme_info_detail.log
			echo "======================" >> ./${foldname}/nvme/nvme${nvmen}/nvme_info_detail.log
			nvme show-regs -H /dev/nvme${nvmen}n1 >> ./${foldname}/nvme/nvme${nvmen}/nvme_info_detail.log
		elif [[ ${nvme_node:11:3} == "gpd" ]]; then
			if ! [[ ${nvme_node} =~ ^\/sys\/block\/gpd([0-9]+)n1\/device\/device\/numa_node$ ]]; then
					continue
			fi
			nvmen=${BASH_REMATCH[1]}
			echo "======================" >> ./${foldname}/nvme/nvme.log
			echo "gpd${nvmen}_node: $(cat ${nvme_node})" >> ./${foldname}/nvme/nvme.log
			echo "gpd${nvmen}_nqn:" `cat /sys/class/block/gpd${nvmen}*/device/subsysnqn` >> ./${foldname}/nvme/nvme.log
			echo "gpd${nvmen}_address:" `cat /sys/class/block/gpd${nvmen}*/device/address` >> ./${foldname}/nvme/nvme.log
			echo "gpd${nvmen}_device_id:" `cat /sys/class/block/gpd${nvmen}*/device/device/device` >> ./${foldname}/nvme/nvme.log
			echo "gpd${nvmen}_vender_id:" `cat /sys/class/block/gpd${nvmen}*/device/device/vendor` >> ./${foldname}/nvme/nvme.log
			echo "gpd${nvmen}_queue_count:" `cat /sys/class/block/gpd${nvmen}*/device/queue_count` >> ./${foldname}/nvme/nvme.log
			echo "gpd${nvmen}_current_link_speed:" `cat /sys/class/block/gpd${nvmen}*/device/device/current_link_speed` >> ./${foldname}/nvme/nvme.log
			echo "gpd${nvmen}_current_link_width:" `cat /sys/class/block/gpd${nvmen}*/device/device/current_link_width` >> ./${foldname}/nvme/nvme.log
			echo "gpd${nvmen}_max_link_speed:" `cat /sys/class/block/gpd${nvmen}*/device/device/max_link_speed` >> ./${foldname}/nvme/nvme.log
			echo "gpd${nvmen}_max_link_width:" `cat /sys/class/block/gpd${nvmen}*/device/device/max_link_width` >> ./${foldname}/nvme/nvme.log
			echo "gpd${nvmen}:" `sudo nvme id-ctrl -H /dev/gpd${nvmen}| grep "ver "` >> ./${foldname}/nvme/nvme.log
			echo "gpd${nvmen}_Data Set Management:" `sudo nvme id-ctrl -H /dev/gpd${nvmen} | grep "Data Set"` >> ./${foldname}/nvme/nvme.log
			echo "gpd${nvmen}_Deallocated:" `sudo nvme id-ns -H -n 1 /dev/gpd${nvmen} | grep "Bytes Read"` >> ./${foldname}/nvme/nvme.log
			
			mkdir ./${foldname}/nvme/gpd${nvmen}
			sudo nvme get-feature -f 7 -s 0 -H /dev/gpd${nvmen} >> ./${foldname}/nvme/gpd${nvmen}/nvme_info_detail.log 
			echo "======================" >> ./${foldname}/nvme/gpd${nvmen}/nvme_info_detail.log
			sudo nvme get-feature -f 7 -s 1 -H /dev/gpd${nvmen} >> ./${foldname}/nvme/gpd${nvmen}/nvme_info_detail.log
			echo "======================" >> ./${foldname}/nvme/gpd${nvmen}/nvme_info_detail.log
			sudo nvme id-ctrl -H /dev/gpd${nvmen} >> ./${foldname}/nvme/gpd${nvmen}/nvme_info_detail.log
			echo "======================" >> ./${foldname}/nvme/gpd${nvmen}/nvme_info_detail.log
			sudo nvme id-ns -n 1 -H /dev/gpd${nvmen} >> ./${foldname}/nvme/gpd${nvmen}/nvme_info_detail.log
			echo "======================" >> ./${foldname}/nvme/gpd${nvmen}/nvme_info_detail.log
			sudo nvme smart-log /dev/gpd${nvmen} >> ./${foldname}/nvme/gpd${nvmen}/nvme_info_detail.log
		fi


		done

}

function nvme_led_info(){

	# Find server information
	vendor_name=$(dmidecode -t system | awk -F': ' '/Manufacturer:/ {print $2}')
	server_product_name=$(dmidecode -t system | awk -F': ' '/Product Name:/ {print $2}' | tr ' ' '_')
	server_pn=$(dmidecode -t system | awk -F': ' '/Product Name:/ {print $2}')

	# Find all NVMe devices
	NVME_DEVICES=$(lspci -d ::0108 -D -PP | awk -F"/" '{print $(NF-1)}' | awk '{print $NF}' | tr '\n' ' ')
	# NVME_DEVICES=$(echo "$NVME_DEVICES" | cut -d'/' -f1) 
	# Check if any NVMe devices were found
	if [ -z "$NVME_DEVICES" ]; then
	echo "No NVMe devices found"
	exit 1
	fi
	
	echo "vendor: ${vendor_name}" > ./${foldname}/${server_product_name}.log
	echo "product: ${server_pn}" >> ./${foldname}/${server_product_name}.log

	echo "led_bdf:" >> ./${foldname}/${server_product_name}.log
	i=0
	# Loop through each NVMe device
	for BDF in $NVME_DEVICES; do
	# Get the PCIe Capability Pointer
	Cap_Ptr_Val=$(setpci -s $BDF 34.b)
	Cap_Ptr_Addr=$(setpci -s $BDF 0x"$Cap_Ptr_Val".b)
	echo "BDF: $BDF" >> ./${foldname}/${server_product_name}.log
	# Modify BDF variable to remove ":" and replace last occurrence with 0
	BDF=$(echo "$BDF" | tr -d ":")
	echo "  - 0x$(echo "${BDF:4:6}" | sed 's/\./0/g') # Slot ${i}" >> ./${foldname}/${server_product_name}_yaml.log
	echo "  - 0x$(echo "${BDF}" | sed 's/\./0/g') # Slot ${i}" >> ./${foldname}/${server_product_name}_yaml_v2.log
	i=$((i+1))

	done


	# set the Root Port BDF here
	Root_Port_BDF=$(echo "$NVME_DEVICES" | head -n1 | cut -d' ' -f1)

	# get the capability pointer value at offset 0x34
	Cap_Ptr_Val=$(setpci -s $Root_Port_BDF 0x34.b)

	# extract the capability pointer address from the value
	Cap_Ptr_Addr=$(setpci -s $Root_Port_BDF 0x"$Cap_Ptr_Val".b)

	# loop through the capability list to find the PCIe capability
	i=0
	while [ $i -lt 30 ]
	do
		# check if it's the PCIe capability
		if [[ $Cap_Ptr_Addr == "10" ]]; then
			# Get the Power State register and extract the indicator address
			PWR_ADDR=$(printf "0x%x" $((0x$Cap_Ptr_Val + 0x19)))

			# Get the Attention State register and extract the indicator address
			ATT_ADDR=$(printf "0x%x" $((0x$Cap_Ptr_Val + 0x18)))

			# print the results
			echo "PWR_ADDR: $PWR_ADDR" >> ./${foldname}/${server_product_name}.log
			echo "ATT_ADDR: $ATT_ADDR" >> ./${foldname}/${server_product_name}.log

			# exit the loop
			break
		fi

		# get the next capability pointer address
		Cap_ID=$Cap_Ptr_Val+$Cap_Ptr_Addr
		Cap_Ptr_Val=$(setpci -s $Root_Port_BDF 0x"$Cap_ID".b)
		Cap_Ptr_Addr=$(setpci -s $Root_Port_BDF 0x"$Cap_Ptr_Val".b)

		# check if it's the end of the capability list
		if [[ $Cap_Ptr_Addr == 0 ]]; then
			echo "PCIe capability not found." >> ./${foldname}/${server_product_name}.log
			break
		fi
		i=$((i+1))
	done

}




function compress_log() {
    timestamp=$(date '+%Y-%m-%d')
    tar_file="graid_log_$timestamp.tar.gz"

    # Check if the target compression file already exists
    if [ -f "$tar_file" ]; then
        echo "Target compression file $tar_file already exists."
        return
    fi

    tar -czPf "$tar_file" ./${foldname}

    # Check if the compression was successful
    if [ $? -eq 0 ]; then
        echo "Compression completed: $tar_file"

        # Optional: Delete the original log files
        # rm -rf ./${foldname}
    else
        echo "Compression failed."
    fi

    unset LC_ALL
}

timestamp=$(date '+%Y%m%d')
foldname=logs-`hostname`-"$timestamp"
rm -rf graid_log_*.tar
rm -rf ./logs-*/
mkdir ./${foldname}/
list_pci_passthrough >> ./${foldname}/pci_passthrough_list.log
print_pci_devs >> ./${foldname}/print_pci_devs_list.log
get_related_log
get_nvme_info
nvme_led_info
compress_log