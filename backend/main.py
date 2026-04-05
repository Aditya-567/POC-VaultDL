# 1. Install dependencies: pip install fastapi uvicorn yt-dlp pydantic
# 2. Make sure aria2 is installed: choco install aria2 -y
# 3. Run the server: uvicorn main:app --reload --port 8000

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, HttpUrl
import yt_dlp
import os
import sys
import shutil
import tempfile
import asyncio
import re
import uuid

# ==========================================
# --- 1. SETUP & CONFIGURATION ---
# ==========================================

def _resource_base_dir() -> str:
    if getattr(sys, 'frozen', False):
        return getattr(sys, '_MEIPASS', os.path.dirname(sys.executable))
    return os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))


def _first_existing(*candidates: str | None) -> str:
    for candidate in candidates:
        if candidate and os.path.exists(candidate):
            return candidate
    return ''

# Locate FFmpeg
_FFMPEG_FALLBACK = os.path.join(
    os.environ.get("LOCALAPPDATA", ""),
    "Microsoft", "WinGet", "Packages",
    "Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe",
    "ffmpeg-8.0.1-full_build", "bin"
)
_BUNDLED_TOOLS_DIR = os.path.join(_resource_base_dir(), "third_party")
_BUNDLED_FFMPEG_BIN = os.path.join(_BUNDLED_TOOLS_DIR, "ffmpeg", "bin")
_SYSTEM_FFMPEG = shutil.which("ffmpeg")
FFMPEG_LOCATION = _first_existing(
    _BUNDLED_FFMPEG_BIN,
    os.path.dirname(_SYSTEM_FFMPEG) if _SYSTEM_FFMPEG else None,
    _FFMPEG_FALLBACK,
)

_ARIA2_FALLBACK = os.path.join(os.environ.get("LOCALAPPDATA", ""), "aria2", "aria2c.exe")
ARIA2_LOCATION = _first_existing(
    os.path.join(_BUNDLED_TOOLS_DIR, "aria2", "aria2c.exe"),
    shutil.which("aria2c"),
    _ARIA2_FALLBACK,
)

app = FastAPI(title="Ultimate Download API (YT + Torrents)")

# Security: Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"], # Add your frontend ports
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition", "Content-Length"],
)

# ==========================================
# --- 2. WEBSOCKET MANAGER (For Progress) ---
# ==========================================

class ConnectionManager:
    def __init__(self):
        self.active_connections: dict[str, WebSocket] = {}

    async def connect(self, websocket: WebSocket, client_id: str):
        await websocket.accept()
        self.active_connections[client_id] = websocket

    def disconnect(self, client_id: str):
        if client_id in self.active_connections:
            del self.active_connections[client_id]

    async def send_progress(self, client_id: str, message: dict):
        if client_id in self.active_connections:
            await self.active_connections[client_id].send_json(message)

manager = ConnectionManager()

# Single-use file store: token -> {file_path, temp_dir, filename}
_pending_downloads: dict = {}


# ==========================================
# --- 3. REQUEST MODELS ---
# ==========================================

class InfoRequest(BaseModel):
    url: HttpUrl

class DownloadRequest(BaseModel):
    url: HttpUrl
    format_id: str 

class MagnetRequest(BaseModel):
    magnet_link: str
    client_id: str  # Ties the HTTP request to the WebSocket connection


# ==========================================
# --- 4. YT-DLP ENDPOINTS (Untouched) ---
# ==========================================

