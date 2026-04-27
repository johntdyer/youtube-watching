"""
youtube-watching
"""

import os
import sys
from http.cookiejar import MozillaCookieJar
import json
import re
import requests
from flask import Flask
from flask_restful import Resource, Api

app = Flask(__name__)
api = Api(app)


def yt_history(cookie):
    """
    get latest video from youtube history excluding reel shelf (shorts)
    """

    # COOKIES
    cookie_jar = MozillaCookieJar(cookie)

    try:
        cookie_jar.load(ignore_discard=True, ignore_expires=True)

    except OSError as notfound_error:
        print(f"WARNING: {cookie} not found\nDEBUG: {notfound_error}")
        sys.exit()

    # SESSION
    session = requests.Session()
    session.headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)\
            AppleWebKit/537.36 (KHTML, like Gecko) Chrome/81.0.4044.138 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-us,en;q=0.5",
        "Sec-Fetch-Mode": "navigate",
    }
    session.cookies = cookie_jar

    # RESPONSE
    response = session.get("https://www.youtube.com/feed/history")
    cookie_jar.save(ignore_discard=True, ignore_expires=True)
    html = response.text

    # JSON
    try:
        regex = r"var ytInitialData = (.*?);<\/script>"
        match = re.search(regex, html).group(1)
        data = json.loads(match)

        path = data["contents"]["twoColumnBrowseResultsRenderer"]\
            ["tabs"][0]["tabRenderer"]["content"]["sectionListRenderer"]\
            ["contents"][0]["itemSectionRenderer"]["contents"]

    except AttributeError as data_error:
        print(f"WARNING: Can't find data, update cookie file\nDEBUG: {data_error}")
        sys.exit()

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
    for item in path:
        if "videoRenderer" in item:
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
        cookie_path = os.environ.get('COOKIE', '/Users/jdyer/development/youtube-watching/app/youtube-watching.txt')
        return yt_history(cookie_path)


api.add_resource(RestApi, "/")

if __name__ == "__main__":
    from waitress import serve
    serve(app, host="0.0.0.0", port=5678)
