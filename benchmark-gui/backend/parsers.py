"""Output parsers and system-info collectors.

Pure functions called by fastapi_app's system-info / results endpoints.
None of these mutate global state.
"""

import json
import re
from pathlib import Path

from config import logger


_PCIE_INFO_CMD = r"""
for ctrl_dir in /sys/class/nvme/nvme*; do
  [ -d "$ctrl_dir" ] || continue
  ctrl=$(basename "$ctrl_dir")
  pci_dev=$(readlink -f "$ctrl_dir/device" 2>/dev/null)
  [ -d "$pci_dev" ] || continue
  [ -f "$pci_dev/current_link_speed" ] || continue
  found_ns=0
  for ns_dir in "$ctrl_dir"/"$ctrl"n*; do
    [ -e "$ns_dir" ] || continue
    ns=$(basename "$ns_dir")
    printf '%s\t%s\t%s\t%s\t%s\n' \
      "$ns" \
      "$(cat "$pci_dev/current_link_speed" 2>/dev/null)" \
      "$(cat "$pci_dev/current_link_width" 2>/dev/null)" \
      "$(cat "$pci_dev/max_link_speed" 2>/dev/null)" \
      "$(cat "$pci_dev/max_link_width" 2>/dev/null)"
    found_ns=1
  done
  if [ "$found_ns" = "0" ]; then
    printf '%s\t%s\t%s\t%s\t%s\n' \
      "${ctrl}n1" \
      "$(cat "$pci_dev/current_link_speed" 2>/dev/null)" \
      "$(cat "$pci_dev/current_link_width" 2>/dev/null)" \
      "$(cat "$pci_dev/max_link_speed" 2>/dev/null)" \
      "$(cat "$pci_dev/max_link_width" 2>/dev/null)"
  fi
done
""".strip()


def _collect_nvme_pcie_info(executor):
    """Return dict keyed by block device name (e.g. 'nvme0n1') with PCIe link fields."""
    pcie = {}
    try:
        res = executor.run(['bash', '-c', _PCIE_INFO_CMD], capture_output=True, text=True)
        if res.returncode == 0:
            for line in res.stdout.splitlines():
                parts = line.split('\t')
                if len(parts) == 5:
                    dev, cur_spd, cur_w, max_spd, max_w = parts
                    try:
                        cur_w_int = int(cur_w.strip())
                        max_w_int = int(max_w.strip())
                    except ValueError:
                        cur_w_int = max_w_int = 0
                    pcie[dev.strip()] = {
                        'pcie_current_speed': cur_spd.strip(),
                        'pcie_current_width': cur_w_int,
                        'pcie_max_speed': max_spd.strip(),
                        'pcie_max_width': max_w_int,
                        'pcie_at_max': (cur_spd.strip() == max_spd.strip() and cur_w_int == max_w_int),
                    }
    except Exception as e:
        logger.debug("PCIe info collection failed: %s", e)
    return pcie


def _collect_device_usage(executor):
    """Return dict keyed by block device name (e.g. 'nvme0n1') listing reasons it's in use.

    Checks for: partitions with filesystem/mount, mdadm RAID membership,
    LVM physical volumes, LUKS encryption, direct mounts.
    Uses `lsblk -J` so a single SSH call covers all devices at once.
    """
    usage = {}
    try:
        res = executor.run(
            ['lsblk', '-J', '-o', 'NAME,TYPE,FSTYPE,MOUNTPOINT'],
            capture_output=True, text=True,
        )
        if res.returncode != 0:
            return usage

        data = json.loads(res.stdout)

        def _scan(node, reasons):
            """Recursively inspect a lsblk node and its children for usage indicators."""
            ctype  = node.get('type', '')
            fstype = node.get('fstype') or ''
            mount  = node.get('mountpoint') or ''

            if fstype == 'linux_raid_member':
                reasons.append('mdadm RAID member')
            elif 'raid' in ctype.lower():
                reasons.append('mdadm RAID')

            if ctype == 'lvm' or 'lvm2' in fstype.lower():
                reasons.append('LVM physical volume')

            if 'crypt' in ctype:
                reasons.append('LUKS encrypted')

            if mount:
                reasons.append(f'mounted at {mount}')
            elif fstype and ctype == 'part' and fstype not in ('', 'swap'):
                reasons.append(f'partition ({fstype})')
            elif ctype == 'part' and not fstype and not mount:
                reasons.append('partition exists')

            for child in node.get('children') or []:
                _scan(child, reasons)

        for blkdev in data.get('blockdevices', []):
            name = blkdev.get('name', '')
            if not name.startswith('nvme'):
                continue
            reasons = []
            # Check device-level mount/fs (raw device without partitions)
            top_fstype = blkdev.get('fstype') or ''
            top_mount  = blkdev.get('mountpoint') or ''
            if top_mount:
                reasons.append(f'mounted at {top_mount}')
            if top_fstype == 'linux_raid_member':
                reasons.append('mdadm RAID member')
            elif top_fstype and top_fstype not in ('', 'NVMe'):
                reasons.append(f'filesystem: {top_fstype}')

            for child in blkdev.get('children') or []:
                _scan(child, reasons)

            if reasons:
                # Deduplicate while preserving order
                seen = set()
                deduped = []
                for r in reasons:
                    if r not in seen:
                        seen.add(r)
                        deduped.append(r)
                usage[name] = deduped

    except Exception as e:
        logger.debug("Device usage check failed: %s", e)
    return usage


def _collect_gpu_perf(executor):
    """Run nvidia-smi -q -d performance and parse throttle-reason states per GPU."""
    gpus = []
    try:
        res = executor.run(['nvidia-smi', '-q', '-d', 'performance'], capture_output=True, text=True)
        if res.returncode == 0:
            current = None
            in_throttle = False
            for line in res.stdout.splitlines():
                s = line.strip()
                if s.startswith('GPU '):
                    current = {'id': s, 'performance_state': None, 'idle': True, 'active_reasons': []}
                    gpus.append(current)
                    in_throttle = False
                elif current is not None:
                    if 'Performance State' in s:
                        current['performance_state'] = s.split(':', 1)[1].strip()
                    elif 'Clocks Throttle Reasons' in s or 'Clocks Event Reasons' in s:
                        in_throttle = True
                    elif in_throttle and ':' in s:
                        reason, _, state = s.partition(':')
                        reason = reason.strip()
                        state = state.strip()
                        if reason == 'Idle' and state == 'Not Active':
                            current['idle'] = False
                        elif reason != 'Idle' and state == 'Active':
                            current['active_reasons'].append(reason)
    except Exception as e:
        logger.debug("nvidia-smi performance check failed: %s", e)
    return gpus


def parse_graidctl_json(output):
    """Parses JSON from graidctl output, skipping the first checkmark line if present."""
    if not output:
        return {}
    lines = output.strip().split('\n')
    json_str = ""
    for line in lines:
        if line.strip().startswith('{'):
            json_str = '\n'.join(lines[lines.index(line):])
            break
    if not json_str:
        return {}
    return json.loads(json_str)


def _extract_raid_from_cmd_dir(parent_dir):
    """Extract RAID type from filenames in cmd/ or raid_config/ sibling directory."""
    for subdir_name in ('cmd', 'raid_config'):
        candidate = Path(parent_dir) / subdir_name
        if candidate.is_dir():
            for f in candidate.iterdir():
                m = re.search(r'(RAID\d+)', f.name)
                if m:
                    return m.group(1)
    return None
