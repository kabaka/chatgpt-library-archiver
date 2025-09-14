# ChatGPT Library Archiver

This is a Python-based toolset for downloading, archiving, and browsing images generated via ChatGPT (4o Image Generator). It stores all images in a single folder and generates static HTML galleries for easy viewing.

---

## ⚠️ Note

Support for legacy versioned gallery folders (`v1`, `v2`, etc.) has been removed.
If you're upgrading from an older release that used those directories, re-download
your images with this version or run a previous release to migrate your data.

## 📦 Folder Structure

```
gallery/
├── images/
├── metadata.json
└── index.html  ← single-page gallery
auth.txt        ← credentials for API access
```

---

## ⚙️ 1. Setup Instructions

### 🔹 Requirements

- Python 3.7+
- Internet connection
- Your browser access to [chat.openai.com](https://chat.openai.com)

### 🔹 Install Dependencies

Recommended: use a virtual environment.

Option A — one command bootstrap (creates `.venv`, installs deps, runs):

```
python -m chatgpt_library_archiver bootstrap
```

Option B — manual setup:

```
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -e .[dev]
```

---

## 🛠 2. `auth.txt` — Setup Your Authentication

This file is required for authenticated API access. You can either let the tool prompt you interactively on first run, or create it manually. Here's what it must contain if creating manually:

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

The interactive setup saves `auth.txt` with permissions `600` (owner read/write only) to protect your credentials. Never commit this file and store it securely.

---

## 🚀 3. Script Usage
### 🧭 Full Flow (Recommended):

1. **Run with venv bootstrap (recommended)**

```bash
python -m chatgpt_library_archiver bootstrap
```
- Creates `.venv`, installs dependencies, and runs the full flow

2. **Run manually inside venv**

```bash
python -m chatgpt_library_archiver
```
- Downloads **only new images**, adds them to `gallery/images`, updates `gallery/metadata.json`, and regenerates `gallery/index.html`

3. **Regenerate gallery without downloading**

```bash
python -m chatgpt_library_archiver gallery
```
- Rebuilds the HTML gallery from existing files (sorts metadata and copies the
  bundled `index.html`)

Use the `-y/--yes` flag with any command to bypass confirmation prompts.

---

## 💡 Notes

- No old data is overwritten. All images are saved with unique filenames and metadata is appended.
- The gallery is fully static and self-contained.
- The `index.html` viewer is bundled with the tool and reused on each run.
- `gallery/index.html` loads `metadata.json` via JavaScript and displays all images on one page.
- Images are lazy-loaded using the Intersection Observer API so they're fetched only when they enter the viewport.
- Use the search bar in the gallery to filter by title or a date range.
 - Click any thumbnail to open a full-screen viewer overlay. Navigate with the left/right
   arrow keys, press Escape to close, or follow the **Raw file** link to view the
   underlying image. Ctrl-click (Cmd-click on macOS) a thumbnail to open the raw image
   directly in a new tab without launching the viewer.

### Disk Space
This depends entirely on how many images you have.
General estimate:
- 1 image ≈ 1.8–3.3 MB
- 100 images ≈ 180–330 MB
- 1,000 images ≈ 2–3 GB
- 5,000 images ≈ 10–12 GB

---

## ❓ Troubleshooting

- If you get a `403` or `401`, your token or cookie may have expired. Refresh `auth.txt` by copying headers again from your browser.
- During downloads, if a `401/403` occurs, the downloader now offers to re-enter credentials interactively.
- If no new images are found, the downloader simply exits without changes.

---

## 🧪 Testing and Linting

Tests cover `auth.txt` parsing, gallery generation, and a full end-to-end
flow with mocked network calls so the suite runs entirely offline.
Network requests in these tests use strict URL parsing to avoid
ambiguous domain matches.

```
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -e .[dev]
pre-commit run --all-files
pytest
```

To build a distributable package:

```
python -m build
```

---

## ✅ You're All Set

Once configured, rerun `python -m chatgpt_library_archiver` any time you generate new images in ChatGPT.

Happy archiving!
