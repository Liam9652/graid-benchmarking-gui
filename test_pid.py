
import subprocess

def test_pid_capture():
    # Simulate what RemoteExecutor.Popen does
    cmd = "echo $$ && exec sleep 10"
    process = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, text=True)
    
    # Read the first line (PID)
    pid_line = process.stdout.readline().strip()
    print(f"Captured PID: {pid_line}")
    
    # Verify process is running
    state = subprocess.run(["ps", "-p", pid_line], capture_output=True, text=True)
    print(f"Process state:\n{state.stdout}")
    
    # Terminate
    subprocess.run(["kill", "-TERM", pid_line])
    print("Sent SIGTERM")

if __name__ == "__main__":
    test_pid_capture()