@app.post("/api/info")
async def get_video_info(request: InfoRequest):
    ydl_opts = {'noplaylist': True}
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(str(request.url), download=False)
            
            def resolution_label(f):
                """Return a friendly resolution label like 720p, 1080p, 2K, 4K."""
                height = f.get('height')
                if not height:
                    return f.get('resolution') or "Audio"
                if height >= 2160:
                    return "4K (2160p)"
                if height >= 1440:
                    return "2K (1440p)"
                if height >= 1080:
                    return "1080p (Full HD)"
                if height >= 720:
                    return "720p (HD)"
                if height >= 480:
                    return "480p (SD)"
                if height >= 360:
                    return "360p"
                return f"{height}p"

            available_formats = []
            for f in info.get('formats', []):
                # Skip formats without a real URL (e.g. SABR-only android_vr streams)
                if not f.get('url'):
                    continue
                if f.get('vcodec') != 'none' or f.get('acodec') != 'none':
                    has_video = f.get('vcodec') != 'none'
                    has_audio = f.get('acodec') != 'none'
                    target_format_id = f.get("format_id")
                    
                    if has_video and has_audio:
                        type_label = "Video + Audio (Pre-merged)"
                    elif has_video:
                        type_label = "Video + Audio (High Quality Merge)"
                        target_format_id = f"{target_format_id}+bestaudio"
                    else:
                        type_label = "Audio Only"

                    available_formats.append({
                        "format_id": target_format_id,
                        "ext": f.get("ext"),
                        "resolution": resolution_label(f),
                        "note": f.get("format_note") or "",
                        "type": type_label,
                        "filesize_mb": round(f.get("filesize", 0) / (1024 * 1024), 2) if f.get("filesize") else "Unknown"
                    })
                    
            available_formats.reverse()
            available_formats.insert(0, {
                "format_id": "bestaudio_mp3", "ext": "mp3", "resolution": "Audio",
                "note": "Highest Quality", "type": "Audio Only (MP3 Extraction)", "filesize_mb": "Auto"
            })

            return {
                "title": info.get("title"), "thumbnail": info.get("thumbnail"),
                "duration": info.get("duration_string"), "formats": available_formats
            }
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to fetch info: {str(e)}")


@app.post("/api/download")
async def trigger_download(request: DownloadRequest):
    url_str = str(request.url)
    format_id = request.format_id
    temp_dir = tempfile.mkdtemp()

    if (format_id == "bestaudio_mp3" or "+" in format_id) and not os.path.exists(os.path.join(FFMPEG_LOCATION, "ffmpeg.exe")):
        raise HTTPException(status_code=500, detail="FFmpeg binary not found. Rebuild app with bundled ffmpeg.")

    ydl_opts = {
        'outtmpl': os.path.join(temp_dir, '%(title)s.%(ext)s'),
        'restrictfilenames': True, 'noplaylist': True, 'ffmpeg_location': FFMPEG_LOCATION,
    }

    if format_id == "bestaudio_mp3":
        ydl_opts['format'] = 'bestaudio/best'
        ydl_opts['postprocessors'] = [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '192'}]
    else:
        # Append fallbacks so yt-dlp can recover if the exact format is unavailable
        ydl_opts['format'] = f"{format_id}/bestvideo+bestaudio/best"

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url_str])
    except Exception as e:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise HTTPException(status_code=400, detail=f"Download failed: {str(e)}")

    files = os.listdir(temp_dir)
    if not files:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise HTTPException(status_code=500, detail="Download produced no output file.")

    file_path = os.path.join(temp_dir, files[0])
    filename = files[0]

    def stream_and_cleanup():
        try:
            with open(file_path, 'rb') as f:
                while chunk := f.read(1024 * 1024):  
                    yield chunk
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    return StreamingResponse(
        stream_and_cleanup(), media_type='application/octet-stream',
        headers={'Content-Disposition': f'attachment; filename="{filename}"'}
    )


# ==========================================
# --- 5. ARIA2 TORRENT & WEBSOCKET ENDPOINTS ---
# ==========================================

@app.websocket("/api/ws/progress/{client_id}")
async def websocket_endpoint(websocket: WebSocket, client_id: str):
    """React connects here to listen for aria2 progress."""
    await manager.connect(websocket, client_id)
    try:
        while True:
            await websocket.receive_text() # Keep connection alive
    except WebSocketDisconnect:
        manager.disconnect(client_id)


