import subprocess
import sys

print("=== ChatGPT Gallery Archiver ===")

scripts = [
    ("incremental_downloader.py", "Downloading new images..."),
    ("generate_gallery_batch.py", "Generating gallery pages..."),
    ("generate_index.py", "Updating index page...")
]

for script, message in scripts:
    print(f"\n>>> {message}")
    result = subprocess.run([sys.executable, script])
    if result.returncode != 0:
        print(f"Error running {script}")
        break
else:
    print("\nAll steps completed successfully.")
