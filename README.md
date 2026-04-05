# VaultDL — Self-Hosted Video Downloader

A self-hosted web app to download videos and audio from YouTube and 1000+ other sites. Paste a URL, pick a format, and the file streams directly to your browser. **Nothing is stored permanently on the server.**

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python · FastAPI · yt-dlp |
| Frontend | React 18 · Vite · Tailwind CSS |
| Merger | FFmpeg (required for 720p+) |

---

## Prerequisites

| Tool | Min Version | Notes |
|---|---|---|
| Python | 3.10+ | [python.org](https://www.python.org/downloads/) |
| Node.js | 18+ | [nodejs.org](https://nodejs.org/) — also fixes yt-dlp JS runtime warning |
| FFmpeg | Any recent | See [FFmpeg Setup](#ffmpeg-setup) below |
| pip | Latest | Upgrade with `pip install -U pip` |

---

## Installation

### 1 · Clone the project

```bash
git clone https://github.com/Aditya-567/POC---VaultDL.git
cd POC---VaultDL
```

### 2 · Backend

```bash
cd backend
pip install fastapi uvicorn yt-dlp pydantic
```

### 3 · Frontend

```bash
cd frontend
npm install
```

---

## FFmpeg Setup

FFmpeg is **required** to merge high-quality video + audio streams (720p and above). YouTube delivers these as separate files — FFmpeg combines them.

### Windows (winget — recommended)

```powershell
winget install --id Gyan.FFmpeg -e --source winget
```

> Open a **new terminal** after installing so PATH updates take effect.

### Windows (manual)

1. Download from [gyan.dev/ffmpeg/builds](https://www.gyan.dev/ffmpeg/builds/)
2. Extract to a permanent folder e.g. `C:\ffmpeg\`
3. Add `C:\ffmpeg\bin` to your system PATH
4. Verify: `ffmpeg -version`

### Linux / macOS

```bash
# Ubuntu/Debian
sudo apt install ffmpeg

# macOS
brew install ffmpeg
```

---

## Running the Application

> Both servers must run at the same time in **separate terminals**.

### Terminal 1 — Backend

```bash
cd backend
python -m uvicorn main:app --reload --port 8000
```

- API: `http://localhost:8000`
- Swagger docs: `http://localhost:8000/docs`

### Terminal 2 — Frontend

```bash
cd frontend
npm run dev
```

- App: `http://localhost:5173`
- Documentation: `http://localhost:5173/docs.html`

---

## Build Portable EXE (No End-User Installs)

To produce a self-contained `VaultDL.exe` that bundles `aria2c` and `ffmpeg`:

1. Run `build.bat` from the project root.
2. The build now automatically downloads Windows binaries for `aria2c` and `ffmpeg` into `third_party/`.
3. PyInstaller packages those binaries into the EXE runtime.

Output: `dist/VaultDL.exe`

Your end users only need to download and run the EXE.

---

## How It Works

1. Paste a YouTube (or other supported site) URL
2. Click **Analyze Formats** — backend fetches available formats, no download yet
3. Select your format from the dropdown (resolution, type, file size shown)
4. Click **Download Now** — file streams directly to your browser's Downloads folder

---

## Project Structure

```
ytdownload/
├── backend/
│   ├── main.py              # FastAPI app — all API logic
│   └── downloads/           # Temp dir, auto-deleted after each stream
├── frontend/
│   ├── public/
│   │   └── docs.html        # Documentation page
│   ├── src/
│   │   ├── App.jsx          # Main React component
│   │   ├── main.jsx         # React entry point
│   │   └── index.css        # Global Tailwind styles
│   ├── package.json
│   └── vite.config.js
├── .gitignore
└── README.md
```

---

## API Reference

### `POST /api/info`

Fetches video metadata and available formats. No download happens.

**Request:**
```json
{ "url": "https://www.youtube.com/watch?v=..." }
```

**Response:**
```json
{
  "title": "Video Title",
  "thumbnail": "https://...",
  "duration": "3:45",
  "formats": [
    {
      "format_id": "bestaudio_mp3",
      "ext": "mp3",
      "resolution": "Audio",
      "type": "Audio Only (MP3 Extraction)",
      "filesize_mb": "Auto"
    }
  ]
}
```

---

### `POST /api/download`

Downloads and streams the file directly to the browser. Temp files are deleted after streaming.

**Request:**
```json
{
  "url": "https://www.youtube.com/watch?v=...",
  "format_id": "137+bestaudio"
}
```

**Response:** Binary file stream with `Content-Disposition: attachment; filename="..."`.

#### Special format IDs

| format_id | Behaviour |
|---|---|
| `bestaudio_mp3` | Best audio → converted to 192kbps MP3 via FFmpeg |
| `{id}+bestaudio` | Video stream merged with best audio via FFmpeg |
| `18` | Pre-merged 360p MP4 — no FFmpeg needed |

---

## Common Errors & Fixes

| Error | Cause | Fix |
|---|---|---|
| `Could not import module "main"` | Uvicorn run from wrong directory | `cd backend` first |
| `ffmpeg is not installed` | FFmpeg not in PATH | Install FFmpeg; open a new terminal |
| `No supported JavaScript runtime` | Node.js not installed | Install Node.js |
| `Failed to fetch info` | Invalid/unsupported URL | Verify the URL; check yt-dlp supported sites |
| `Download produced no output file` | yt-dlp extraction failed | Run `pip install -U yt-dlp` |
| CORS error in browser | Frontend URL not in `allow_origins` | Add your URL to `allow_origins` in `main.py` |
| `Connection refused` on port 8000 | Backend not running | Start uvicorn |
| `HTTP 429 Too Many Requests` | YouTube rate limiting | Wait a few minutes and retry |

---

## Keeping yt-dlp Updated

YouTube changes its internals frequently. If downloads stop working, update yt-dlp first:

```bash
pip install -U yt-dlp
```

---

## Deploying Online

1. Deploy backend to a VPS (DigitalOcean, Hetzner, Railway, Render)
2. Install FFmpeg on the server: `sudo apt install ffmpeg`
3. In `frontend/src/App.jsx` change `API_BASE` to your server's public URL
4. In `backend/main.py` update `allow_origins` to your frontend's domain
5. Build frontend: `npm run build` → deploy `dist/` to Vercel/Netlify or serve via Nginx

> **Note:** YouTube blocks many datacenter IPs. If downloads fail on your VPS but work locally, the server IP may be banned by YouTube.
