from flask import Flask, request, jsonify, send_file, send_from_directory
from flask_cors import CORS
import yt_dlp
import os
import re
import uuid
import logging
import json
from datetime import datetime
import tempfile
import traceback
import subprocess
import urllib.parse  # Added at the top

app = Flask(__name__)
CORS(app, resources={r"/api/*": {"origins": "*"}})

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

DOWNLOADS_DIR = "downloads"
os.makedirs(DOWNLOADS_DIR, exist_ok=True)

# Supported platforms regex patterns
SUPPORTED_PLATFORMS = {
    'YouTube': r'(youtube\.com|youtu\.be)',
    'Facebook': r'(facebook\.com|fb\.watch|fb\.com)',
    'Instagram': r'(instagram\.com|instagr\.am)',
    'Twitter/X': r'(twitter\.com|x\.com)',
    'TikTok': r'(tiktok\.com|douyin\.com)',
    'Dailymotion': r'dailymotion\.com',
    'Vimeo': r'vimeo\.com',
    'Reddit': r'reddit\.com',
    'Twitch': r'twitch\.tv',
    'SoundCloud': r'soundcloud\.com',
    'Bilibili': r'bilibili\.com',
    'Rumble': r'rumble\.com',
    'LinkedIn': r'linkedin\.com',
    'Pinterest': r'pinterest\.com',
    '9GAG': r'9gag\.com',
    'Likee': r'likee\.video',
    'Kwai': r'kwai\.com'
}

# Cache FFmpeg status
_ffmpeg_available = None

# ------------------ Utility Functions ------------------

def check_ffmpeg():
    """Check if FFmpeg is installed and working (cached)"""
    global _ffmpeg_available
    
    if _ffmpeg_available is not None:
        return _ffmpeg_available
    
    try:
        result = subprocess.run(['ffmpeg', '-version'], 
                              capture_output=True, 
                              text=True, 
                              timeout=5)
        if result.returncode == 0:
            logger.info("✓ FFmpeg is installed and working")
            for line in result.stdout.split('\n'):
                if 'version' in line.lower():
                    logger.info(f"  Version: {line.strip()}")
                    break
            _ffmpeg_available = True
        else:
            logger.warning("⚠ FFmpeg check failed")
            _ffmpeg_available = False
    except FileNotFoundError:
        logger.error("✗ FFmpeg not found in PATH")
        _ffmpeg_available = False
    except Exception as e:
        logger.error(f"✗ FFmpeg check error: {str(e)}")
        _ffmpeg_available = False
    
    return _ffmpeg_available

def sanitize_filename(filename):
    """Clean filename for safe use"""
    if not filename:
        return f"video_{uuid.uuid4().hex[:8]}.mp4"
    
    filename = re.sub(r'[<>:"/\\|?*]', '', filename)
    filename = re.sub(r'\s+', ' ', filename).strip()
    filename = filename.replace('|', '-').replace('/', '-')
    return filename[:150] if filename else f"video_{uuid.uuid4().hex[:8]}.mp4"

def format_file_size(size_bytes):
    """Format file size in human readable format"""
    if not size_bytes or size_bytes == 0:
        return "0 B"
    size = float(size_bytes)
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size < 1024:
            return f"{size:.2f} {unit}"
        size /= 1024
    return f"{size:.2f} TB"

def clean_old_files(age_seconds=3600):
    """Clean old downloaded files"""
    now = datetime.now().timestamp()
    for f in os.listdir(DOWNLOADS_DIR):
        path = os.path.join(DOWNLOADS_DIR, f)
        if os.path.isfile(path) and now - os.path.getmtime(path) > age_seconds:
            try:
                os.remove(path)
                logger.info(f"Deleted old file: {f}")
            except Exception as e:
                logger.error(f"Failed to delete file {f}: {str(e)}")

# ------------------ URL Validation ------------------

def validate_and_clean_url(url):
    """Simple URL validation and cleaning"""
    if not url or not url.strip():
        return None, "URL is required", "Unknown"
    
    url = url.strip()
    
    # Add https:// if missing
    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url
    
    # Check if it's a valid URL
    try:
        result = urllib.parse.urlparse(url)
        if not all([result.scheme, result.netloc]):
            return None, "Invalid URL format", "Unknown"
    except Exception:
        return None, "Invalid URL format", "Unknown"
    
    # Get platform name
    platform = get_platform_name(url)
    
    return url, None, platform

