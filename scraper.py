#!/usr/bin/env python3
"""
SBMSA 7u Midget scraper — fetches Skenes, Skubal, Yamamoto schedule pages
from teamsideline.com and writes standings.json for the dashboard.

Run locally:  python scraper.py
Runs in CI:   same command, triggered by GitHub Actions
"""

import json
import re
import sys
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup

# ── Division config ──────────────────────────────────────────────────────────
DIVISIONS = {
    "Skenes":   "https://www.teamsideline.com/sites/sbmsa/schedule/676203/7u-Midget-Skenes",
    "Skubal":   "https://www.teamsideline.com/sites/sbmsa/schedule/676201/7u-Midget-Skubal",
    "Yamamoto": "https://www.teamsideline.com/sites/sbmsa/schedule/676202/7u-Midget-Yamamoto",
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    )
}


# ── Helpers ──────────────────────────────────────────────────────────────────
def fetch(url: str) -> BeautifulSoup:
    resp = requests.get(url, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    return BeautifulSoup(resp.text, "html.parser")


def safe_int(s: str):
    """Return int or None for empty / non-numeric strings."""
    s = s.strip()
    return int(s) if s.lstrip("-").isdigit() else None


# ── Standings parser ─────────────────────────────────────────────────────────
def parse_standings(soup: BeautifulSoup) -> list[dict]:
    """
    Teamsideline standings tables look like:
      <table class="... standings ..."> <tbody> <tr> ...
    Each row: Rank | Team | W | L | T | PCT | GB | Streak | Coach
    Column order can vary; we detect by header text.
    """
    standings = []

    # Find the standings table — teamsideline uses a table with "standings" in
    # its id or class, or we fall back to the first sizeable table.
    table = None
    for t in soup.find_all("table"):
        tid = (t.get("id") or "").lower()
        tcls = " ".join(t.get("class") or []).lower()
        if "standing" in tid or "standing" in tcls:
            table = t
            break
    if table is None:
        # fallback: biggest table on page
        tables = soup.find_all("table")
        if tables:
            table = max(tables, key=lambda t: len(t.find_all("tr")))

    if table is None:
        print("  WARNING: no standings table found", file=sys.stderr)
        return standings

    # Read headers to map column indices
    headers = []
    header_row = table.find("thead")
    if header_row:
        headers = [th.get_text(strip=True).upper() for th in header_row.find_all(["th", "td"])]
    
    # Column index map with sensible defaults
    def col(name, default):
        try:
            return headers.index(name)
        except ValueError:
            return default

    # teamsideline typical order: Team(0) W(1) L(2) T(3) PCT(4) GB(5) Coach varies
    idx = {
        "team":   col("TEAM", 0),
        "w":      col("W", 1),
        "l":      col("L", 2),
        "t":      col("T", 3),
        "pct":    col("PCT", 4),
        "gb":     col("GB", 5),
        "streak": col("STREAK", 6),
        "coach":  col("COACH", -1),
    }

    rows = table.find("tbody")
    if rows is None:
        rows = table
    
    place = 0
    for tr in rows.find_all("tr"):
        cells = tr.find_all(["td", "th"])
        if len(cells) < 4:
            continue
        texts = [c.get_text(strip=True) for c in cells]
        
        # Skip header rows that snuck into tbody
        if texts[0].upper() in ("TEAM", "RANK", "#", ""):
            continue

        place += 1

        def g(key):
            i = idx[key]
            if i < 0 or i >= len(texts):
                return ""
            return texts[i]

        w = safe_int(g("w")) or 0
        l = safe_int(g("l")) or 0
        t = safe_int(g("t")) or 0
        gp = w + l + t
        pct = round(w / gp, 3) if gp > 0 else 0.0

        standings.append({
            "place":  place,
            "team":   g("team"),
            "w":      w,
            "l":      l,
            "t":      t,
            "gp":     gp,
            "pct":    f"{pct:.3f}",
            "gb":     g("gb") or "--",
            "streak": g("streak") or "",
            "coach":  g("coach") or "",
        })

    return standings


# ── Schedule / games parser ───────────────────────────────────────────────────
def parse_games(soup: BeautifulSoup) -> list[dict]:
    """
    Teamsideline schedule rows typically look like:
      Date | Time | Away Team | Away Score | Home Team | Home Score | Location
    We look for a <table> or <div> grid containing game rows.
    Scores are empty strings for future games.
    """
    games = []

    # Try schedule table first
    sched_table = None
    for t in soup.find_all("table"):
        tid = (t.get("id") or "").lower()
        tcls = " ".join(t.get("class") or []).lower()
        if "schedule" in tid or "schedule" in tcls or "game" in tid or "game" in tcls:
            sched_table = t
            break

    # If no labeled table, try the second table (first is usually standings)
    if sched_table is None:
        tables = soup.find_all("table")
        if len(tables) >= 2:
            sched_table = tables[1]
        elif len(tables) == 1:
            sched_table = tables[0]

    if sched_table is None:
        print("  WARNING: no schedule table found", file=sys.stderr)
        return games

    # Detect column mapping from header
    headers = []
    hrow = sched_table.find("thead")
    if hrow:
        headers = [th.get_text(strip=True).upper() for th in hrow.find_all(["th", "td"])]

    # teamsideline typical schedule columns:
    # Date | Time | Away | AwayScore | Home | HomeScore | Field/Location
    def col(name, default):
        for h in headers:
            if name in h:
                return headers.index(h)
        return default

    idx = {
        "date":       col("DATE", 0),
        "time":       col("TIME", 1),
        "away":       col("AWAY", 2),
        "away_score": col("ASCORE", 3),   # teamsideline uses "AScore" or "Away Score"
        "home":       col("HOME", 4),
        "home_score": col("HSCORE", 5),
        "field":      col("FIELD", 6),
    }

    # Also handle "VISITOR" label instead of "AWAY"
    if idx["away"] == 2 and "VISITOR" in headers:
        idx["away"] = headers.index("VISITOR")

    tbody = sched_table.find("tbody") or sched_table
    week = 0
    last_date = None

    for tr in tbody.find_all("tr"):
        cells = tr.find_all(["td", "th"])
        if len(cells) < 5:
            continue
        texts = [c.get_text(strip=True) for c in cells]

        # Skip header rows
        if texts[0].upper() in ("DATE", "WEEK", ""):
            continue

        def g(key):
            i = idx[key]
            if i < 0 or i >= len(texts):
                return ""
            return texts[i]

        date_str = g("date")
        if not date_str:
            continue

        # Crude week counter: increment when date changes to a later week
        if date_str != last_date:
            # Parse week number from date if possible; otherwise increment
            last_date = date_str
            # We'll just increment every ~3 unique dates as a rough heuristic
            # Real week grouping can be refined based on actual HTML structure
            week = week  # keep same; increment logic below

        away_score_raw = g("away_score").strip()
        home_score_raw = g("home_score").strip()
        away_score = safe_int(away_score_raw)
        home_score = safe_int(home_score_raw)

        games.append({
            "week":       _infer_week(date_str, games),
            "date":       date_str,
            "time":       g("time"),
            "away":       g("away"),
            "home":       g("home"),
            "awayScore":  away_score,
            "homeScore":  home_score,
            "field":      g("field"),
        })

    return games


def _infer_week(date_str: str, existing: list[dict]) -> int:
    """
    Assign a week number by grouping dates that are within 7 days of each other.
    Rough but works for a single-season schedule.
    """
    # Parse month/day from strings like "Mon 3/16", "Sat 4/25"
    match = re.search(r"(\d{1,2})/(\d{1,2})", date_str)
    if not match:
        return (existing[-1]["week"] if existing else 1)
    month, day = int(match.group(1)), int(match.group(2))
    # Use 2026 season
    try:
        d = datetime(2026, month, day)
    except ValueError:
        return (existing[-1]["week"] if existing else 1)

    if not existing:
        return 1

    # Find the earliest game date seen
    first = _date_of(existing[0]["date"])
    if first is None:
        return 1

    delta = (d - first).days
    return max(1, (delta // 7) + 1)


def _date_of(date_str: str):
    match = re.search(r"(\d{1,2})/(\d{1,2})", date_str)
    if not match:
        return None
    try:
        return datetime(2026, int(match.group(1)), int(match.group(2)))
    except ValueError:
        return None


# ── Main ──────────────────────────────────────────────────────────────────────
def scrape() -> dict:
    result = {}
    for div_name, url in DIVISIONS.items():
        print(f"Scraping {div_name}...")
        try:
            soup = fetch(url)
            standings = parse_standings(soup)
            games = parse_games(soup)
            print(f"  {len(standings)} teams, {len(games)} games")
            result[div_name] = {"standings": standings, "games": games}
        except Exception as e:
            print(f"  ERROR scraping {div_name}: {e}", file=sys.stderr)
            result[div_name] = {"standings": [], "games": [], "error": str(e)}

    return {
        "divisions": result,
        "updated": datetime.now(timezone.utc).isoformat(),
        "season": "Spring '26",
    }


if __name__ == "__main__":
    data = scrape()
    out = "standings.json"
    with open(out, "w") as f:
        json.dump(data, f, indent=2)
    print(f"\nWrote {out}")
