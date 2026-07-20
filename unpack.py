import json
import base64
import gzip
import re
import os

html_path = "/Users/meetdeshani/Desktop/HQ/Platform (standalone).html"
output_dir = "/Users/meetdeshani/Desktop/HQ/unpacked_platform"

os.makedirs(output_dir, exist_ok=True)

with open(html_path, "r", encoding="utf-8") as f:
    content = f.read()

# Find the manifest script block
manifest_match = re.search(r'<script type="__bundler/manifest">(.*?)</script>', content, re.DOTALL)
if not manifest_match:
    print("Manifest not found")
    exit(1)

manifest_json = json.loads(manifest_match.group(1).strip())

# Find the page order if present
page_order_match = re.search(r'<script type="__bundler/page_order">(.*?)</script>', content, re.DOTALL)
page_order = json.loads(page_order_match.group(1).strip()) if page_order_match else []

# Find external resources
ext_res_match = re.search(r'<script type="__bundler/ext_resources">(.*?)</script>', content, re.DOTALL)
ext_resources = json.loads(ext_res_match.group(1).strip()) if ext_res_match else []

print(f"Loaded {len(manifest_json)} assets from manifest.")
print(f"Page order: {page_order}")
print(f"External resources map: {len(ext_resources)} entries")

uuid_to_id = {item["uuid"]: item["id"] for item in ext_resources}

for uuid, entry in manifest_json.items():
    mime = entry["mime"]
    compressed = entry["compressed"]
    b64_data = entry["data"]
    
    data = base64.b64decode(b64_data)
    if compressed:
        try:
            data = gzip.decompress(data)
        except Exception as e:
            print(f"Gzip decompress failed for {uuid}: {e}")
            
    # Determine file name
    res_id = uuid_to_id.get(uuid, uuid)
    
    # Try to make a clean filename
    if res_id.startswith("http"):
        # external URL, clean it up
        clean_name = res_id.replace("https://", "").replace("http://", "").replace("/", "_").replace(":", "_")
    else:
        clean_name = res_id
        
    # Append appropriate extension if not present
    if not os.path.splitext(clean_name)[1]:
        if "html" in mime:
            clean_name += ".html"
        elif "javascript" in mime or "js" in mime:
            clean_name += ".js"
        elif "css" in mime:
            clean_name += ".css"
        elif "json" in mime:
            clean_name += ".json"
            
    out_path = os.path.join(output_dir, clean_name)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    
    # If the file content is text, write as text
    if "text" in mime or "javascript" in mime or "json" in mime or "css" in mime:
        try:
            text_content = data.decode("utf-8")
            with open(out_path, "w", encoding="utf-8") as out_f:
                out_f.write(text_content)
            print(f"Saved text asset: {clean_name} ({len(text_content)} chars)")
            continue
        except UnicodeDecodeError:
            pass
            
    with open(out_path, "wb") as out_f:
        out_f.write(data)
    print(f"Saved binary asset: {clean_name} ({len(data)} bytes)")

# Also extract the main template
template_match = re.search(r'<script type="__bundler/template">(.*?)</script>', content, re.DOTALL)
if template_match:
    template_json = json.loads(template_match.group(1).strip())
    template_path = os.path.join(output_dir, "template.html")
    with open(template_path, "w", encoding="utf-8") as out_f:
        out_f.write(template_json)
    print("Saved template.html")
