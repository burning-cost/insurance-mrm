# Databricks notebook source
# COMMAND ----------

# MAGIC %md
# MAGIC # insurance-mrm: test runner

# COMMAND ----------

import subprocess
import sys
import os
import shutil

# Install the library from the workspace copy
result = subprocess.run(
    [sys.executable, "-m", "pip", "install", "-e", "/Workspace/insurance-mrm", "--quiet"],
    capture_output=True,
    text=True,
)
if result.returncode != 0:
    print("pip install FAILED:", result.stderr[-3000:])
else:
    print("Install OK")

# COMMAND ----------

# Copy the project to /tmp (workspace FS doesn't support __pycache__)
src = "/Workspace/insurance-mrm"
dst = "/tmp/insurance-mrm"
if os.path.exists(dst):
    shutil.rmtree(dst)
shutil.copytree(src, dst, ignore=shutil.ignore_patterns(".git", "__pycache__", "*.pyc"))
print("Copied to", dst)

# Re-install from the /tmp copy so pytest can write cache files
result = subprocess.run(
    [sys.executable, "-m", "pip", "install", "-e", dst, "--quiet"],
    capture_output=True,
    text=True,
)
if result.returncode != 0:
    print("Re-install FAILED:", result.stderr[-3000:])

# COMMAND ----------

# Run pytest from /tmp
result = subprocess.run(
    [
        sys.executable, "-m", "pytest",
        f"{dst}/tests",
        "-v",
        "--tb=short",
        "--no-header",
        "-p", "no:cacheprovider",
    ],
    capture_output=True,
    text=True,
    cwd=dst,
)
full_output = result.stdout + ("\nSTDERR:\n" + result.stderr if result.stderr else "")
print(full_output)

summary_lines = [l for l in result.stdout.split("\n") if l.strip()]
result_lines = "\n".join(summary_lines[-50:])
dbutils.notebook.exit(f"RC={result.returncode}\n{result_lines}")
