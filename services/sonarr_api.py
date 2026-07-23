import os
import aiohttp
from urllib.parse import urljoin
from dotenv import load_dotenv

load_dotenv()

class SonarrAPI:
    def __init__(self, base_url: str, api_key: str):
        # Ensure base_url ends with a slash for urljoin
        self.base_url = base_url.rstrip("/") + "/"
        self.api_key = api_key
        self.headers = {"X-Api-Key": self.api_key}

    async def _request(self, method: str, endpoint: str, **kwargs) -> dict | list | None:
        """Helper to make async HTTP requests to Sonarr."""
        url = urljoin(self.base_url, endpoint)
        
        async with aiohttp.ClientSession(headers=self.headers) as session:
            async with session.request(method, url, **kwargs) as response:
                if response.status in (200, 201, 202):
                    return await response.json()
                elif response.status == 404:
                    return None
                else:
                    text = await response.text()
                    raise RuntimeError(f"Sonarr API error {response.status} on {endpoint}: {text}")

    async def lookup_series(self, term: str) -> list[dict]:
        """Search TVDB via Sonarr for a show name."""
        return await self._request("GET", "api/v3/series/lookup", params={"term": term})

    async def get_root_folders(self) -> list[dict]:
        """Get available root folders (e.g., D:\Downloads\Anime)."""
        return await self._request("GET", "api/v3/rootfolder")

    async def get_quality_profiles(self) -> list[dict]:
        """Get available quality profiles to find '1080p Dub Tracker' ID."""
        return await self._request("GET", "api/v3/qualityprofile")

    async def get_series(self) -> list[dict]:
        """Get all currently tracked series."""
        return await self._request("GET", "api/v3/series")

    async def add_series(self, tvdb_id: int, title: str, quality_profile_id: int, root_folder_path: str) -> dict:
        """Add a new series to Sonarr with Anime series type."""
        # First, we must lookup the series to get the exact payload format Sonarr expects
        lookup_results = await self.lookup_series(f"tvdb:{tvdb_id}")
        if not lookup_results:
            raise ValueError(f"Could not find TVDB ID {tvdb_id} to construct add payload.")
            
        show_data = lookup_results[0]
        
        # Build the payload for an anime addition
        payload = {
            "title": show_data["title"],
            "tvdbId": show_data["tvdbId"],
            "titleSlug": show_data["titleSlug"],
            "images": show_data["images"],
            "seasons": show_data["seasons"],
            "qualityProfileId": quality_profile_id,
            "rootFolderPath": root_folder_path,
            "seriesType": "anime",            # CRITICAL: Forces Absolute Numbering
            "monitored": True,
            "addOptions": {
                "searchForMissingEpisodes": False, # Just wait for the RSS feed
                "ignoreEpisodesWithFiles": True
            }
        }
        
        return await self._request("POST", "api/v3/series", json=payload)

    async def delete_series(self, series_id: int, delete_files: bool = False) -> None:
        """Remove a series from Sonarr by its internal Sonarr ID."""
        params = {"deleteFiles": "true" if delete_files else "false"}
        await self._request("DELETE", f"api/v3/series/{series_id}", params=params)

    async def unmonitor_episode(self, episode_id: int) -> dict | None:
        """Fetch an episode, set it to unmonitored, and save it back."""
        endpoint = f"api/v3/episode/{episode_id}"
        
        # 1. Get current episode data
        episode_data = await self._request("GET", endpoint)
        if not episode_data:
            return None
            
        # 2. If it's already unmonitored, do nothing
        if not episode_data.get("monitored"):
            return episode_data
            
        # 3. Change monitored status and save
        episode_data["monitored"] = False
        return await self._request("PUT", endpoint, json=episode_data)
    

# Create a singleton instance to import into your handlers
sonarr = SonarrAPI(
    base_url=os.getenv("SONARR_URL", "http://localhost:8989"),
    api_key=os.getenv("SONARR_API_KEY", "")
)