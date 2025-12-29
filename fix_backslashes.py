
import os

path = r"e:\Apps\Python\ScrapeHub\templates\jobs\job_detail.html"

with open(path, "r", encoding="utf-8") as f:
    content = f.read()

# Remove backslashes before single quotes in the Django tags I just touched
# We look for \%} or \' which might have been introduced
content = content.replace(r"\'", "'")

with open(path, "w", encoding="utf-8") as f:
    f.write(content)

print("Removed backslashes.")