@app.post("/api/download-magnet")
async def download_magnet_via_aria2(request: MagnetRequest):
    """Downloads the torrent via aria2, sends progress over WS, then streams the file."""
    magnet = request.magnet_link
    client_id = request.client_id

    if not os.path.exists(ARIA2_LOCATION):
        raise HTTPException(status_code=500, detail="aria2c binary not found. Rebuild app with bundled aria2.")
    
    if not magnet.startswith("magnet:"):
        raise HTTPException(status_code=400, detail="Invalid magnet link.")

    temp_dir = tempfile.mkdtemp()

    # Public trackers for faster peer discovery on magnet links
    trackers = ",".join([
        "udp://tracker.opentrackr.org:1337/announce",
        "udp://open.tracker.cl:1337/announce",
        "udp://tracker.openbittorrent.com:6969/announce",
        "udp://open.stealth.si:80/announce",
        "udp://tracker.torrent.eu.org:451/announce",
        "udp://exodus.desync.com:6969/announce",
        "udp://tracker.tiny-vps.com:6969/announce",
        "udp://tracker.moeking.me:6969/announce",
        "udp://explodie.org:6969/announce",
        "udp://tracker.theoks.net:6969/announce",
        "https://tracker.tamersunion.org:443/announce",
        "udp://tracker1.bt.moack.co.kr:80/announce",
        "udp://tracker.bittor.pw:1337/announce",
        "udp://tracker.dump.cl:6969/announce",
        "udp://tracker-udp.gbitt.info:80/announce",
        "udp://opentracker.io:6969/announce",
        "udp://new-line.net:6969/announce",
        "udp://tracker.tryhackx.org:6969/announce",
        "udp://carr.codes:6969/announce",
        "udp://ttk2.nbarat.com:6969/announce",
    ])

    command = [
        ARIA2_LOCATION,
        "--dir", temp_dir,
        "--seed-time=0",
        "--summary-interval=1",
        "--max-connection-per-server=16",
        "--split=32",
        "--min-split-size=1M",
        "--bt-max-peers=300",
        "--bt-request-peer-speed-limit=0",
        "--bt-tracker-connect-timeout=10",
        "--bt-tracker-timeout=10",
        "--enable-dht=true",
        "--enable-dht6=true",
        "--enable-peer-exchange=true",
        "--bt-enable-lpd=true",
        "--follow-torrent=mem",
        "--file-allocation=none",
        "--check-integrity=false",
        f"--bt-tracker={trackers}",
        "--dht-listen-port=6881-6999",
        "--listen-port=6881-6999",
        "--max-overall-download-limit=0",
        "--max-download-limit=0",
        "--max-concurrent-downloads=16",
        "--optimize-concurrent-downloads=true",
        "--piece-length=1M",
        "--disk-cache=64M",
        "--socket-recv-buffer-size=16777216",
        "--bt-detach-seed-only=true",
        "--bt-save-metadata=false",
        "--bt-load-saved-metadata=false",
        "--bt-remove-unselected-file=true",
        "--allow-overwrite=true",
        "--auto-file-renaming=false",
        magnet
    ]
    
    # Immediately tell the frontend we received the request
    await manager.send_progress(client_id, {"status": "connecting", "progress": 0, "message": "Starting aria2, connecting to peers..."})

    loop = asyncio.get_event_loop()

    def _run_aria2_blocking():
        """Runs aria2c synchronously in a thread, posting progress back to the event loop."""
        import subprocess
        asyncio.run_coroutine_threadsafe(
            manager.send_progress(client_id, {"status": "connecting", "progress": 0, "message": "aria2c launched, waiting for peers..."}),
            loop
        )
        proc = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            encoding='utf-8',
            errors='replace',
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        def _to_mbps(value_str, unit_str):
            """Convert aria2 speed like '5.2MiB' to Mbps string."""
            try:
                val = float(value_str)
                multipliers = {'GiB': 8589.934592, 'MiB': 8.388608, 'KiB': 0.008192, 'B': 0.000008}
                mbps = val * multipliers.get(unit_str, 0)
                return f"{mbps:.2f} Mbps" if mbps >= 1 else f"{mbps * 1000:.0f} Kbps"
            except (ValueError, TypeError):
                return ''

        for line in proc.stdout:
            size_match = re.search(r'([\d.]+(?:GiB|MiB|KiB|B))\/([\d.]+(?:GiB|MiB|KiB|B))\((\d+)%\)', line)
            speed_match = re.search(r'DL:([\d.]+)(GiB|MiB|KiB|B)\/s', line)
            seed_match = re.search(r'SD:(\d+)', line)
            peer_match = re.search(r'CN:(\d+)', line)
            pct_match = re.search(r'\((\d+)%\)', line)
            if size_match:
                downloaded = size_match.group(1)
                total = size_match.group(2)
                percentage = int(size_match.group(3))
                speed_mbps = _to_mbps(speed_match.group(1), speed_match.group(2)) if speed_match else ''
                seeds = int(seed_match.group(1)) if seed_match else 0
                peers = int(peer_match.group(1)) if peer_match else 0
                asyncio.run_coroutine_threadsafe(
                    manager.send_progress(client_id, {
                        "status": "downloading",
                        "progress": percentage,
                        "downloaded": downloaded,
                        "total": total,
                        "speed": speed_mbps,
                        "seeds": seeds,
                        "peers": peers,
                        "message": f"Downloading... {percentage}%"
                    }),
                    loop
                )
            elif pct_match:
                percentage = int(pct_match.group(1))
                asyncio.run_coroutine_threadsafe(
                    manager.send_progress(client_id, {"status": "downloading", "progress": percentage, "message": f"Downloading... {percentage}%"}),
                    loop
                )
            elif 'DL:' in line or 'ETA:' in line:
                # Still active but no percentage yet (e.g. metadata phase)
                asyncio.run_coroutine_threadsafe(
                    manager.send_progress(client_id, {"status": "connecting", "progress": 0, "message": line.strip()}),
                    loop
                )
        proc.wait()
        if proc.returncode != 0:
            stderr_msg = proc.stderr.read().strip()
            raise RuntimeError(f"aria2c exited with code {proc.returncode}. stderr: {stderr_msg}")

    try:
        await loop.run_in_executor(None, _run_aria2_blocking)
    except Exception as e:
        shutil.rmtree(temp_dir, ignore_errors=True)
        import traceback; traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Aria2 failed: {str(e)}")

    # Tell the frontend the download finished and we are preparing the file stream
    await manager.send_progress(client_id, {"status": "processing", "progress": 100})

    # 4. Find the largest video file in the downloaded torrent folder
    downloaded_file = None
    largest_size = 0
    for root, dirs, files in os.walk(temp_dir):
        for file in files:
            if file.endswith(('.mp4', '.mkv', '.avi', '.webm')):
                filepath = os.path.join(root, file)
                size = os.path.getsize(filepath)
                if size > largest_size:
                    largest_size = size
                    downloaded_file = filepath

    if not downloaded_file:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise HTTPException(status_code=404, detail="No video file found in the torrent.")

    filename = os.path.basename(downloaded_file)
    token = str(uuid.uuid4())
    _pending_downloads[token] = {"file_path": downloaded_file, "temp_dir": temp_dir, "filename": filename}

    # 5. Tell frontend the file is ready — it will open the GET endpoint as a native browser download
    await manager.send_progress(client_id, {"status": "ready", "token": token, "filename": filename})
    return {"status": "ok"}


