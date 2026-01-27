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
        top_champs = []
        
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
                    # Separar por comas para tener una lista
                    top_champs = [c.strip() for c in raw_champs.split(',')]
            
            # Si encontramos la meta tag, usamos estos datos y saltamos el resto
            json_success = True 

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
            "opgg_url": opgg_url,
            "top_champs": top_champs
        }
        return jsonify(response)
        
    except Exception as err:
        import traceback
        print(f"[API] An unexpected error occurred: {err}")
        traceback.print_exc()
        return jsonify({"error": "Internal server error", "details": str(err)}), 500

if __name__ == '__main__':
    app.run(debug=True)
