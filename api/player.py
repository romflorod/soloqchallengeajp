import os
import requests
from urllib.parse import urlencode

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
        
        riot_api_key = os.environ.get('RIOT_API_KEY')
        
        if not riot_api_key:
            print("[API] RIOT_API_KEY not configured")
            return {"error": "RIOT_API_KEY not configured"}, 500
        
        print("[API] API Key found, requesting account data...")
        headers = {"X-Riot-Token": riot_api_key}
        
        # 1) Get PUUID
        account_url = f"https://europe.api.riotgames.com/riot/account/v1/accounts/by-riot-id/{name}/{tag}"
        account_res = requests.get(account_url, headers=headers)
        
        print(f"[API] Account Response Status: {account_res.status_code}")
        
        if not account_res.ok:
            error_data = account_res.text
            print(f"[API] Account API Error: {error_data}")
            return {"error": "Summoner not found"}, 404
        
        account_data = account_res.json()
        puuid = account_data.get('puuid')
        print(f"[API] PUUID obtained: {puuid}")
        
        # 2) Get summoner info
        summoner_url = f"https://euw1.api.riotgames.com/lol/summoner/v4/summoners/by-puuid/{puuid}"
        summoner_res = requests.get(summoner_url, headers=headers)
        
        print(f"[API] Summoner Response Status: {summoner_res.status_code}")
        
        if not summoner_res.ok:
            error_data = summoner_res.text
            print(f"[API] Summoner API Error: {error_data}")
            return {"error": "Summoner info not found"}, 404
        
        summoner_data = summoner_res.json()
        summoner_id = summoner_data.get('id')
        print(f"[API] Summoner data obtained for ID: {summoner_id}")
        
        # 3) Get ranked info
        ranked_url = f"https://euw1.api.riotgames.com/lol/league/v4/entries/by-summoner/{summoner_id}"
        ranked_res = requests.get(ranked_url, headers=headers)
        
        print(f"[API] Ranked Response Status: {ranked_res.status_code}")
        
        if not ranked_res.ok:
            error_data = ranked_res.text
            print(f"[API] Ranked API Error: {error_data}")
            return {"error": "Ranked info not found"}, 404
        
        ranked_data = ranked_res.json()
        solo_q = next((q for q in ranked_data if q.get('queueType') == 'RANKED_SOLO_5x5'), None)
        
        print(f"[API] SoloQ found: {solo_q is not None}")
        
        if not solo_q:
            response = {
                "name": name,
                "tag": tag,
                "tier": "UNRANKED",
                "rank": "",
                "lp": 0,
                "wins": 0,
                "losses": 0
            }
            print(f"[API] Returning UNRANKED response: {response}")
            return response, 200
        
        response = {
            "name": name,
            "tag": tag,
            "tier": solo_q.get('tier'),
            "rank": solo_q.get('rank'),
            "lp": solo_q.get('leaguePoints', 0),
            "wins": solo_q.get('wins', 0),
            "losses": solo_q.get('losses', 0)
        }
        print(f"[API] Returning ranked response: {response}")
        return response, 200
        
    except Exception as err:
        print(f"[API] Error: {err}")
        return {"error": "Internal server error", "details": str(err)}, 500
