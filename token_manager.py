# token_manager.py
import os
import json
import requests  # Needed for notify_discord
from base64 import b64encode
from datetime import datetime, timedelta, timezone
import asyncio
from dotenv import load_dotenv
import aiohttp

load_dotenv()

# --- Configuration ---
GITHUB_API = "https://api.github.com"
BRANCH = "main"
ZONES = ["br", "ind", "bd"]

LOCAL_CONFIG_DIR = "configs"

REPO_TOKENS = os.getenv("REPO_TOKENS")
AUTH_URL = os.getenv("AUTH_URL")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
WEEBOOK_URL = os.getenv("WEEBOOK_URL")

STALE_TOKEN_HOURS = 6      
MAX_TOKENS = 110           

HEADERS = {
    "Authorization": f"token {GITHUB_TOKEN}",
    "Accept": "application/vnd.github.v3+json"
}

# Store last commit times for each zone
last_commit_times = {zone: None for zone in ZONES}


def notify_discord(message: str):
    """Send a notification to Discord via webhook."""
    if not WEEBOOK_URL:
        print("[Discord] Notification skipped.")
        return
    try:
        requests.post(WEEBOOK_URL, json={"content": message}, timeout=5)
    except Exception as e:
        print(f"[Discord] Error: {e}")


async def get_github_file_content(session, repo: str, path: str):
    """Get file content from GitHub repository and return (content, sha)."""
    url = f"{GITHUB_API}/repos/{repo}/contents/{path}"
    async with session.get(url, headers=HEADERS) as response:
        if response.status == 200:
            file_info = await response.json()
            # Download raw content
            download_url = file_info.get('download_url')
            if download_url:
                async with session.get(download_url, timeout=10) as content_response:
                    if content_response.status == 200:
                        content = await content_response.text()
                        return content, file_info['sha']
            return None, file_info.get('sha')
    return None, None


async def get_github_file_commit_info(session, repo: str, path: str):
    """Get the last commit date for a given file on GitHub."""
    url = f"{GITHUB_API}/repos/{repo}/commits?path={path}&page=1&per_page=1"
    async with session.get(url, headers=HEADERS) as response:
        if response.status == 200:
            commits = await response.json()
            if commits:
                date_str = commits[0]['commit']['committer']['date']
                return datetime.fromisoformat(date_str.replace('Z', '+00:00'))
    return None


async def update_github_file(session, repo: str, path: str, content: str, sha: str | None):
    """Update a file on GitHub repository."""
    url = f"{GITHUB_API}/repos/{repo}/contents/{path}"
    data = {
        "message": f"Auto update {path} @ {datetime.now(timezone.utc).isoformat()}",
        "content": b64encode(content.encode()).decode(),
        "sha": sha,
        "branch": BRANCH
    }
    try:
        async with session.put(url, headers=HEADERS, data=json.dumps(data)) as r:
            return r.status in [200, 201]
    except Exception as e:
        print(f"Update error for {path}: {e}")
        return False


async def get_auth_token(session, uid: str, password: str):
    """Get auth token from AUTH_URL using uid and password."""
    try:
        async with session.get(AUTH_URL, params={"uid": uid, "password": password}, timeout=10) as res:
            if res.status == 200:
                return (await res.json()).get("token")
            return None
    except Exception:
        return None


async def refresh_zone(session, zone: str):
    zone = zone.lower()
    if zone not in ZONES:
        notify_discord(f"❌ Unknown zone: {zone}")
        return

    try:
        config_path = os.path.join(LOCAL_CONFIG_DIR, f"config_{zone}.json")
        token_path = f"tokens/token_{zone}.json"
        
        notify_discord(f"⏳ Refreshing `{zone}` tokens...")

        # Check if local config exists
        if not os.path.exists(config_path):
            notify_discord(f"❌ Config file not found: {config_path}")
            return

        # Load local config accounts
        with open(config_path, "r", encoding="utf-8") as f:
            config_data = json.load(f)

        # Limit accounts to MAX_TOKENS
        accounts = config_data[:MAX_TOKENS]

        tokens = []
        count_success = 0
        count_fail = 0
        processed_count = 0

        # Generate tokens for accounts
        for acc in accounts:
            if 'uid' in acc and 'password' in acc:
                processed_count += 1
                token = await get_auth_token(session, acc['uid'], acc['password'])
                if token:
                    tokens.append({"token": token})
                    count_success += 1
                else:
                    count_fail += 1
            if processed_count % 20 == 0:
                notify_discord(f"🔄 `{zone}`: {processed_count} tokens traités sur {len(accounts)}.")

        notify_discord(f"🔄 `{zone}`: {count_success} tokens OK, {count_fail} failed.")

        # Get current SHA of token file
        _, sha = await get_github_file_content(session, REPO_TOKENS, token_path)

        # Update token file on GitHub
        updated = await update_github_file(session, REPO_TOKENS, token_path, json.dumps(tokens, indent=2), sha)

        if updated:
            last_commit_times[zone] = datetime.now(timezone.utc)
            notify_discord(f"✅ `{token_path}` updated with {len(tokens)} tokens.")
        else:
            notify_discord(f"⚠️ Failed to update `{token_path}`.")
    except Exception as e:
        notify_discord(f"❌ Error in zone `{zone}`: {str(e)}")


async def check_and_refresh_on_startup(session):
    """
    Checks if token files exist on GitHub for each zone.
    If a file is missing, it triggers a refresh for that specific zone.
    """
    for zone in ZONES:
        token_path = f"tokens/token_{zone}.json"
        if not await github_file_exists(session, token_path):
            notify_discord("`                                     `")
            notify_discord(f"⚠️ No token file found for `{zone}`. Generating now...")
            await refresh_zone(session, zone)
        else:
            notify_discord(f"✅ Token file found for `{zone}`. Skipping initial refresh.")


async def check_token_validity(session):

    while True:
        for zone in ZONES:
            token_path = f"tokens/token_{zone}.json"
            commit_dt = await get_github_file_commit_info(session, REPO_TOKENS, token_path)

            if commit_dt:
                time_diff = datetime.now(timezone.utc) - commit_dt

                is_stale = time_diff > timedelta(hours=STALE_TOKEN_HOURS)
                if is_stale:
                    notify_discord("`                                     `")
                    notify_discord(f"⚠️ Tokens `{zone}` expired. Refreshing...")
                    await refresh_zone(session, zone)


        await asyncio.sleep(60)  



async def github_file_exists(session, filename: str) -> bool:
    url = f"https://api.github.com/repos/{REPO_TOKENS}/contents/{filename}"
    async with session.get(url, headers=HEADERS) as response:
        return response.status == 200
