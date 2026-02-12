
# Simulated AB Test for giostat parsing
# Case A: Old parsing logic (indexed)
# Case B: New parsing logic (header-aware)

def old_parse(line):
    parts = line.trim().split()
    # parts[1] was r/s, but what if a new column is inserted at [1]?
    return float(parts[2]) # bw_read

def new_parse(headers, parts):
    header_map = {h: i for i, h in enumerate(headers)}
    def get_val(keys):
        for k in keys:
            if k in header_map: return float(parts[header_map[k]])
        return 0.0
    return get_val(['rMB/s', 'rkB/s'])

# Sample 1: Standard output
headers1 = ['Device', 'r/s', 'rMB/s', 'await']
parts1 = ['nvme0n1', '100', '500', '1.2']
print(f"Sample 1 - New Parse: {new_parse(headers1, parts1)} MB/s")

# Sample 2: Shifted output (e.g., new column 'tps' added at index 1)
headers2 = ['Device', 'tps', 'rio/s', 'rkB/s', 'await']
parts2 = ['nvme0n1', '50', '100', '512000', '1.2'] # 512000 KB/s = 500 MB/s
# Old logic would take parts[2] -> '100' instead of bandwidth
print(f"Sample 2 - New Parse (rkB/s): {new_parse(headers2, parts2) / 1024} MB/s")