@app.get("/api/file/{token}")
async def serve_pending_file(token: str):
    """Single-use: serves the prepared file directly to the browser, then deletes the temp folder."""
    entry = _pending_downloads.pop(token, None)
    if entry is None:
        raise HTTPException(status_code=404, detail="File not found or already downloaded.")

    file_path: str = entry["file_path"]
    temp_dir: str = entry["temp_dir"]
    filename: str = entry["filename"]

    if not os.path.exists(file_path):
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise HTTPException(status_code=404, detail="File no longer exists on disk.")

    file_size = os.path.getsize(file_path)

    def stream_and_cleanup():
        try:
            with open(file_path, 'rb') as f:
                while chunk := f.read(1024 * 1024):
                    yield chunk
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    media_type = "video/mp4" if filename.endswith(".mp4") else "application/octet-stream"

    return StreamingResponse(
        stream_and_cleanup(),
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Length": str(file_size),
        }
    )

# ==========================================
# --- 6. SERVE DESKTOP UI ---
# ==========================================
if getattr(sys, 'frozen', False):
    # Running as a PyInstaller .exe — files are in sys._MEIPASS
    frontend_path = os.path.join(sys._MEIPASS, 'frontend', 'dist')
else:
    frontend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "frontend", "dist"))

if os.path.exists(frontend_path):
    app.mount("/", StaticFiles(directory=frontend_path, html=True), name="frontend")