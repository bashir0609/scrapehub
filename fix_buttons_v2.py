
import os
import re

path = r"e:\Apps\Python\ScrapeHub\templates\jobs\job_detail.html"

with open(path, "r", encoding="utf-8") as f:
    content = f.read()

# Helper to join split tags
def join_split_tags(text):
    # Pattern: {% if ... \n ... %}
    # We want to find cases where {% if ... %} is split across lines
    return re.sub(r'({%\s*if\s+[^%]+)\n\s*(%})', r'\1 \2', text)

# Specifically target the button attribute lines which are causing issues
# 1. Pause button
# <button ... {% if job.status !='running'\n %}disabled{% endif %}>
content = re.sub(
    r'(<button onclick="pauseJob\(\)"[^>]+?){%\s*if\s+job\.status\s*!=\s*\'running\'\s*\n\s*%}disabled{%\s*endif\s*%}',
    r'\1{% if job.status != \'running\' %}disabled{% endif %}',
    content,
    flags=re.DOTALL
)

# 2. Stop button
# <button ... {% if job.status=='completed'\n or job.status=='failed' %}disabled{% endif %}>
content = re.sub(
    r'(<button onclick="stopJob\(\)"[^>]+?){%\s*if\s+job\.status\s*==\s*\'completed\'\s*\n\s*or\s+job\.status\s*==\s*\'failed\'\s*%}disabled{%\s*endif\s*%}',
    r'\1{% if job.status == \'completed\' or job.status == \'failed\' %}disabled{% endif %}',
    content,
    flags=re.DOTALL
)

# 3. Resume button (just in case)
content = re.sub(
    r'(<button onclick="resumeJob\(\)"[^>]+?){%\s*if\s+job\.status\s*!=\s*\'paused\'\s+and\s+job\.status\s*!=\s*\'auto_paused\'\s*\n\s*%}disabled{%\s*endif\s*%}',
    r'\1{% if job.status != \'paused\' and job.status != \'auto_paused\' %}disabled{% endif %}',
    content,
    flags=re.DOTALL
)

# Generic fallback for any remaining split tags inside buttons
content = re.sub(
    r'(<button[^>]+){%\s*if([^%]+)\n\s*%}disabled',
    r'\1{% if\2 %}disabled',
    content
)

with open(path, "w", encoding="utf-8") as f:
    f.write(content)

print("Fixed split tags.")
