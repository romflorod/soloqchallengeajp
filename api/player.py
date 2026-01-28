import os
import requests
import urllib.parse
from concurrent.futures import ThreadPoolExecutor

def fetch_and_process_match(match_id, headers, puuid):
    """Fetches a single match and returns processed stats for the player."""
    try:
        match_url = f"https://europe.api.riotgames.com/lol/match/v5/matches/{match_id}"
        match_res = requests.get(match_url, headers=headers, timeout=5)
        if match_res.ok:
            match_data = match_res.json()
            info = match_data.get('info', {})
            participants = info.get('participants', [])
            player_stats = next((p for p in participants if p.get('puuid') == puuid), None)
            if player_stats:
                return {
                    "win": player_stats.get('win'),
                    "kills": player_stats.get('kills', 0),
                    "deaths": player_stats.get('deaths', 0),
                    "assists": player_stats.get('assists', 0),
                    "championName": player_stats.get('championName')
                }
    except requests.exceptions.RequestException as e:
        print(f"[API] Failed to fetch match {match_id}: {e}")
    return None

def handler(req):
    """Handler for Vercel serverless functions"""
    try:
        # Get query parameters
        name = req.args.get('name')
        tag = req.args.get('tag')

        print(f"[API] Request: name={name}, tag={tag}")

        if not name or not tag:
            print("[API] Missing name or tag")
            return {"error": "Missing name or tag"}, 400

        api_key = os.environ.get('RIOT_API_KEY')

        if not api_key:
            print("[API] RIOT_API_KEY not configured")
            return {"error": "RIOT_API_KEY not configured"}, 500

        print("[API] API Key found, requesting account data...")
        headers = {"X-Riot-Token": api_key}

        # 1. Get PUUID
        encoded_name = urllib.parse.quote(name)
        encoded_tag = urllib.parse.quote(tag)
        account_url = f"https://europe.api.riotgames.com/riot/account/v1/accounts/by-riot-id/{encoded_name}/{encoded_tag}"
        account_res = requests.get(account_url, headers=headers, timeout=10)

        print(f"[API] Account Response Status: {account_res.status_code}")

        if not account_res.ok:
            error_data = account_res.text
            print(f"[API] Account API Error: {error_data}")
            return {"error": "Riot Account not found"}, 404

        puuid = account_res.json().get('puuid')
        print(f"[API] PUUID obtained: {puuid}")

        # 2. Get Summoner data (level)
        summoner_url = f"https://euw1.api.riotgames.com/lol/summoner/v4/summoners/by-puuid/{puuid}"
        summoner_res = requests.get(summoner_url, headers=headers, timeout=10)
        summoner_data = summoner_res.json() if summoner_res.ok else {}
        level = summoner_data.get('summonerLevel')

        # 3. Get Ranked data
        ranked_url = f"https://euw1.api.riotgames.com/lol/league/v4/entries/by-puuid/{puuid}"
        ranked_res = requests.get(ranked_url, headers=headers, timeout=10)
        ranked_data = ranked_res.json() if ranked_res.ok else []
        solo_q_data = next((q for q in ranked_data if q.get('queueType') == 'RANKED_SOLO_5x5'), None)

        # 4. Get Match History
        recent_games = []
        total_kills = 0
        total_deaths = 0
        total_assists = 0
        champ_stats = {}

        match_ids_url = f"https://europe.api.riotgames.com/lol/match/v5/matches/by-puuid/{puuid}/ids?queue=420&start=0&count=10"
        match_ids_res = requests.get(match_ids_url, headers=headers, timeout=10)
        match_ids = match_ids_res.json() if match_ids_res.ok else []

        with ThreadPoolExecutor(max_workers=10) as executor:
            future_to_match = {executor.submit(fetch_and_process_match, match_id, headers, puuid): match_id for match_id in match_ids}
            for future in future_to_match:
                match_details = future.result()
                if match_details:
                    win = match_details.get('win')
                    recent_games.append("W" if win else "L")
                    k = match_details.get('kills', 0)
                    d = match_details.get('deaths', 0)
                    a = match_details.get('assists', 0)
                    total_kills += k
                    total_deaths += d
                    total_assists += a
                    c_name = match_details.get('championName')
                    if c_name not in champ_stats:
                        champ_stats[c_name] = {'wins': 0, 'losses': 0, 'count': 0}
                    champ_stats[c_name]['count'] += 1
                    if win:
                        champ_stats[c_name]['wins'] += 1
                    else:
                        champ_stats[c_name]['losses'] += 1

        # --- CALCULATE STATS ---
        streak = None
        if recent_games:
            current_streak_type = recent_games[0]
            current_streak_count = 0
            for result in recent_games:
                if result == current_streak_type:
                    current_streak_count += 1
                else:
                    break
            if current_streak_count >= 3:
                streak = f"{current_streak_count} {'Win' if current_streak_type == 'W' else 'Loss'} Streak"

        kda, avg_k, avg_d, avg_a = None, None, None, None
        if recent_games:
            games_count = len(recent_games)
            avg_k = round(total_kills / games_count, 1)
            avg_d = round(total_deaths / games_count, 1)
            avg_a = round(total_assists / games_count, 1)
            kda = round((total_kills + total_assists) / total_deaths, 2) if total_deaths > 0 else round(total_kills + total_assists, 2)

        top_champs = []
        sorted_champs = sorted(champ_stats.items(), key=lambda item: item[1]['count'], reverse=True)
        for champ_name, stats in sorted_champs[:3]:
            winrate = int((stats['wins'] / stats['count']) * 100)
            top_champs.append({"name": champ_name, "wins": stats['wins'], "losses": stats['losses'], "winrate": winrate})

        if not solo_q_data:
            return {
                "name": name, "tag": tag, "tier": "UNRANKED", "rank": "", "lp": 0,
                "wins": 0, "losses": 0, "level": level, "recent_games": recent_games,
                "kda": kda, "avg_k": avg_k, "avg_d": avg_d, "avg_a": avg_a, "streak": streak,
                "top_champs": top_champs,
                "opgg_url": f"https://www.op.gg/summoners/euw/{urllib.parse.quote(name)}-{tag}"
            }, 200

        response = {
            "name": name,
            "tag": tag,
            "tier": solo_q_data.get('tier'),
            "rank": solo_q_data.get('rank'),
            "lp": solo_q_data.get('leaguePoints', 0),
            "wins": solo_q_data.get('wins', 0),
            "losses": solo_q_data.get('losses', 0),
            "level": level,
            "recent_games": recent_games,
            "kda": kda, "avg_k": avg_k, "avg_d": avg_d, "avg_a": avg_a, "streak": streak,
            "top_champs": top_champs,
            "ladder_rank": None, "ranked_flex": None, "mastery": None, "masteries": [],
            "past_rank": None, "past_ranks": [],
            "opgg_url": f"https://www.op.gg/summoners/euw/{urllib.parse.quote(name)}-{tag}"
        }
        return response, 200

    except Exception as err:
        print(f"[API] Error: {err}")
        return {"error": "Internal server error", "details": str(err)}, 500
