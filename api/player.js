import fetch from "node-fetch";

export default async function handler(req, res) {
  try {
    const { name, tag } = req.query;

    if (!name || !tag) {
      return res.status(400).json({ error: "Missing name or tag" });
    }

    const RIOT_API_KEY = process.env.RIOT_API_KEY;

    if (!RIOT_API_KEY) {
      return res.status(500).json({ error: "RIOT_API_KEY not configured" });
    }

    // 1) Obtener PUUID
    const accountRes = await fetch(
      `https://europe.api.riotgames.com/riot/account/v1/accounts/by-riot-id/${encodeURIComponent(
        name
      )}/${encodeURIComponent(tag)}`,
      {
        headers: { "X-Riot-Token": RIOT_API_KEY }
      }
    );

    if (!accountRes.ok) {
      return res.status(404).json({ error: "Summoner not found" });
    }

    const accountData = await accountRes.json();
    const puuid = accountData.puuid;

    // 2) Obtener summoner info
    const summonerRes = await fetch(
      `https://euw1.api.riotgames.com/lol/summoner/v4/summoners/by-puuid/${puuid}`,
      {
        headers: { "X-Riot-Token": RIOT_API_KEY }
      }
    );

    if (!summonerRes.ok) {
      return res.status(404).json({ error: "Summoner info not found" });
    }

    const summonerData = await summonerRes.json();

    // 3) Ranked
    const rankedRes = await fetch(
      `https://euw1.api.riotgames.com/lol/league/v4/entries/by-summoner/${summonerData.id}`,
      {
        headers: { "X-Riot-Token": RIOT_API_KEY }
      }
    );

    if (!rankedRes.ok) {
      return res.status(404).json({ error: "Ranked info not found" });
    }

    const rankedData = await rankedRes.json();
    const soloQ = rankedData.find(
      (q) => q.queueType === "RANKED_SOLO_5x5"
    );

    if (!soloQ) {
      return res.json({
        name,
        tag,
        tier: "UNRANKED",
        rank: "",
        lp: 0,
        wins: 0,
        losses: 0
      });
    }

    return res.json({
      name,
      tag,
      tier: soloQ.tier,
      rank: soloQ.rank,
      lp: soloQ.leaguePoints,
      wins: soloQ.wins,
      losses: soloQ.losses
    });

  } catch (err) {
    console.error(err);
    return res.status(500).json({ error: "Internal server error" });
  }
}
