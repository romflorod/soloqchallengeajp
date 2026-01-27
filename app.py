from flask import Flask, request, jsonify
from flask_cors import CORS
import requests
import os
from bs4 import BeautifulSoup
import json
import urllib.parse
import re

app = Flask(__name__)
CORS(app)

def fetch_mcp_data(name, tag):
    """Consulta el servidor MCP de OP.GG para obtener datos estructurados."""
    url = "https://mcp-api.op.gg/mcp"
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    # Payload JSON-RPC 2.0 para la herramienta lol_get_summoner_profile
    payload = {
        "jsonrpc": "2.0",
        "method": "tools/call",
        "params": {
            "name": "lol_get_summoner_profile",
            "arguments": {
                "region": "euw",
                "game_name": name,
                "tagline": tag
            }
        },
        "id": 1
    }
    
    try:
        print(f"[MCP] Fetching data for {name}#{tag}...")
        res = requests.post(url, json=payload, headers=headers, timeout=5)
        
        if res.status_code == 200:
            json_resp = res.json()
            # La respuesta MCP suele venir dentro de result -> content -> text (que es un string JSON)
            if 'result' in json_resp and 'content' in json_resp['result']:
                for content in json_resp['result']['content']:
                    if content['type'] == 'text':
                        return json.loads(content['text'])
        else:
            print(f"[MCP] HTTP Error: {res.status_code}")
            
    except Exception as e:
        print(f"[MCP] Exception: {e}")
    return None

def fetch_mcp_matches(name, tag):
    """Consulta el historial de partidas via MCP."""
    url = "https://mcp-api.op.gg/mcp"
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    payload = {
        "jsonrpc": "2.0",
        "method": "tools/call",
        "params": {
            "name": "lol_list_summoner_matches",
            "arguments": {
                "region": "euw",
                "game_name": name,
                "tagline": tag
            }
        },
        "id": 1
    }
    try:
        res = requests.post(url, json=payload, headers=headers, timeout=5)
        if res.status_code == 200:
            json_resp = res.json()
            if 'result' in json_resp and 'content' in json_resp['result']:
                for content in json_resp['result']['content']:
                    if content['type'] == 'text':
                        return json.loads(content['text'])
    except Exception:
        pass
    return None

