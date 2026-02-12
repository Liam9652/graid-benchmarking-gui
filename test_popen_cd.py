
import subprocess
import shlex

def test_popen_structure():
    # Setup
    env = {'FOO': 'bar'}
    cwd = '/tmp'
    target_cmd = ['ls', '-la']
    
    # Logic from app.py
    actual_binary_cmd = " ".join(shlex.quote(str(c)) for c in target_cmd)
    
    setup_parts = []
    if env:
        for k, v in env.items():
            setup_parts.append(f"export {k}={shlex.quote(str(v))}")
    if cwd:
        setup_parts.append(f"cd {shlex.quote(str(cwd))}")
        
    setup_str = " && ".join(setup_parts)
    if setup_str:
        wrapped_cmd = f"echo $$ && {setup_str} && exec {actual_binary_cmd}"
    else:
        wrapped_cmd = f"echo $$ && exec {actual_binary_cmd}"
        
    print(f"Executing: {wrapped_cmd}")
    
    # Execute locally to verify syntax
    process = subprocess.Popen(wrapped_cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    
    line = process.stdout.readline().strip()
    print(f"Captured PID: {line}")
    
    out, err = process.communicate()
    if err:
        print(f"Error: {err}")
    else:
        print("Success! No syntax error.")
        # print(f"Output: {out[:100]}...")

if __name__ == "__main__":
    test_popen_structure()
