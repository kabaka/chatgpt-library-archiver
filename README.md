# ChatGPT Library Archiver

This is a Python-based toolset for downloading, archiving, and browsing images generated via ChatGPT (4o Image Generator). It stores all images in versioned folders and generates static HTML galleries for easy viewing.

---

## 📦 Folder Structure

```
gallery/
├── v1/
│   ├── images/
│   ├── metadata_v1.json
│   ├── page_1.html, page_2.html, ...
├── v2/
│   └── ...
├── index.html  ← main entry point
auth.txt        ← credentials for API access
```

---

## ⚙️ 1. Setup Instructions

### 🔹 Requirements

- Python 3.7+
- Internet connection
- Your browser access to [chat.openai.com](https://chat.openai.com)

### 🔹 Install Dependencies

None required beyond standard `requests`, `concurrent.futures`, `tqdm` and `json`.

---

## 🛠 2. `auth.txt` — Setup Your Authentication

This file is required for authenticated API access. Here's what it must contain:

```
url=https://chat.openai.com/backend-api/my/recent/image_gen?limit=100
authorization=Bearer <your_token_here>
cookie=__Secure-next-auth.session-token=<your_cookie_here>
referer=https://chat.openai.com/library
user_agent=Mozilla/5.0 (...)
oai_client_version=...
oai_device_id=...
oai_language=...
```

### How to Get These:
1. Log into [https://chat.openai.com/library](https://chat.openai.com/library)
2. Open Developer Tools (in Chrome, by pressing F12) → Network tab → Fetch/XHR
3. Scroll down the page to load new images in the library
4. Find any request to `image_gen` : they should look like `image_gen?limit=6&after...`. Click on one of them
5. Scroll down the **Headers** section until you find the required Headers, as in the `auth.txt`
6. Copy the headers exactly as they are; note that for the cookie key, you only need the part starting with `__Secure-next-auth.session-token=...`
7. Paste values into `auth.txt`

---

## 🚀 3. Script Usage
### 🧭 Full Flow (Recommended):

1. **run main.py**

```bash
python main.py
```
- Downloads **only new images**, creates `gallery/vN/`, `images/`, `metadata_vN.json`, `page_1.html` etc., creates/updates `gallery/index.html` with links to all pages

### 🧭 Single Steps:

1. **Download New Images**

```bash
python incremental_downloader.py
```

- Scans all existing `v*/metadata_v*.json`
- Downloads **only new images**
- Creates `gallery/vN/`, `images/`, and `metadata_vN.json`

2. **Generate HTML Gallery**

```bash
python generate_gallery_batch.py
```

- Detects the latest batch (e.g. `v3`)
- Generates `page_1.html`, `page_2.html`, etc. inside `v3`

3. **Update the Main Index Page**

```bash
python generate_index.py
```

- Scans all `gallery/v*` folders
- Creates/updates `gallery/index.html` with links to all pages

---

## 💡 Notes

- No old data is overwritten. Every batch is saved in its own versioned folder (`v1`, `v2`, etc.).
- Each gallery version is fully static and self-contained.
- The `index.html` provides a quick navigation hub.

---

## ❓ Troubleshooting

- If you get a `403` or `401`, your token or cookie may have expired. Refresh `auth.txt` by copying headers again from your browser.
- If a version is created with no new images, it will be cleaned up automatically.

---

## ✅ You're All Set

Once configured, just rerun the three scripts above any time you generate new images in ChatGPT.

Happy archiving!