@app.route('/api/player', methods=['GET'])
def player():
    try:
        name = request.args.get('name')
        tag = request.args.get('tag')
        
        print(f"[API] Request: name={name}, tag={tag}")
        
        if not name or not tag:
            return jsonify({"error": "Missing name or tag"}), 400
        
        # Construir URL de op.gg (Asumimos EUW por defecto)
        # Formato: https://www.op.gg/summoners/euw/Nombre-Tag
        encoded_name = urllib.parse.quote(name)
        opgg_url = f"https://www.op.gg/summoners/euw/{encoded_name}-{tag}"
        
        # ---------------------------------------------------------
        # 1. INTENTO CON OP.GG MCP SERVER (API OFICIAL PARA AI)
        # ---------------------------------------------------------
        mcp_data = fetch_mcp_data(name, tag)
        
        if mcp_data and 'data' in mcp_data:
            print("[MCP] Data received successfully! Parsing...")
            try:
                data = mcp_data['data']
                summoner = data.get('summoner', {})
                league_stats = summoner.get('league_stats', [])
                
                # Buscar SoloQ (ID 420) y Flex (ID 440)
                solo_q = next((q for q in league_stats if q.get('queue_info', {}).get('id') == 420), {})
                flex_q = next((q for q in league_stats if q.get('queue_info', {}).get('id') == 440), {})
                
                tier_info = solo_q.get('tier_info', {})
                
                # Mapear Top Champions
                top_champs = []
                # A veces viene en 'most_champions' dentro de summoner
                most_champs = summoner.get('most_champions', [])
                for c in most_champs:
                    # Intentar obtener nombre del campeón. Si viene solo ID, el frontend podría fallar sin un mapa.
                    # Asumimos que MCP devuelve datos enriquecidos o 'name'.
                    c_name = c.get('name') or c.get('champion', {}).get('name')
                    if c_name:
                        top_champs.append({
                            "name": c_name,
                            "wins": c.get('win', 0),
                            "losses": c.get('lose', 0),
                            "winrate": int((c.get('win', 0) / c.get('play', 1)) * 100) if c.get('play') else 0
                        })

                # Construir respuesta Flex
                ranked_flex = None
                if flex_q:
                    f_tier = flex_q.get('tier_info', {})
                    if f_tier.get('tier'):
                        ranked_flex = f"{f_tier.get('tier')} {f_tier.get('division')} {f_tier.get('lp')} LP"

                # Obtener historial de partidas (Últimos 10)
                recent_games = []
                try:
                    matches_data = fetch_mcp_matches(name, tag)
                    if matches_data and 'data' in matches_data:
                        # La estructura suele ser una lista de partidas en 'data'
                        m_list = matches_data['data'] if isinstance(matches_data['data'], list) else matches_data['data'].get('matches', [])
                        for m in m_list[:10]:
                            # Buscamos la propiedad 'win' (true/false)
                            if 'win' in m:
                                recent_games.append("W" if m['win'] else "L")
                except Exception as e:
                    print(f"[MCP] Error fetching matches: {e}")

                response = {
                    "name": name,
                    "tag": tag,
                    "tier": tier_info.get('tier', 'UNRANKED'),
                    "rank": tier_info.get('division', ''),
                    "lp": tier_info.get('lp', 0),
                    "wins": solo_q.get('win', 0),
                    "losses": solo_q.get('lose', 0),
                    "kda": None, # MCP a veces no da KDA global directo en este endpoint
                    "avg_k": None,
                    "avg_d": None,
                    "avg_a": None,
                    "streak": None, 
                    "ladder_rank": summoner.get('ladder_rank', {}).get('rank'),
                    "level": summoner.get('level'),
                    "ranked_flex": ranked_flex,
                    "mastery": None,
                    "past_rank": None, # Podría estar en previous_seasons
                    "opgg_url": opgg_url,
                    "top_champs": top_champs,
                    "recent_games": recent_games
                }
                return jsonify(response)
                
            except Exception as e:
                print(f"[MCP] Error parsing data: {e}")
                # Si falla el parseo, continuamos al scraper normal

        # ---------------------------------------------------------
        # 2. FALLBACK: SCRAPER HTML (SI MCP FALLA)
        # ---------------------------------------------------------
        
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Referer": "https://www.op.gg/",
            "Connection": "keep-alive"
        }
        
        print(f"[Scraper] Fetching: {opgg_url}")
        res = requests.get(opgg_url, headers=headers)
        
        if res.status_code != 200:
            print(f"[Scraper] Failed to fetch op.gg: {res.status_code}")
            return jsonify({"error": "Failed to fetch data from op.gg"}), 502

        soup = BeautifulSoup(res.text, 'html.parser')
        
        # Inicializar datos por defecto
        tier = "UNRANKED"
        rank = ""
        lp = 0
        wins = 0
        losses = 0
        kda = None
        avg_k = None
        avg_d = None
        avg_a = None
        streak = None
        ladder_rank = None
        level = None
        ranked_flex = None
        mastery = None
        past_rank = None
        top_champs = []
        recent_games = []
        
        # DEBUG: Imprimir título para ver si es Cloudflare o error 404
        if soup.title:
            print(f"[Scraper] Page Title: {soup.title.string}")
        
        # 0. Intentar leer Meta Description (Nuevo método más robusto)
        # Formato: "Name#Tag / Tier Rank LP / WinsWin LossesLose ..."
        meta_desc = soup.find("meta", {"name": "description"})
        if meta_desc:
            content = meta_desc.get("content", "")
            print(f"[Scraper] Found Meta Description: {content}")
            
            if "Unranked" in content:
                tier = "UNRANKED"
            else:
                # Extraer Tier y Rank (Ej: Platinum 2)
                tier_match = re.search(r'(Iron|Bronze|Silver|Gold|Platinum|Emerald|Diamond|Master|Grandmaster|Challenger)\s*(\d)?', content, re.IGNORECASE)
                if tier_match:
                    tier = tier_match.group(1).upper()
                    rank = tier_match.group(2) if tier_match.group(2) else ""
                
                # Extraer LP (Ej: 50LP)
                lp_match = re.search(r'(\d+)\s*LP', content)
                if lp_match:
                    lp = int(lp_match.group(1))
                
                # Extraer Wins/Losses (Ej: 5Win 5Lose)
                wl_match = re.search(r'(\d+)Win\s+(\d+)Lose', content)
                if wl_match:
                    wins = int(wl_match.group(1))
                    losses = int(wl_match.group(2))
                
                # Extraer Top Champions (Suele estar en la 4ª parte de la descripción separada por /)
                # Ejemplo: "... / 5Win 5Lose ... / Malzahar - 60%, Ahri - 55% ..."
                parts = content.split(' / ')
                if len(parts) >= 4:
                    raw_champs = parts[3]
                    # Parsear campeones a objetos estructurados
                    # Formato esperado: "Malzahar - 8Win 5Lose Win rate 62%"
                    for champ_str in raw_champs.split(','):
                        champ_str = champ_str.strip()
                        # Regex para extraer datos: Nombre - Wins - Losses - Winrate
                        match = re.search(r'(.+?)\s*-\s*(\d+)Win\s+(\d+)Lose\s+Win\s*rate\s*(\d+)%', champ_str, re.IGNORECASE)
                        if match:
                            top_champs.append({
                                "name": match.group(1).strip(),
                                "wins": int(match.group(2)),
                                "losses": int(match.group(3)),
                                "winrate": int(match.group(4))
                            })
            
            # Si encontramos la meta tag, usamos estos datos y saltamos el resto
            json_success = True 

        # 0.5 Intentar extraer KDA y Rachas del texto HTML (Funciona incluso si falla JSON)
        # op.gg suele poner el KDA como "3.45:1" y los promedios como "5.2 / 4.1 / 8.3"
        try:
            # Usar separador de espacio para evitar que se peguen las palabras (ej: Mastery34 -> Mastery 34)
            text_content = soup.get_text(separator=' ')
            
            # --- LEVEL ---
            # Intentar buscar por clase (más preciso)
            level_tag = soup.find("span", class_="level")
            if level_tag:
                level = level_tag.get_text().strip()
            else:
                # Fallback regex: "Level 123", "Lvl 123", "My Page 123" (Visto en debug)
                level_match = re.search(r"(?:Level|Lvl|My Page)\.?\s*(\d+)", text_content, re.IGNORECASE)
                if level_match:
                    level = level_match.group(1)
            
            # --- MASTERY ---
            # Ej: "Mastery 34 Malzahar 342,114 pts" (El separador de espacio es clave aquí)
            mastery_match = re.search(r"Mastery\s*\d+\s*(.+?)\s*([\d,]+)\s*pts", text_content)
            if mastery_match:
                mastery = {
                    "champ": mastery_match.group(1).strip(),
                    "points": mastery_match.group(2)
                }

            # --- PAST RANK (S2024 S3) ---
            # Ej: "S2024 S3 platinum 3" o "S2023 S2 emerald 2"
            past_rank_match = re.search(r"S2024\s*S\d\s*([a-zA-Z]+\s*\d*)", text_content, re.IGNORECASE)
            if past_rank_match:
                past_rank = past_rank_match.group(1).upper()

            # --- RANKED FLEX ---
            # Ej: "Ranked Flex emerald 1 14 LP"
            flex_match = re.search(r"Ranked Flex\s*([a-zA-Z]+\s*\d*)\s*(\d+)\s*LP", text_content, re.IGNORECASE)
            if flex_match:
                ranked_flex = f"{flex_match.group(1).upper()} {flex_match.group(2)} LP"

            # --- KDA ---
            # Regex más flexible: "3.45:1", "3:1", "3.45 : 1"
            # Buscamos el patrón X:1 o "KDA 3.45"
            kda_match = re.search(r"(?:KDA)?\s*([\d\.]+)\s*:\s*1", text_content, re.IGNORECASE)
            if kda_match:
                kda = kda_match.group(1)
                
            # Buscar Promedios K/D/A (Ej: 5.2 / 4.1 / 8.3)
            avg_match = re.search(r"(\d+\.\d+)\s*/\s*(\d+\.\d+)\s*/\s*(\d+\.\d+)", text_content)
            if avg_match:
                avg_k, avg_d, avg_a = avg_match.groups()
                
            # Buscar Rachas (Ej: 3 Win Streak)
            streak_match = re.search(r"(\d+)\s*(Win|Loss)\s*Streak", text_content, re.IGNORECASE)
            if streak_match:
                streak = f"{streak_match.group(1)} {streak_match.group(2)}"
                
            # Buscar Ladder Rank (Ej: Ladder Rank 12,345)
            ladder_match = re.search(r"Ladder Rank\s*([\d,]+)", text_content, re.IGNORECASE)
            if ladder_match:
                ladder_rank = ladder_match.group(1)
        except Exception as e:
            print(f"[Scraper] Error extracting KDA/Streak: {e}")

        # 1. Intentar leer JSON (__NEXT_DATA__) - Método secundario
        next_data_tag = soup.find('script', id='__NEXT_DATA__')
        # Solo intentamos JSON si no hemos sacado datos del meta description
        if next_data_tag and tier == "UNRANKED" and wins == 0:
        
            try:
                data = json.loads(next_data_tag.string)
                league_stats = data['props']['pageProps']['data']['league_stats']
                solo_q = next((q for q in league_stats if q.get('queue_info', {}).get('id') == 420), None)
                
                if solo_q:
                    tier_info = solo_q.get('tier_info', {})
                    tier = tier_info.get('tier', 'UNRANKED')
                    rank = tier_info.get('division', '')
                    lp = tier_info.get('lp', 0)
                    wins = solo_q.get('win', 0)
                    losses = solo_q.get('lose', 0)
                json_success = True
            except Exception as e:
                print(f"[Scraper] JSON parsing error: {e}")

        # 2. Si falla JSON, intentar HTML Parsing (Fallback) - Método visual
        if not json_success:
            print("[Scraper] JSON failed or missing. Trying HTML fallback...")
            
            # Buscar texto "Ranked Solo" en el HTML
            ranked_header = soup.find(string=re.compile("Ranked Solo"))
            
            if ranked_header:
                # Buscar contenedor padre que tenga información de LP o Unranked
                container = ranked_header.parent
                found_container = None
                # Subir niveles hasta encontrar el contenedor con los datos
                for _ in range(6): 
                    if container and ("LP" in container.get_text() or "Unranked" in container.get_text()):
                        found_container = container
                        break
                    container = container.parent
                
                if found_container:
                    text = found_container.get_text()
                    # Limpiar espacios extra para facilitar regex
                    text = " ".join(text.split())
                    
                    if "Unranked" in text:
                        tier = "UNRANKED"
                    else:
                        # Regex para Tier y Rank (Ej: Gold 4, Emerald 2, Master)
                        tier_match = re.search(r'(Iron|Bronze|Silver|Gold|Platinum|Emerald|Diamond|Master|Grandmaster|Challenger)\s*(\d)?', text, re.IGNORECASE)
                        if tier_match:
                            tier = tier_match.group(1).upper()
                            rank = tier_match.group(2) if tier_match.group(2) else ""
                        
                        # Regex para LP (Ej: 23 LP)
                        lp_match = re.search(r'(\d+)\s*LP', text)
                        if lp_match:
                            lp = int(lp_match.group(1))
                            
                        # Regex para Wins/Losses (Ej: 20W 15L)
                        wl_match = re.search(r'(\d+)W\s+(\d+)L', text)
                        if wl_match:
                            wins = int(wl_match.group(1))
                            losses = int(wl_match.group(2))
            else:
                print("[Scraper] 'Ranked Solo' header not found.")

        response = {
            "name": name,
            "tag": tag,
            "tier": tier,
            "rank": rank,
            "lp": lp,
            "wins": wins,
            "losses": losses,
            "kda": kda,
            "avg_k": avg_k,
            "avg_d": avg_d,
            "avg_a": avg_a,
            "streak": streak,
            "ladder_rank": ladder_rank,
            "level": level,
            "ranked_flex": ranked_flex,
            "mastery": mastery,
            "past_rank": past_rank,
            "opgg_url": opgg_url,
            "top_champs": top_champs,
            "recent_games": recent_games
        }
        return jsonify(response)
        
    except Exception as err:
        import traceback
        print(f"[API] An unexpected error occurred: {err}")
        traceback.print_exc()
        return jsonify({"error": "Internal server error", "details": str(err)}), 500

if __name__ == '__main__':
    app.run(debug=True)
