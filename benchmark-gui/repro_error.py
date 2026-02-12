import subprocess
import time
import re

ANSI_ESCAPE = re.compile(r'(?:\x1B[@-_][0-?]*[ -/]*[@-~])')

def strip_ansi(text):
    return ANSI_ESCAPE.sub('', text)

def run_test():
    cmd = ['bash', './scripts/mock_bench.sh']
    print(f"Running: {cmd}")
    
    process = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, 
        cwd='/root/graid-benchmarking-gui/benchmark-gui', text=True, bufsize=1
    )
    
    last_error = None
    
    while True:
        line = process.stdout.readline()
        if line:
            msg = strip_ansi(line.strip())
            print(f"READ: {msg}")
            
            if "STATUS: ERROR:" in msg:
                try:
                    error_msg = msg.split("STATUS: ERROR:")[1].strip()
                    print(f"DETECTED ERROR: {error_msg}")
                    last_error = error_msg
                except Exception as e:
                    print(f"Error parsing error: {e}")
        else:
            if process.poll() is not None:
                break
                
    process.wait()
    print(f"Return Code: {process.returncode}")
    print(f"Last Error: {last_error}")

if __name__ == "__main__":
    run_test()
