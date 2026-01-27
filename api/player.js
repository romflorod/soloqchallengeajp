import fetch from "node-fetch";

export default async function handler(req, res) {
  try {
    const { name, tag } = req.query;

    console.log(`[API] Request: name=${name}, tag=${tag}`);

    if (!name || !tag) {
      console.log("[API] Missing name or tag");
      return res.status(400).json({ error: "Missing name or tag" });
    }

    const RIOT_API_KEY = process.env.RIOT_API_KEY;

    if (!RIOT_API_KEY) {
      console.log("[API] RIOT_API_KEY not configured");
      return res.status(500).json({ error: "RIOT_API_KEY not configured" });
    }

    console.log("[API] API Key found, requesting account data...");

    // 1) Obtener PUUID
    const accountRes = await fetch(
      `https://europe.api.riotgames.com/riot/account/v1/accounts/by-riot-id/${encodeURIComponent(
        name
      )}/${encodeURIComponent(tag)}`,
      {
        headers: { "X-Riot-Token": RIOT_API_KEY }
      }
    );

    console.log(`[API] Account Response Status: ${accountRes.status}`);

    if (!accountRes.ok) {
      const errorData = await accountRes.text();
      console.log(`[API] Account API Error: ${errorData}`);
      return res.status(404).json({ error: "Summoner not found" });
    }

    const accountData = await accountRes.json();
    const puuid = accountData.puuid;
    console.log(`[API] PUUID obtained: ${puuid}`);

    // 2) Obtener summoner info
    const summonerRes = await fetch(
      `https://euw1.api.riotgames.com/lol/summoner/v4/summoners/by-puuid/${puuid}`,
      {
        headers: { "X-Riot-Token": RIOT_API_KEY }
      }
    );

    console.log(`[API] Summoner Response Status: ${summonerRes.status}`);

    if (!summonerRes.ok) {
      const errorData = await summonerRes.text();
      console.log(`[API] Summoner API Error: ${errorData}`);
      return res.status(404).json({ error: "Summoner info not found" });
    }

    const summonerData = await summonerRes.json();
    console.log(`[API] Summoner data obtained for ID: ${summonerData.id}`);

    // 3) Ranked
    const rankedRes = await fetch(
      `https://euw1.api.riotgames.com/lol/league/v4/entries/by-summoner/${summonerData.id}`,
      {
        headers: { "X-Riot-Token": RIOT_API_KEY }
      }
    );

    console.log(`[API] Ranked Response Status: ${rankedRes.status}`);

    if (!rankedRes.ok) {
      const errorData = await rankedRes.text();
      console.log(`[API] Ranked API Error: ${errorData}`);
      return res.status(404).json({ error: "Ranked info not found" });
    }

    const rankedData = await rankedRes.json();
    const soloQ = rankedData.find(
      (q) => q.queueType === "RANKED_SOLO_5x5"
    );

    console.log(`[API] SoloQ found: ${soloQ ? "Yes" : "No"}`);

    if (!soloQ) {
      const response = {
        name,
        tag,
        tier: "UNRANKED",
        rank: "",
        lp: 0,
        wins: 0,
        losses: 0
      };
      console.log("[API] Returning UNRANKED response:", response);
      return res.json(response);
    }

    const response = {
      name,
      tag,
      tier: soloQ.tier,
      rank: soloQ.rank,
      lp: soloQ.leaguePoints,
      wins: soloQ.wins,
      losses: soloQ.losses
    };
    console.log("[API] Returning ranked response:", response);
    return res.json(response);

  } catch (err) {
    console.error("[API] Error:", err);
    return res.status(500).json({ error: "Internal server error", details: err.message });
  }
}
