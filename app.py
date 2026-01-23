from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import yt_dlp
import os
import re
import uuid
import logging
from urllib.parse import urlparse
from datetime import datetime

app = Flask(__name__)
CORS(app)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DOWNLOADS_DIR = "downloads"
os.makedirs(DOWNLOADS_DIR, exist_ok=True)

SUPPORTED_PLATFORMS = {
    'youtube': ['youtube.com', 'youtu.be'],
    'instagram': ['instagram.com'],
    'tiktok': ['tiktok.com'],
    'facebook': ['facebook.com', 'fb.watch'],
    'twitter': ['twitter.com', 'x.com']
}

# ------------------ Utility ------------------

def detect_platform(url):
    for platform, domains in SUPPORTED_PLATFORMS.items():
        if any(domain in url for domain in domains):
            return platform
    return None


def format_file_size(size_bytes):
    if not size_bytes:
        return "0 B"
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size_bytes < 1024:
            return f"{size_bytes:.2f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.2f} TB"


def sanitize_filename(filename):
    filename = re.sub(r'[<>:"/\\|?*]', '', filename)
    filename = re.sub(r'\s+', ' ', filename).strip()
    return filename[:150]


def clean_old_files(age_seconds=3600):
    now = datetime.now().timestamp()
    for f in os.listdir(DOWNLOADS_DIR):
        path = os.path.join(DOWNLOADS_DIR, f)
        if os.path.isfile(path) and now - os.path.getmtime(path) > age_seconds:
            os.remove(path)
            logger.info(f"Deleted old file: {f}")

# ------------------ yt-dlp ------------------

def extract_video_info(url):
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'skip_download': True
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)

        formats = []
        for fmt in info.get('formats', []):
            filesize = fmt.get('filesize') or fmt.get('filesize_approx') or 0

            formats.append({
                'format_id': fmt.get('format_id'),
                'ext': fmt.get('ext'),
                'resolution': fmt.get('resolution') or f"{fmt.get('height','')}p",
                'filesize': filesize,
                'filesize_readable': format_file_size(filesize),
                'vcodec': fmt.get('vcodec', 'none'),
                'acodec': fmt.get('acodec', 'none'),
                'format_note': fmt.get('format_note', '')
            })

        return {
            'title': info.get('title', 'Unknown'),
            'duration': info.get('duration_string') or str(info.get('duration', '')),
            'thumbnail': info.get('thumbnail', ''),
            'formats': formats
        }

    except Exception as e:
        logger.error(f"Extract error: {e}")
        return None

# ------------------ Routes ------------------

@app.route("/api/health")
def health():
    return jsonify({"status": "healthy"})


@app.route("/api/analyze", methods=["POST"])
def analyze():
    data = request.get_json(silent=True) or {}
    url = data.get("url", "").strip()

    if not url:
        return jsonify({"error": "URL required"}), 400

    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        return jsonify({"error": "Invalid URL"}), 400

    if not detect_platform(url):
        return jsonify({"error": "Unsupported platform"}), 400

    info = extract_video_info(url)
    if not info:
        return jsonify({"error": "Failed to analyze"}), 500

    return jsonify({"success": True, "video_info": info})


@app.route("/api/formats", methods=["POST"])
def formats():
    data = request.get_json(silent=True) or {}
    url = data.get("url", "").strip()

    info = extract_video_info(url)
    if not info:
        return jsonify({"error": "Failed to fetch formats"}), 500

    video, audio = [], []

    for f in info["formats"]:
        if f["vcodec"] != "none":
            video.append(f)
        elif f["acodec"] != "none":
            audio.append(f)

    return jsonify({
        "success": True,
        "video_formats": video[:10],
        "audio_formats": audio[:10],
        "video_info": {
            "title": info["title"],
            "thumbnail": info["thumbnail"]
        }
    })


@app.route("/api/download", methods=["POST"])
def download():
    clean_old_files()
    data = request.get_json(silent=True) or {}

    url = data.get("url")
    format_id = data.get("format_id")

    if not url or not format_id:
        return jsonify({"error": "url & format_id required"}), 400

    uid = str(uuid.uuid4())[:8]
    outtmpl = os.path.join(DOWNLOADS_DIR, f"{uid}_%(title)s.%(ext)s")

    ydl_opts = {
        'format': format_id,
        'outtmpl': outtmpl,
        'quiet': True,
        'no_warnings': True
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            file_path = ydl.prepare_filename(info)

        filename = sanitize_filename(os.path.basename(file_path))
        final_path = os.path.join(DOWNLOADS_DIR, filename)
        os.rename(file_path, final_path)

        return jsonify({
            "success": True,
            "filename": filename,
            "download_url": f"/api/download-file/{filename}",
            "size": format_file_size(os.path.getsize(final_path))
        })

    except Exception as e:
        logger.error(f"Download error: {e}")
        return jsonify({"error": "Download failed"}), 500


@app.route("/api/download-file/<filename>")
def download_file(filename):
    filename = sanitize_filename(filename)
    path = os.path.join(DOWNLOADS_DIR, filename)

    if not os.path.exists(path):
        return jsonify({"error": "File not found"}), 404

    return send_file(path, as_attachment=True, download_name=filename)


# ------------------ Run ------------------

if __name__ == "__main__":
    clean_old_files()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
