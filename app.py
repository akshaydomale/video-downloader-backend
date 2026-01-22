from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import yt_dlp
import os
import re
import uuid
import logging
from urllib.parse import urlparse
import tempfile

app = Flask(__name__)
CORS(app)  # Enable CORS for all routes

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Supported platforms
SUPPORTED_PLATFORMS = {
    'youtube': ['youtube.com', 'youtu.be'],
    'instagram': ['instagram.com'],
    'tiktok': ['tiktok.com'],
    'facebook': ['facebook.com', 'fb.watch'],
    'twitter': ['twitter.com', 'x.com']
}

def detect_platform(url):
    """Detect which platform the URL belongs to"""
    for platform, domains in SUPPORTED_PLATFORMS.items():
        for domain in domains:
            if domain in url:
                return platform
    return None

def extract_video_info(url):
    """Extract video information using yt-dlp"""
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'extract_flat': True,
    }
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            
            # Format the response
            video_info = {
                'title': info.get('title', 'Unknown Title'),
                'duration': info.get('duration_string', '0:00'),
                'thumbnail': info.get('thumbnail', ''),
                'uploader': info.get('uploader', 'Unknown'),
                'upload_date': info.get('upload_date', ''),
                'view_count': info.get('view_count', 0),
                'like_count': info.get('like_count', 0),
                'platform': detect_platform(url),
                'formats': []
            }
            
            # Get available formats
            if 'formats' in info:
                for fmt in info['formats']:
                    if fmt.get('ext') in ['mp4', 'webm', 'm4a', 'mp3']:
                        format_info = {
                            'format_id': fmt.get('format_id', ''),
                            'ext': fmt.get('ext', ''),
                            'resolution': fmt.get('resolution', 'unknown'),
                            'filesize': fmt.get('filesize', 0),
                            'filesize_readable': format_file_size(fmt.get('filesize', 0)),
                            'vcodec': fmt.get('vcodec', 'none'),
                            'acodec': fmt.get('acodec', 'none'),
                            'format_note': fmt.get('format_note', ''),
                            'url': fmt.get('url', '')
                        }
                        video_info['formats'].append(format_info)
            
            # Calculate total size
            total_size = sum(fmt['filesize'] for fmt in video_info['formats'] if fmt['filesize'])
            video_info['total_size'] = total_size
            video_info['total_size_readable'] = format_file_size(total_size)
            
            return video_info
    except Exception as e:
        logger.error(f"Error extracting video info: {str(e)}")
        return None

def format_file_size(size_bytes):
    """Convert bytes to human readable format"""
    if size_bytes == 0:
        return "0 B"
    
    size_names = ['B', 'KB', 'MB', 'GB', 'TB']
    i = 0
    while size_bytes >= 1024 and i < len(size_names) - 1:
        size_bytes /= 1024.0
        i += 1
    
    return f"{size_bytes:.2f} {size_names[i]}"

@app.route('/api/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({
        'status': 'healthy',
        'message': 'Video Downloader API is running',
        'supported_platforms': list(SUPPORTED_PLATFORMS.keys())
    })

@app.route('/api/analyze', methods=['POST'])
def analyze_video():
    """Analyze video URL and return information"""
    try:
        data = request.json
        url = data.get('url', '').strip()
        
        if not url:
            return jsonify({'error': 'URL is required'}), 400
        
        # Validate URL format
        try:
            result = urlparse(url)
            if not all([result.scheme, result.netloc]):
                return jsonify({'error': 'Invalid URL format'}), 400
        except:
            return jsonify({'error': 'Invalid URL format'}), 400
        
        # Check if platform is supported
        platform = detect_platform(url)
        if not platform:
            return jsonify({'error': 'Unsupported platform'}), 400
        
        logger.info(f"Analyzing video from {platform}: {url}")
        
        # Extract video information
        video_info = extract_video_info(url)
        
        if not video_info:
            return jsonify({'error': 'Could not extract video information'}), 500
        
        # Add platform to response
        video_info['platform'] = platform
        
        return jsonify({
            'success': True,
            'video_info': video_info
        })
        
    except Exception as e:
        logger.error(f"Error in analyze_video: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/formats', methods=['POST'])
def get_formats():
    """Get available download formats for a video"""
    try:
        data = request.json
        url = data.get('url', '').strip()
        
        if not url:
            return jsonify({'error': 'URL is required'}), 400
        
        video_info = extract_video_info(url)
        
        if not video_info:
            return jsonify({'error': 'Could not extract formats'}), 500
        
        # Filter and organize formats
        video_formats = []
        audio_formats = []
        
        for fmt in video_info['formats']:
            # Video formats (with video codec)
            if fmt['vcodec'] != 'none':
                video_formats.append({
                    'id': fmt['format_id'],
                    'name': f"{fmt['ext'].upper()} {fmt['resolution']}",
                    'quality': fmt['resolution'],
                    'size': fmt['filesize_readable'],
                    'bitrate': 'Unknown',
                    'ext': fmt['ext'],
                    'format_note': fmt['format_note']
                })
            
            # Audio formats (audio only)
            if fmt['acodec'] != 'none' and fmt['vcodec'] == 'none':
                audio_formats.append({
                    'id': fmt['format_id'],
                    'name': f"{fmt['ext'].upper()} Audio",
                    'quality': fmt['format_note'] or 'Unknown',
                    'size': fmt['filesize_readable'],
                    'duration': video_info['duration'],
                    'ext': fmt['ext']
                })
        
        return jsonify({
            'success': True,
            'video_formats': video_formats[:5],  # Limit to 5 formats
            'audio_formats': audio_formats[:5],
            'video_info': {
                'title': video_info['title'],
                'duration': video_info['duration'],
                'thumbnail': video_info['thumbnail']
            }
        })
        
    except Exception as e:
        logger.error(f"Error in get_formats: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/download', methods=['POST'])
def download_video():
    """Download video in selected format"""
    try:
        data = request.json
        url = data.get('url', '').strip()
        format_id = data.get('format_id', '')
        
        if not url or not format_id:
            return jsonify({'error': 'URL and format_id are required'}), 400
        
        # Create temporary directory for download
        with tempfile.TemporaryDirectory() as temp_dir:
            ydl_opts = {
                'format': format_id,
                'outtmpl': os.path.join(temp_dir, '%(title)s.%(ext)s'),
                'quiet': False,
                'no_warnings': True,
            }
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                downloaded_file = ydl.prepare_filename(info)
                
                # Ensure file exists
                if not os.path.exists(downloaded_file):
                    # Try with different extension
                    base_name = os.path.splitext(downloaded_file)[0]
                    for ext in ['.mp4', '.webm', '.m4a', '.mp3']:
                        if os.path.exists(base_name + ext):
                            downloaded_file = base_name + ext
                            break
                
                if os.path.exists(downloaded_file):
                    # Return download URL (in production, you'd serve the file)
                    return jsonify({
                        'success': True,
                        'download_url': f'/api/stream/{os.path.basename(downloaded_file)}',
                        'filename': os.path.basename(downloaded_file),
                        'message': 'Ready for download'
                    })
                else:
                    return jsonify({'error': 'File not found after download'}), 500
                    
    except Exception as e:
        logger.error(f"Error in download_video: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/stream/<filename>', methods=['GET'])
def stream_file(filename):
    """Stream downloaded file"""
    try:
        # In production, implement proper file serving
        # This is a simplified version
        return jsonify({
            'message': 'File streaming endpoint',
            'note': 'Implement proper file serving logic'
        })
    except Exception as e:
        logger.error(f"Error in stream_file: {str(e)}")
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)