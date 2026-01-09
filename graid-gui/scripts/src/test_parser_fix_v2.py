import pandas as pd
import os
import sys
from pathlib import Path

sys.path.append('/root/graid-benchmarking-gui/graid-gui/scripts/src')
from fio_parser import parser_fio

dummy_log_path = '/tmp/test_keyerror_v2.txt'
# Create a dummy log with enough content to not trigger search_and_delete
# and to be recognized as something by the loop
with open(dummy_log_path, 'w') as f:
    f.write("fio-3.39\n")
    f.write("test: (g=0): rw=randread, bs=4k, iodepth=32\n")

# Mock parse_iostat_file to prevent crash
import fio_parser
fio_parser.parse_iostat_file = lambda x: {'avg_user': '0.0', 'avg_system': '0.0', 'avg_idle': '100.0'}

try:
    print("Running parser_fio...")
    parser_fio(dummy_log_path)
    print("Parser completed successfully!")
    
    # Check if a CSV was created in 'result' folder relative to /tmp
    # parser_fio creates folder 'result' in same dir as log
    result_dir = Path('/tmp/result')
    csvs = list(result_dir.glob('*.csv'))
    if csvs:
        print(f"CSV created: {csvs[0]}")
        df = pd.read_csv(csvs[0])
        print("Columns in CSV:", df.columns.tolist())
        required_cols = ['Threads', 'Bandwidth (GB/s)', '99.99th']
        missing = [c for c in required_cols if c not in df.columns]
        if missing:
            print(f"FAILED: Missing columns: {missing}")
        else:
            print("SUCCESS: All required columns found!")
    else:
        print("FAILED: No CSV created.")

except Exception as e:
    import traceback
    traceback.print_exc()
    print(f"FAILED: An error occurred: {e}")
finally:
    if os.path.exists(dummy_log_path):
        os.remove(dummy_log_path)
    # Cleanup results
    if os.path.exists('/tmp/result'):
        import shutil
        shutil.rmtree('/tmp/result')
