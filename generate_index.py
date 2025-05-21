import os

os.makedirs("gallery", exist_ok=True)
gallery_root = "gallery"
versions = sorted(
    [folder for folder in os.listdir(gallery_root)
     if folder.startswith("v") and os.path.isdir(os.path.join(gallery_root, folder))],
    key=lambda x: int(x[1:])
)

html = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Image Gallery Index</title>
<style>
body { font-family: sans-serif; margin: 30px; }
h1 { margin-bottom: 20px; }
.version-block {
    margin-bottom: 30px;
    border: 1px solid #ccc;
    padding: 15px;
    border-radius: 8px;
}
.version-title {
    font-size: 1.2em;
    font-weight: bold;
    margin-bottom: 10px;
}
.page-links {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
    gap: 8px;
}
a {
    text-decoration: none;
    padding: 6px;
    display: block;
    background: #f5f5f5;
    border: 1px solid #ddd;
    border-radius: 4px;
    text-align: center;
    color: #333;
}
a:hover {
    background: #e0e0e0;
}
</style>
</head>
<body>
<h1>Image Gallery Index</h1>
"""

for version in versions:
    version_path = os.path.join(gallery_root, version)
    page_files = sorted([
        f for f in os.listdir(version_path)
        if f.startswith("page_") and f.endswith(".html")
    ], key=lambda f: int(f.split("_")[1].split(".")[0]))

    if not page_files:
        continue

    html += f"<div class='version-block'>\n"
    html += f"<div class='version-title'>{version} ({len(page_files)} page{'s' if len(page_files) != 1 else ''})</div>\n"
    html += f"<div class='page-links'>\n"
    for page in page_files:
        html += f'<a href="{version}/{page}">{page}</a>\n'
    html += "</div>\n</div>\n"

html += "</body></html>"

with open(os.path.join(gallery_root, "index.html"), "w", encoding="utf-8") as f:
    f.write(html)

print("Generated index.html")
