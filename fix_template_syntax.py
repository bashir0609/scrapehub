import re

# Read the file
with open('templates/jobs/job_detail.html', 'r', encoding='utf-8') as f:
    content = f.read()

# Fix the specific syntax errors
# Fix: |default: 0 -> |default:0
content = re.sub(r'\|default:\s*0', '|default:0', content)

# Fix: { { -> {{
content = re.sub(r'\{\s+\{', '{{', content)
content = re.sub(r'\}\s+\}', '}}', content)

# Write back
with open('templates/jobs/job_detail.html', 'w', encoding='utf-8') as f:
    f.write(content)

print("✓ Fixed template syntax errors")
print("✓ Removed spaces from |default: filters")
print("✓ Fixed broken curly braces")
