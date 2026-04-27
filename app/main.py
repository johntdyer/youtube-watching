"""
youtube-watching
"""

import os
import sys
import logging
from http.cookiejar import MozillaCookieJar
import json
import re
import requests
from flask import Flask, request
from flask_restful import Resource, Api

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
api = Api(app)


@app.before_request
def log_request():
    logger.info(f"Incoming {request.method} request to {request.path} from {request.remote_addr}")


def yt_history(cookie):
    """
    get latest video from youtube history excluding reel shelf (shorts)
    Returns tuple of (data, status_code) for proper HTTP response handling
    """

    # COOKIES
    cookie_jar = MozillaCookieJar(cookie)
    print("starting")
    try:
        cookie_jar.load(ignore_discard=True, ignore_expires=True)

    except OSError as notfound_error:
        print(f"WARNING: {cookie} not found\nDEBUG: {notfound_error}")
        sys.exit()

    # SESSION
    session = requests.Session()
    session.headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-Dest": "document",
    }
    session.cookies = cookie_jar
    logger.debug(f"Loaded {len(cookie_jar)} cookies for YouTube request")

    # Establish session first
    session.get("https://www.youtube.com/", timeout=10)

    # RESPONSE
    response = session.get("https://www.youtube.com/feed/history")
    cookie_jar.save(ignore_discard=True, ignore_expires=True)
    html = response.text
    logger.info(f"YouTube response status: {response.status_code}, length: {len(html)}")
    if response.status_code != 200:
        logger.error(f"Failed to fetch YouTube history: {response.status_code}")
        return {"error": f"Failed to fetch YouTube history: HTTP {response.status_code}"}, 502

    # Debug: save first 2000 chars to check what we're getting
    if "ytInitialData" not in html:
        logger.debug(f"Response snippet (first 1000 chars): {html[:1000]}")

    # JSON
    try:
        regex = r"var ytInitialData = (.*?);<\/script>"
        match = re.search(regex, html)
        if not match:
            logger.error("Could not find ytInitialData in response. Cookies may be invalid or expired.")
            logger.debug(f"Response length: {len(html)}, Response snippet: {html[:500]}")
            return {"error": "Cookie authentication failed - upstream cookies are invalid or expired"}, 401

        data = json.loads(match.group(1))
        path = data["contents"]["twoColumnBrowseResultsRenderer"]\
            ["tabs"][0]["tabRenderer"]["content"]["sectionListRenderer"]\
            ["contents"][0]["itemSectionRenderer"]["contents"]

    except (AttributeError, KeyError, json.JSONDecodeError) as data_error:
        logger.error(f"Failed to parse YouTube data: {data_error}")
        logger.debug(f"Response snippet: {html[:1000]}")
        return {"error": "Cookie authentication failed - could not parse YouTube response"}, 401

    # THUMBNAIL
    def thumbnail(fid):
        """ return max resolution """

        url = f"https://img.youtube.com/vi/{fid}"
        maxres = f"{url}/maxresdefault.jpg"
        default = f"{url}/0.jpg"

        if requests.get(maxres, timeout=3).status_code == 200:
            return maxres

        return default

    # OUTPUT - Handle both old videoRenderer and new lockupViewModel formats
    video_item = None
    for i, item in enumerate(path):
        if "messageRenderer" in item:
            msg_text = "Unknown message"
            text_obj = item["messageRenderer"].get("text", {})
            if "runs" in text_obj and len(text_obj["runs"]) > 0:
                msg_text = text_obj["runs"][0].get("text", "Unknown message")
            elif "simpleText" in text_obj:
                msg_text = text_obj["simpleText"]

            logger.warning(f"YouTube returned message instead of video: {msg_text}")
            if "button" in item["messageRenderer"]:
                button_text = item["messageRenderer"]["button"].get("buttonRenderer", {}).get("text", {}).get("runs", [])
                if button_text and "sign in" in button_text[0].get("text", "").lower():
                    logger.error("YouTube requested sign-in - cookies have expired")
                    return {"error": "Cookie authentication failed - YouTube requires sign-in"}, 401
            continue
        elif "videoRenderer" in item:
            key = item["videoRenderer"]
            return {
                "channel": key["longBylineText"]["runs"][0]["text"],
                "title": key["title"]["runs"][0]["text"],
                "video_id": key["videoId"],
                "duration_string": key["lengthText"]["simpleText"],
                "thumbnail": thumbnail(key["videoId"]),
                "original_url": f"https://www.youtube.com/watch?v={key['videoId']}",
            }
        elif "lockupViewModel" in item:
            video_item = item["lockupViewModel"]
            break

    if video_item:
        video_id = video_item.get("contentId", "")
        metadata = video_item.get("metadata", {}).get("lockupMetadataViewModel", {})
        title = metadata.get("title", {}).get("content", "Unknown")

        channel = "Unknown"
        content_meta = metadata.get("metadata", {}).get("contentMetadataViewModel", {})
        if "metadataRows" in content_meta and len(content_meta["metadataRows"]) > 0:
            parts = content_meta["metadataRows"][0].get("metadataParts", [])
            if len(parts) > 0:
                channel = parts[0].get("text", {}).get("content", "Unknown")

        return {
            "channel": channel,
            "title": title,
            "video_id": video_id,
            "thumbnail": thumbnail(video_id),
            "original_url": f"https://www.youtube.com/watch?v={video_id}",
        }

    return {"error": "No video found in history"}


class RestApi(Resource):
    """
    https://flask-restful.readthedocs.io/en/latest/quickstart.html
    """

    def get(self):
        """
        on GET request run yt_history
        """
        cookie_path = os.environ.get('COOKIE', '/Users/jdyer/development/youtube-watching/youtube-watching.txt')
        return yt_history(cookie_path)


api.add_resource(RestApi, "/")


def validate_cookie_file(cookie_path):
    """Validate cookie file exists and is readable."""
    logger.info(f"Validating cookie file: {cookie_path}")

    if not os.path.exists(cookie_path):
        logger.error(f"Cookie file not found: {cookie_path}")
        sys.exit(1)

    try:
        cookie_jar = MozillaCookieJar(cookie_path)
        cookie_jar.load(ignore_discard=True, ignore_expires=True)
        logger.info(f"Cookie file validated successfully, loaded {len(cookie_jar)} cookies")
    except Exception as e:
        logger.error(f"Invalid cookie file {cookie_path}: {e}")
        sys.exit(1)


if __name__ == "__main__":
    from waitress import serve
    cookie_path = os.environ.get('COOKIE', '/Users/jdyer/development/youtube-watching/youtube-watching.txt')
    validate_cookie_file(cookie_path)
    logger.info("Starting youtube-watching app on 0.0.0.0:5678")
    serve(app, host="0.0.0.0", port=5678)
