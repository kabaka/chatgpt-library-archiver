import json
import os
from datetime import datetime

# Detect latest batch version
gallery_root = "gallery"
versions = sorted(
    [int(folder[1:]) for folder in os.listdir(gallery_root)
     if folder.startswith("v") and os.path.isdir(os.path.join(gallery_root, folder))],
    reverse=True
)
if not versions:
    print("No versioned folders found in 'gallery/'.")
    exit()

latest = versions[0]
version_folder = f"v{latest}"
version_path = os.path.join(gallery_root, version_folder)
meta_path = os.path.join(version_path, f"metadata_v{latest}.json")
image_dir = "images"
output_dir = version_path
images_per_page = 500

# Load metadata
with open(meta_path, "r", encoding="utf-8") as f:
    metadata = json.load(f)

metadata.sort(key=lambda x: x.get("created_at", 0), reverse=True)
pages = [metadata[i:i + images_per_page] for i in range(0, len(metadata), images_per_page)]

def generate_html(page_items, page_num, total_pages):
    html = f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Gallery {version_folder} – Page {page_num}</title>
<style>
body {{
    font-family: sans-serif;
    margin: 20px;
    background-color: white;
    color: black;
    transition: background 0.3s, color 0.3s;
}}
body.dark {{
    background-color: #111;
    color: #eee;
}}
.gallery-grid {{
    display: grid;
    gap: 15px;
}}
.gallery-small {{
    grid-template-columns: repeat(6, 1fr);
}}
.gallery-medium {{
    grid-template-columns: repeat(4, 1fr);
}}
.gallery-large {{
    grid-template-columns: repeat(2, 1fr);
}}
.image-card {{
    border: 1px solid #ccc;
    padding: 8px;
    border-radius: 8px;
    font-size: 0.85em;
    background: white;
}}
body.dark .image-card {{
    background: #222;
}}
img {{
    width: 100%;
    border-radius: 4px;
    display: block;
}}
.meta {{
    margin-top: 6px;
    color: #444;
}}
body.dark .meta {{
    color: #ccc;
}}
h1 {{
    margin-bottom: 10px;
}}
.search-bar {{
    margin-bottom: 15px;
    display: flex;
    gap: 10px;
    align-items: center;
}}
.search-bar input {{
    padding: 6px;
    font-size: 1em;
    width: 300px;
}}
.controls {{
    display: flex;
    justify-content: flex-end;
    gap: 10px;
    margin-bottom: 15px;
}}
.toggle {{
    background: #ddd;
    border-radius: 5px;
    padding: 6px 10px;
    cursor: pointer;
    font-size: 0.9em;
}}
body.dark .toggle {{
    background: #555;
    color: white;
}}
.size-select {{
    background: #ddd;
    border-radius: 5px;
    padding: 6px 10px;
    cursor: pointer;
    font-size: 0.9em;
}}
body.dark .size-select {{
    background: #555;
    color: white;
}}
</style>
</head>
<body>
<div class="controls">
  <div class="size-select">
    <strong>Select Image Size: </strong>
    <select id="sizeSelector" onchange="changeSize()">
      <option value="gallery-small">Small</option>
      <option value="gallery-medium" selected>Medium</option>
      <option value="gallery-large">Large</option>
    </select>
  </div>
  <div class="toggle" onclick="toggleDarkMode()">Toggle Dark Mode</div>
</div>
<h1>Gallery {version_folder} – Page {page_num} of {total_pages}</h1>
<div class="search-bar">
    <input type="text" id="searchBox" placeholder="Search by title..." oninput="filterGallery()">
</div>
<div class="gallery-grid gallery-medium" id="gallery">
'''

    for item in page_items:
        created = datetime.utcfromtimestamp(item.get("created_at", 0)).strftime('%Y-%m-%d %H:%M:%S')
        title = item.get("title") or ""
        data_title = title.lower()
        tags = ", ".join(item.get("tags", [])) or "—"
        html += f'''
<div class="image-card" data-title="{data_title}">
  <a href="{image_dir}/{item['filename']}" target="_blank">
    <img src="{image_dir}/{item['filename']}" alt="{title}">
  </a>
  <div class="meta">
    <strong>{title or item['id']}</strong><br>
    {created}<br>
    Tags: {tags}<br>
    <a href="{item.get('conversation_link', '#')}" target="_blank">View conversation</a>
  </div>
</div>'''

    html += '''
</div><div style='text-align:center;margin-top:30px;'>'''
    if page_num > 1:
        html += f'<a href="page_{page_num - 1}.html">&laquo; Prev</a> '
    if page_num < total_pages:
        html += f'<a href="page_{page_num + 1}.html">Next &raquo;</a>'
    html += '''</div>
<script>
function toggleDarkMode() {
    document.body.classList.toggle('dark');
    localStorage.setItem('theme', document.body.classList.contains('dark') ? 'dark' : 'light');
}
if (localStorage.getItem('theme') === 'dark') {
    document.body.classList.add('dark');
}

function filterGallery() {
    const input = document.getElementById('searchBox').value.toLowerCase();
    const cards = document.querySelectorAll('.image-card');
    cards.forEach(card => {
        const title = card.dataset.title;
        card.style.display = title.includes(input) ? '' : 'none';
    });
}

function changeSize() {
    const gallery = document.getElementById('gallery');
    gallery.className = 'gallery-grid ' + document.getElementById('sizeSelector').value;
}
</script>
</body></html>'''
    return html

for i, page in enumerate(pages):
    html = generate_html(page, i + 1, len(pages))
    with open(os.path.join(output_dir, f"page_{i+1}.html"), "w", encoding="utf-8") as f:
        f.write(html)

print(f"Gallery HTML with search, dark mode, and image size toggle generated in '{version_path}/'.")
