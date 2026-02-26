import subprocess
import time
import os
import signal

# Start the app in a subprocess
process = subprocess.Popen(['python', 'app.py'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

# Wait for 10 seconds to let it initialize
time.sleep(10)

# Check if it's still running
retcode = process.poll()
if retcode is not None:
    print(f"Process terminated prematurely with code {retcode}")
    stdout, stderr = process.communicate()
    print("STDOUT:", stdout)
    print("STDERR:", stderr)
else:
    print("Process still running after 10s. Killing it...")
    # Send SIGINT to let it shut down gracefully and maybe output something
    os.kill(process.pid, signal.SIGINT)
    stdout, stderr = process.communicate()
    print("STDOUT:", stdout[:2000]) # Limit output
    print("STDERR:", stderr[:2000])
