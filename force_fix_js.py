
path = r"e:\Apps\Python\ScrapeHub\templates\jobs\job_detail.html"
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

# exact string to match
broken = """            let lastProcessedItems = {{ job.processed_items }
        };"""

fixed = """            let lastProcessedItems = {{ job.processed_items }};"""

if broken in content:
    new_content = content.replace(broken, fixed)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(new_content)
    print("Fixed!")
else:
    print("Could not find the broken string exactly as defined.")
    # Debug finding
    import re
    match = re.search(r'let lastProcessedItems = \{\{ job.processed_items \}\s*\n\s*\};', content)
    if match:
        print("Found regex match, fixing...")
        new_content = re.sub(r'let lastProcessedItems = \{\{ job.processed_items \}\s*\n\s*\};', 
                             'let lastProcessedItems = {{ job.processed_items }};', content)
        with open(path, 'w', encoding='utf-8') as f:
            f.write(new_content)
        print("Fixed via regex!")
    else:
        print("Could not find broken pattern even with regex.")

