import subprocess
import sys

print("=== ChatGPT Gallery Archiver ===")

script = "incremental_downloader.py"
print(f"\n>>> Downloading new images and regenerating gallery...")
result = subprocess.run([sys.executable, script])
if result.returncode == 0:
    print("\nAll steps completed successfully.")
else:
    print(f"Error running {script}")
