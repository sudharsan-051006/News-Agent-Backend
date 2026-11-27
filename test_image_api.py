
from dotenv import load_dotenv
import os
import requests

load_dotenv()

url = os.getenv(
    "IMAGE_SEARCH_API_URL",
    "https://image-search-errf.onrender.com/search",
)
api_key = os.getenv("IMAGE_SEARCH_API_KEY", "")

headers = {"Content-Type": "application/json"}

if api_key:
    headers["X-API-Key"] = api_key

response = requests.post(
    url,
    headers=headers,
    json={
        "sentence": (
            "SpaceX and Tesla merger proposal discussed by Elon Musk"
        ),
        "count": 5,
    },
    timeout=30,
)

print("HTTP status:", response.status_code)
response.raise_for_status()

print("API response:")
print(response.text[:5000])
