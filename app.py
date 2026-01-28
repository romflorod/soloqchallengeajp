from flask import Flask, request, jsonify
from flask_cors import CORS
import requests
import os
import urllib.parse
import time
from concurrent.futures import ThreadPoolExecutor

app = Flask(__name__)
CORS(app)

def fetch_data(url, headers, timeout=5, retries=3):
    for i in range(retries + 1):
        try:
            response = requests.get(url, headers=headers, timeout=timeout)
            if response.status_code == 429:
                retry_after = int(response.headers.get('Retry-After', 1))
                print(f"[API] Rate limit 429. Retrying in {retry_after}s...")
                time.sleep(retry_after)
                continue
            
            response.raise_for_status()
            return response.json(), None
        except requests.exceptions.RequestException as e:
            if i == retries:
                print(f"[API] Error fetching {url}: {e}")
                status_code = 500
                error_msg = str(e)
                if hasattr(e, 'response') and e.response is not None:
                    print(f"[API] Response Status: {e.response.status_code}, Body: {e.response.text}")
                    status_code = e.response.status_code
                    error_msg = e.response.text
                return None, {"status": status_code, "details": error_msg}
            time.sleep(0.5)
    return None, {"status": 500, "details": "Max retries exceeded"}

def fetch_and_process_match(match_id, headers, puuid):
    """Fetches a single match and returns processed stats for the player."""
    url = f"https://europe.api.riotgames.com/lol/match/v5/matches/{match_id}"
    data, _ = fetch_data(url, headers)
    if data:
        info = data.get('info', {})
        participants = info.get('participants', [])
        player_stats = next((p for p in participants if p.get('puuid') == puuid), None)
        if player_stats:
            return {
                "gameCreation": info.get('gameCreation', 0),
                "gameDuration": info.get('gameDuration', 0),
                "queueId": info.get('queueId', 0),
                "win": player_stats.get('win'),
                "kills": player_stats.get('kills', 0),
                "deaths": player_stats.get('deaths', 0),
                "assists": player_stats.get('assists', 0),
                "championName": player_stats.get('championName', 'Unknown'),
                "cs": player_stats.get('totalMinionsKilled', 0) + player_stats.get('neutralMinionsKilled', 0),
                "gold": player_stats.get('goldEarned', 0),
                "damage": player_stats.get('totalDamageDealtToChampions', 0),
                "vision": player_stats.get('visionScore', 0),
                "items": [
                    player_stats.get('item0', 0), player_stats.get('item1', 0), player_stats.get('item2', 0),
                    player_stats.get('item3', 0), player_stats.get('item4', 0), player_stats.get('item5', 0),
                    player_stats.get('item6', 0)
                ]
            }
    return None

