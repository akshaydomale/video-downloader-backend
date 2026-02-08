# 🎬 Universal Video Downloader Backend

A powerful Flask-based backend API for downloading videos from 15+ platforms using yt-dlp.

## ✨ Features

- **Multi-Platform Support**: Download from YouTube, Facebook, Instagram, Twitter/X, TikTok, and 12+ more platforms
- **Multiple Formats**: Support for video (MP4) and audio (MP3/M4A) formats
- **Smart Format Selection**: Choose from best, worst, or specific resolutions
- **FFmpeg Integration**: Automatic audio extraction and format conversion
- **Clean REST API**: Easy-to-use endpoints for integration
- **File Management**: Automatic cleanup of old files

## 🚀 Quick Start

### Prerequisites
- Python 3.8 or higher
- FFmpeg (recommended for audio conversion)
- Git

### Installation

1. **Clone and setup**:
```bash
# Create project directory
mkdir video-downloader-backend
cd video-downloader-backend

# Create virtual environment (optional but recommended)
python -m venv venv

# Activate virtual environment
# On Windows:
venv\Scripts\activate
# On Mac/Linux:
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
