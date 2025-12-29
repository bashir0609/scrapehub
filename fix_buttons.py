
import os
import re

path = r"e:\Apps\Python\ScrapeHub\templates\jobs\job_detail.html"

with open(path, "r", encoding="utf-8") as f:
    content = f.read()

# 1. Fix the split Pause button tag (cleanup my previous mess)
# Pattern matches the split tag I just created
pause_pattern_split = r'<button onclick="pauseJob\(\)" class="btn btn-pause" style="width: 100%;" {% if job.status !=\'running\'\s+.*?%}>'
# Replacement: clean single line
pause_replacement = '<button onclick="pauseJob()" class="btn btn-pause" style="width: 100%;" {% if job.status != \'running\' %}disabled{% endif %}>'

# We use regex to handle the whitespace/newlines
content = re.sub(pause_pattern_split, pause_replacement, content, flags=re.DOTALL)

# 2. Update Stop button
# Target: <button onclick="stopJob()" class="btn btn-stop" style="width: 100%;">
stop_target = '<button onclick="stopJob()" class="btn btn-stop" style="width: 100%;">'
stop_replacement = '<button onclick="stopJob()" class="btn btn-stop" style="width: 100%;" {% if job.status == \'completed\' or job.status == \'failed\' %}disabled{% endif %}>'

if stop_target in content:
    content = content.replace(stop_target, stop_replacement)
else:
    print("Stop button target not found exactly as expected.")

# 3. Handle Resume button (if I find it, I'll update the script in the next step, for now just fixing Pause/Stop)
# I will wait for grep search result to know where Resume is.

with open(path, "w", encoding="utf-8") as f:
    f.write(content)

print("Buttons updated.")