@app.route('/', methods=['GET'])
@app.route('/api/player', methods=['GET'])
def player():
    try:
        start_time = time.time()
        name = request.args.get('name')
        tag = request.args.get('tag')

        print(f"[API] Request: name={name}, tag={tag}")

        if not name or not tag:
            return jsonify({"error": "Missing name or tag"}), 400

        api_key = os.environ.get('RIOT_API_KEY')
        if not api_key:
            print("[API] CRITICAL: RIOT_API_KEY environment variable not found.")
            return jsonify({"error": "Server is not configured with a RIOT_API_KEY."}), 500
        
        api_key = api_key.strip() # Eliminar espacios en blanco o saltos de línea
        print(f"[API] Found RIOT_API_KEY: {api_key[:10]}...")  # Log primeros 10 chars
        headers = {"X-Riot-Token": api_key}

        # 1. Get PUUID
        encoded_name = urllib.parse.quote(name)
        encoded_tag = urllib.parse.quote(tag)
        account_url = f"https://europe.api.riotgames.com/riot/account/v1/accounts/by-riot-id/{encoded_name}/{encoded_tag}"
        
        print(f"[API] Fetching account: {account_url}")
        account_data, error = fetch_data(account_url, headers, timeout=10)
        if not account_data:
            print(f"[API] Error fetching account: {error}")
            return jsonify({"error": "Riot API Error", "details": error['details']}), error['status']
            
        puuid = account_data.get('puuid')
        game_name = account_data.get('gameName', name)
        print(f"[API] Step 1 took {time.time() - start_time:.2f}s: PUUID={puuid}")

        step2_start = time.time()
        # 2. Fetch Summoner, Ranked, and Match IDs in parallel
        summoner_url = f"https://euw1.api.riotgames.com/lol/summoner/v4/summoners/by-puuid/{puuid}"
        ranked_url = f"https://euw1.api.riotgames.com/lol/league/v4/entries/by-puuid/{puuid}"
        match_ids_url = f"https://europe.api.riotgames.com/lol/match/v5/matches/by-puuid/{puuid}/ids?queue=420&start=0&count=10"
        mastery_url = f"https://euw1.api.riotgames.com/lol/champion-mastery/v4/champion-masteries/by-puuid/{puuid}/top?count=3"
        spectator_url = f"https://euw1.api.riotgames.com/lol/spectator/v5/active-games/by-summoner/{puuid}"

        def fetch_silent(u, h):
            d, _ = fetch_data(u, h)
            return d

        with ThreadPoolExecutor(max_workers=3) as executor:
            future_summoner = executor.submit(fetch_silent, summoner_url, headers)
            future_ranked = executor.submit(fetch_silent, ranked_url, headers)
            future_match_ids = executor.submit(fetch_silent, match_ids_url, headers)
            future_mastery = executor.submit(fetch_silent, mastery_url, headers)
            future_spectator = executor.submit(fetch_silent, spectator_url, headers)

            summoner_data = future_summoner.result() or {}
            ranked_data = future_ranked.result() or []
            match_ids = future_match_ids.result() or []
            mastery_data = future_mastery.result() or []
            spectator_data = future_spectator.result()

        print(f"[API] Step 2 took {time.time() - step2_start:.2f}s")
        level = summoner_data.get('summonerLevel')
        solo_q_data = next((q for q in ranked_data if q.get('queueType') == 'RANKED_SOLO_5x5'), None)

        # 3. Fetch Matches in parallel
        step3_start = time.time()
        recent_games = []
        total_kills = 0
        total_deaths = 0
        total_assists = 0
        champ_stats = {} 
        last_match = None

        if match_ids:
            with ThreadPoolExecutor(max_workers=10) as executor:
                futures = [executor.submit(fetch_and_process_match, mid, headers, puuid) for mid in match_ids[:10]]
                
                for i, future in enumerate(futures):
                    details = future.result()
                    if details:
                        if i == 0:
                            last_match = details
                        win = details.get('win')
                        recent_games.append("W" if win else "L")
                        
                        k = details.get('kills', 0)
                        d = details.get('deaths', 0)
                        a = details.get('assists', 0)
                        total_kills += k
                        total_deaths += d
                        total_assists += a
                        
                        c_name = details.get('championName')
                        if c_name:
                            if c_name not in champ_stats:
                                champ_stats[c_name] = {'wins': 0, 'losses': 0, 'count': 0}
                            champ_stats[c_name]['count'] += 1
                            if win:
                                champ_stats[c_name]['wins'] += 1
                            else:
                                champ_stats[c_name]['losses'] += 1
        print(f"[API] Step 3 took {time.time() - step3_start:.2f}s")

        # Calculate stats
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

        kda = None
        avg_k = None
        avg_d = None
        avg_a = None
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
            top_champs.append({
                "name": champ_name,
                "wins": stats['wins'],
                "losses": stats['losses'],
                "winrate": winrate
            })

        # Process Mastery
        top_mastery = []
        if mastery_data:
            for m in mastery_data:
                top_mastery.append({
                    "championId": m.get('championId'),
                    "level": m.get('championLevel'),
                    "points": m.get('championPoints')
                })

        # Process Active Game
        is_in_game = False
        if spectator_data and spectator_data.get('gameId'):
            is_in_game = True

        if not solo_q_data:
            return jsonify({
                "name": game_name,
                "tag": tag,
                "tier": "UNRANKED",
                "rank": "",
                "lp": 0,
                "wins": 0,
                "losses": 0,
                "level": level,
                "recent_games": recent_games,
                "kda": kda,
                "avg_k": avg_k,
                "avg_d": avg_d,
                "avg_a": avg_a,
                "streak": streak,
                "last_match": last_match,
                "top_champs": top_champs,
                "opgg_url": f"https://www.op.gg/summoners/euw/{urllib.parse.quote(name)}-{tag}",
                "top_mastery": top_mastery,
                "is_in_game": is_in_game
            })

        response = {
            "name": game_name,
            "tag": tag,
            "tier": solo_q_data.get('tier'),
            "rank": solo_q_data.get('rank'),
            "lp": solo_q_data.get('leaguePoints', 0),
            "wins": solo_q_data.get('wins', 0),
            "losses": solo_q_data.get('losses', 0),
            "level": level,
            "recent_games": recent_games,
            "kda": kda,
            "avg_k": avg_k,
            "avg_d": avg_d,
            "avg_a": avg_a,
            "streak": streak,
            "last_match": last_match,
            "top_champs": top_champs,
            "ladder_rank": None,
            "ranked_flex": None,
            "mastery": None, # Deprecated field
            "masteries": [], # Deprecated field
            "past_rank": None,
            "past_ranks": [],
            "opgg_url": f"https://www.op.gg/summoners/euw/{urllib.parse.quote(name)}-{tag}",
            "top_mastery": top_mastery,
            "is_in_game": is_in_game
        }
        
        print(f"[API] Total request time: {time.time() - start_time:.2f}s")
        return jsonify(response)

    except Exception as err:
        import traceback
        print(f"[API] An unexpected error occurred: {err}")
        traceback.print_exc()
        return jsonify({"error": "Internal server error", "details": str(err)}), 500

# IMPORTANTE: Para Vercel, NO uses app.run()
# La app Flask se exporta automáticamente