def get_platform_name(url):
    """Get platform name from URL"""
    for platform, pattern in SUPPORTED_PLATFORMS.items():
        if re.search(pattern, url, re.IGNORECASE):
            return platform
    return "Other"

# ------------------ yt-dlp Functions ------------------

def get_video_info(url):
    """Get video information using yt-dlp"""
    try:
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'skip_download': True,
            'socket_timeout': 30,
            'retries': 3,
            'ignoreerrors': False,
            'no_color': True,
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'en-us,en;q=0.5',
                'Accept-Encoding': 'gzip,deflate',
                'Connection': 'keep-alive',
            }
        }

        logger.info(f"Getting video info for: {url}")
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
        
        if not info:
            return None, "Failed to extract video information"

        logger.info(f"Successfully extracted info for: {info.get('title', 'Unknown')}")
        
        # Get platform name
        platform = get_platform_name(url)
        
        # Get available formats
        video_formats = []
        audio_formats = []
        all_formats = []
        
        for fmt in info.get('formats', []):
            # Get filesize
            filesize = 0
            if fmt.get('filesize'):
                filesize = fmt['filesize']
            elif fmt.get('filesize_approx'):
                filesize = fmt['filesize_approx']
            
            # Get resolution
            resolution = fmt.get('resolution', '')
            if not resolution and fmt.get('height'):
                width = fmt.get('width', '?')
                resolution = f"{width}x{fmt['height']}"
            
            # Get format note
            format_note = fmt.get('format_note', '')
            if not format_note and fmt.get('height'):
                format_note = f"{fmt['height']}p"
            
            # Get codec info
            vcodec = fmt.get('vcodec', 'none')
            acodec = fmt.get('acodec', 'none')
            
            format_data = {
                'format_id': fmt.get('format_id', ''),
                'ext': fmt.get('ext', 'mp4'),
                'resolution': resolution,
                'width': fmt.get('width'),
                'height': fmt.get('height'),
                'filesize': filesize,
                'filesize_readable': format_file_size(filesize) if filesize > 0 else "Unknown",
                'vcodec': vcodec,
                'acodec': acodec,
                'format_note': format_note,
                'abr': fmt.get('abr'),
                'tbr': fmt.get('tbr'),
                'fps': fmt.get('fps'),
                'has_video': vcodec != 'none' and vcodec is not None,
                'has_audio': acodec != 'none' and acodec is not None
            }
            
            all_formats.append(format_data)
            
            # Separate video and audio formats
            if vcodec != 'none' and vcodec is not None:
                video_formats.append(format_data)
            elif acodec != 'none' and acodec is not None:
                audio_formats.append(format_data)

        # Format duration
        duration_seconds = info.get('duration', 0)
        duration_str = ""
        if duration_seconds:
            hours = int(duration_seconds // 3600)
            minutes = int((duration_seconds % 3600) // 60)
            secs = int(duration_seconds % 60)
            if hours > 0:
                duration_str = f"{hours}:{minutes:02d}:{secs:02d}"
            else:
                duration_str = f"{minutes}:{secs:02d}"
        else:
            duration_str = "00:00"

        # Add MP3 format option
        mp3_format = {
            'format_id': 'mp3',
            'ext': 'mp3',
            'resolution': 'Audio Only',
            'filesize': 0,
            'filesize_readable': 'Unknown',
            'vcodec': 'none',
            'acodec': 'mp3',
            'format_note': 'MP3 Audio',
            'abr': 192,
            'has_video': False,
            'has_audio': True,
            'quality': '192kbps',
            'description': 'Best audio quality'
        }
        
        # Add M4A format option
        m4a_format = {
            'format_id': 'm4a',
            'ext': 'm4a',
            'resolution': 'Audio Only',
            'filesize': 0,
            'filesize_readable': 'Unknown',
            'vcodec': 'none',
            'acodec': 'm4a',
            'format_note': 'M4A Audio',
            'abr': 128,
            'has_video': False,
            'has_audio': True,
            'quality': '128kbps',
            'description': 'Standard audio quality'
        }
        
        audio_formats.append(mp3_format)
        audio_formats.append(m4a_format)

        video_info = {
            'title': info.get('title', 'Unknown Title'),
            'duration': duration_str,
            'duration_seconds': duration_seconds,
            'thumbnail': info.get('thumbnail', ''),
            'uploader': info.get('uploader', info.get('channel', info.get('creator', 'Unknown'))),
            'channel': info.get('channel', info.get('creator', '')),
            'upload_date': info.get('upload_date', info.get('timestamp', '')),
            'view_count': info.get('view_count', 0),
            'like_count': info.get('like_count', 0),
            'platform': platform,
            'formats': all_formats,
            'video_formats': video_formats,
            'audio_formats': audio_formats,
            'filesize': 0
        }

        # Calculate total size
        total_size = 0
        for fmt in all_formats:
            if fmt['filesize'] > 0:
                total_size += fmt['filesize']
        
        if total_size > 0:
            video_info['filesize'] = total_size
        
        return video_info, None
        
    except yt_dlp.utils.DownloadError as e:
        logger.error(f"yt-dlp DownloadError: {str(e)}")
        return None, f"Download Error: {str(e)}"
    except yt_dlp.utils.ExtractorError as e:
        logger.error(f"yt-dlp ExtractorError: {str(e)}")
        return None, f"Platform Error: {str(e)}"
    except Exception as e:
        logger.error(f"Error getting video info: {str(e)}")
        logger.error(traceback.format_exc())
        return None, f"Failed to analyze video: {str(e)}"

# ------------------ Routes ------------------

@app.route("/api/health", methods=["GET"])
def health():
    """Health check endpoint"""
    ffmpeg_available = check_ffmpeg()
    return jsonify({
        "status": "healthy", 
        "timestamp": datetime.now().isoformat(),
        "downloads_dir": os.path.abspath(DOWNLOADS_DIR),
        "server_url": "http://127.0.0.1:5000",
        "supported_platforms": list(SUPPORTED_PLATFORMS.keys()),
        "ffmpeg_available": ffmpeg_available
    })

@app.route("/api/analyze", methods=["POST"])
def analyze():
    """Analyze video URL - SUPPORTS ALL PLATFORMS"""
    try:
        data = request.get_json(silent=True) or {}
        url = data.get("url", "").strip()

        if not url:
            return jsonify({"success": False, "error": "URL is required"}), 400

        logger.info(f"Analyze request received for URL: {url}")
        
        # Validate URL
        cleaned_url, error_msg, platform = validate_and_clean_url(url)
        if error_msg:
            logger.error(f"URL validation failed: {error_msg}")
            return jsonify({"success": False, "error": error_msg}), 400
        
        if not cleaned_url:
            logger.error("URL validation returned empty URL")
            return jsonify({"success": False, "error": "Invalid URL"}), 400

        logger.info(f"Processing URL from {platform}: {cleaned_url}")
        
        # Get video info
        video_info, error = get_video_info(cleaned_url)
        if error:
            logger.error(f"Failed to get video info: {error}")
            return jsonify({"success": False, "error": error}), 500
        
        if not video_info:
            logger.error("Video info is None")
            return jsonify({"success": False, "error": "Failed to analyze video"}), 500
        
        logger.info(f"Successfully analyzed video from {platform}: {video_info.get('title', 'Unknown')}")
        
        return jsonify({
            "success": True, 
            "video_info": video_info,
            "url": cleaned_url,
            "platform": platform
        })

    except Exception as e:
        logger.error(f"Analyze error: {str(e)}")
        logger.error(traceback.format_exc())
        return jsonify({"success": False, "error": f"Internal server error: {str(e)}"}), 500

@app.route("/api/formats", methods=["POST"])
def get_formats():
    """Get available formats for a video - ALL PLATFORMS"""
    try:
        data = request.get_json(silent=True) or {}
        url = data.get("url", "").strip()

        if not url:
            return jsonify({"success": False, "error": "URL is required"}), 400

        logger.info(f"Formats request for URL: {url}")
        
        # Validate URL
        cleaned_url, error_msg, platform = validate_and_clean_url(url)
        if error_msg:
            return jsonify({"success": False, "error": error_msg}), 400
        
        # Get video info
        video_info, error = get_video_info(cleaned_url)
        if error:
            return jsonify({"success": False, "error": error}), 500
        
        if not video_info:
            return jsonify({"success": False, "error": "Failed to get video info"}), 500
        
        # Sort formats
        video_formats = sorted(
            video_info.get('video_formats', []),
            key=lambda x: x.get('height') or x.get('tbr') or 0,
            reverse=True
        )
        
        audio_formats = sorted(
            video_info.get('audio_formats', []),
            key=lambda x: x.get('abr') or x.get('tbr') or 0,
            reverse=True
        )
        
        logger.info(f"Found {len(video_formats)} video formats and {len(audio_formats)} audio formats from {platform}")
        
        return jsonify({
            "success": True,
            "video_formats": video_formats[:15],  # Limit to 15
            "audio_formats": audio_formats[:10],  # Limit to 10
            "video_info": {
                "title": video_info.get('title', ''),
                "thumbnail": video_info.get('thumbnail', ''),
                "duration": video_info.get('duration', ''),
                "uploader": video_info.get('uploader', ''),
                "duration_seconds": video_info.get('duration_seconds', 0),
                "filesize": video_info.get('filesize', 0),
                "platform": video_info.get('platform', 'Unknown')
            },
            "url": cleaned_url,
            "platform": platform
        })

    except Exception as e:
        logger.error(f"Formats error: {str(e)}")
        logger.error(traceback.format_exc())
        return jsonify({"success": False, "error": f"Failed to fetch formats: {str(e)}"}), 500

@app.route("/api/download", methods=["POST"])
def download():
    """Download video or audio - ALL PLATFORMS"""
    try:
        clean_old_files()
        data = request.get_json(silent=True) or {}
        
        url = data.get("url", "").strip()
        format_id = data.get("format_id", "").strip()

        if not url:
            return jsonify({"success": False, "error": "URL is required"}), 400
        if not format_id:
            return jsonify({"success": False, "error": "Format ID is required"}), 400

        logger.info(f"Download request - URL: {url}, Format: {format_id}")
        
        # Validate URL
        cleaned_url, error_msg, platform = validate_and_clean_url(url)
        if error_msg:
            return jsonify({"success": False, "error": error_msg}), 400
        
        # Check if it's MP3 or M4A download
        is_mp3 = format_id == 'mp3'
        is_m4a = format_id == 'm4a'
        is_audio = is_mp3 or is_m4a
        
        # Check FFmpeg availability
        ffmpeg_available = check_ffmpeg()
        
        # Generate unique filename
        uid = uuid.uuid4().hex[:8]
        
        # Platform-specific headers
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': '*/*',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate',
            'Connection': 'keep-alive',
        }
        
        # Add referer based on platform
        if 'instagram.com' in cleaned_url:
            headers['Referer'] = 'https://www.instagram.com/'
        elif 'facebook.com' in cleaned_url:
            headers['Referer'] = 'https://www.facebook.com/'
        elif 'twitter.com' in cleaned_url or 'x.com' in cleaned_url:
            headers['Referer'] = 'https://twitter.com/'
        elif 'tiktok.com' in cleaned_url:
            headers['Referer'] = 'https://www.tiktok.com/'
        else:
            headers['Referer'] = 'https://www.google.com/'
        
        # Configure yt-dlp options
        if is_mp3:
            # For MP3 download
            ydl_opts = {
                'format': 'bestaudio/best',
                'outtmpl': os.path.join(DOWNLOADS_DIR, f'{uid}_%(title)s.%(ext)s'),
                'quiet': False,
                'no_warnings': True,
                'socket_timeout': 30,
                'retries': 5,
                'fragment_retries': 5,
                'ignoreerrors': True,
                'ratelimit': None,
                'http_headers': headers,
                'extractor_args': {
                    'youtube': {'format': 'bestaudio'},
                    'facebook': {'format': 'best'},
                    'twitter': {'format': 'best'},
                }
            }
            
            # Add postprocessor only if FFmpeg is available
            if ffmpeg_available:
                ydl_opts['postprocessors'] = [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }]
            else:
                logger.warning("FFmpeg not available, MP3 conversion may not work properly")
                
        elif is_m4a:
            # For M4A download
            ydl_opts = {
                'format': 'bestaudio/best',
                'outtmpl': os.path.join(DOWNLOADS_DIR, f'{uid}_%(title)s.%(ext)s'),
                'quiet': False,
                'no_warnings': True,
                'socket_timeout': 30,
                'retries': 5,
                'fragment_retries': 5,
                'ignoreerrors': True,
                'ratelimit': None,
                'http_headers': headers,
                'extractor_args': {
                    'youtube': {'format': 'bestaudio'},
                }
            }
            
            # Add postprocessor only if FFmpeg is available
            if ffmpeg_available:
                ydl_opts['postprocessors'] = [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'm4a',
                    'preferredquality': '128',
                }]
                
        else:
            # For video download - Smart format selection
            if format_id == 'best':
                # Try to get best quality with audio included
                format_selector = 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best'
            elif format_id == 'worst':
                format_selector = 'worstvideo[ext=mp4]+worstaudio[ext=m4a]/worst[ext=mp4]/worst'
            else:
                format_selector = format_id
            
            ydl_opts = {
                'format': format_selector,
                'outtmpl': os.path.join(DOWNLOADS_DIR, f'{uid}_%(title)s.%(ext)s'),
                'quiet': False,
                'no_warnings': True,
                'socket_timeout': 30,
                'retries': 5,
                'fragment_retries': 5,
                'ignoreerrors': True,
                'ratelimit': None,
                'http_headers': headers,
                'extractor_args': {
                    'youtube': {'format': format_selector},
                    'facebook': {'format': 'best'},
                    'twitter': {'format': 'best'},
                }
            }
            
            # Add postprocessor for merging audio+video if FFmpeg available
            if ffmpeg_available:
                ydl_opts['postprocessors'] = [{
                    'key': 'FFmpegVideoConvertor',
                    'preferedformat': 'mp4',
                }]
        
        logger.info(f"Starting download from {platform}: {cleaned_url}")
        logger.info(f"Using format selector: {ydl_opts.get('format', format_id)}")
        logger.info(f"FFmpeg available: {ffmpeg_available}")
        
        # Perform download
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(cleaned_url, download=True)
        
        # Find the downloaded file
        downloaded_files = []
        for file in os.listdir(DOWNLOADS_DIR):
            if file.startswith(uid):
                downloaded_files.append(file)
        
        if not downloaded_files:
            # Search for any file that might have been downloaded
            for file in os.listdir(DOWNLOADS_DIR):
                if os.path.getmtime(os.path.join(DOWNLOADS_DIR, file)) > datetime.now().timestamp() - 300:
                    downloaded_files.append(file)
                    break
        
        if not downloaded_files:
            raise Exception("No file was downloaded")
        
        # Get the downloaded file
        original_file = os.path.join(DOWNLOADS_DIR, downloaded_files[0])
        
        # Generate final filename
        video_title = info.get('title', 'video') if info else 'video'
        safe_title = sanitize_filename(video_title)
        
        if is_mp3:
            final_filename = f"{safe_title}.mp3"
        elif is_m4a:
            final_filename = f"{safe_title}.m4a"
        else:
            # Add resolution to filename if available
            resolution = ""
            if info and 'formats' in info:
                for fmt in info['formats']:
                    if fmt.get('format_id') == format_id and fmt.get('height'):
                        resolution = f"_{fmt['height']}p"
                        break
            
            # Check if it's mp4, if not rename to mp4
            base_name, ext = os.path.splitext(original_file)
            if ext.lower() != '.mp4':
                final_filename = f"{safe_title}{resolution}.mp4"
            else:
                final_filename = f"{safe_title}{resolution}{ext}"
        
        final_filename = sanitize_filename(final_filename)
        final_path = os.path.join(DOWNLOADS_DIR, final_filename)
        
        # Rename file
        if original_file != final_path:
            if os.path.exists(final_path):
                os.remove(final_path)
            os.rename(original_file, final_path)
        
        # Get file size
        file_size = os.path.getsize(final_path) if os.path.exists(final_path) else 0
        
        logger.info(f"Download completed: {final_filename} ({format_file_size(file_size)}) from {platform}")
        
        # Generate download URL
        base_url = request.host_url.rstrip('/')
        download_url = f"{base_url}/api/download-file/{final_filename}"
        
        return jsonify({
            "success": True,
            "filename": final_filename,
            "download_url": download_url,
            "size": format_file_size(file_size),
            "size_bytes": file_size,
            "platform": platform,
            "has_audio": True,
            "has_video": not is_audio,
            "ffmpeg_used": ffmpeg_available,
            "message": f"Download from {platform} completed successfully."
        })
            
    except yt_dlp.utils.DownloadError as e:
        logger.error(f"yt-dlp DownloadError: {str(e)}")
        return jsonify({"success": False, "error": f"Download error: {str(e)}"}), 500
    except Exception as e:
        logger.error(f"Download error: {str(e)}")
        logger.error(traceback.format_exc())
        return jsonify({"success": False, "error": f"Download failed: {str(e)}"}), 500

@app.route("/api/download-file/<filename>")
def download_file(filename):
    """Serve downloaded file"""
    try:
        # Sanitize filename for security
        safe_filename = sanitize_filename(filename)
        path = os.path.join(DOWNLOADS_DIR, safe_filename)

        if not os.path.exists(path):
            logger.error(f"File not found: {safe_filename}")
            return jsonify({"success": False, "error": "File not found or may have been deleted"}), 404

        file_size = os.path.getsize(path)
        logger.info(f"Serving file: {safe_filename} ({format_file_size(file_size)})")
        
        # Determine MIME type
        if safe_filename.endswith('.mp3'):
            mime_type = 'audio/mpeg'
        elif safe_filename.endswith('.m4a'):
            mime_type = 'audio/mp4'
        elif safe_filename.endswith('.mp4'):
            mime_type = 'video/mp4'
        else:
            mime_type = 'application/octet-stream'
        
        # Send file with proper headers
        return send_file(
            path,
            as_attachment=True,
            download_name=safe_filename,
            mimetype=mime_type
        )
        
    except Exception as e:
        logger.error(f"Download file error: {str(e)}")
        return jsonify({"success": False, "error": f"File download failed: {str(e)}"}), 500

@app.route("/api/platforms", methods=["GET"])
def platforms():
    """Get list of supported platforms"""
    return jsonify({
        "success": True,
        "platforms": list(SUPPORTED_PLATFORMS.keys()),
        "count": len(SUPPORTED_PLATFORMS)
    })

@app.route("/api/test", methods=["GET"])
def test():
    """Test endpoint"""
    ffmpeg_available = check_ffmpeg()
    return jsonify({
        "success": True,
        "message": "Backend is running",
        "timestamp": datetime.now().isoformat(),
        "supported_platforms": list(SUPPORTED_PLATFORMS.keys()),
        "ffmpeg_available": ffmpeg_available
    })

# Serve frontend
@app.route('/')
def serve_frontend():
    return send_from_directory('.', 'index.html')

@app.route('/<path:path>')
def serve_static(path):
    return send_from_directory('.', path)

# ------------------ Run ------------------

if __name__ == "__main__":
    clean_old_files()
    port = int(os.environ.get("PORT", 5000))
    
    # Check FFmpeg
    ffmpeg_available = check_ffmpeg()
    
    logger.info(f"Starting server on port {port}")
    logger.info(f"Downloads directory: {os.path.abspath(DOWNLOADS_DIR)}")
    logger.info(f"Server URL: http://127.0.0.1:{port}")
    logger.info(f"Supported platforms: {len(SUPPORTED_PLATFORMS)}")
    logger.info(f"FFmpeg available: {ffmpeg_available}")
    
    # Check if yt-dlp is installed
    try:
        logger.info(f"yt-dlp version: {yt_dlp.version.__version__}")
    except AttributeError:
        logger.info("yt-dlp version information not available")
    except Exception as e:
        logger.error(f"Error getting yt-dlp version: {str(e)}")
    
    app.run(host="0.0.0.0", port=port, debug=True, threaded=True)
