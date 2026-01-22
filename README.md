# Smart Video Downloader - Backend API

Python Flask backend for video downloading application.

## Features
- Extract video info from multiple platforms
- Get available formats
- Download videos in different qualities
- REST API endpoints

## API Endpoints
- `GET /api/health` - Health check
- `POST /api/analyze` - Analyze video URL
- `POST /api/formats` - Get available formats
- `POST /api/download` - Download video

## Setup
1. Clone this repository
2. Install dependencies: `pip install -r requirements.txt`
3. Run locally: `python app.py`
4. The server will run on `http://localhost:5000`

## Environment Variables
- `PORT` - Server port (default: 5000)

## Supported Platforms
- YouTube
- Instagram
- TikTok
- Facebook
- Twitter/X

## Deployment
Deployed on Render: https://video-downloader-backend.onrender.com

## Frontend
Frontend is hosted separately on GitHub Pages:
[Frontend Repository](https://github.com/yourusername/video-downloader-frontend)
