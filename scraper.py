#!/usr/bin/env python3
"""
SBMSA 7u Midget scraper — fetches Skenes, Skubal, Yamamoto schedule pages
from teamsideline.com and writes standings.json.

Usage:
  python scraper.py            # normal run, writes standings.json
  python scraper.py --debug    # verbose output, no file write
"""

import json
import re
import sys
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup

DEBUG = "--debug" in sys.argv

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
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}

# Teamsideline appends the score directly to the team name, e.g. "Oakland A's16"
# This regex splits "TeamName<digits>" into (name, score) or (name, None)
TEAM_SCORE_RE = re.compile(r"^(.*?)(\d+)$")


def fetch(url):
    resp = requests.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    return BeautifulSoup(resp.text, "html.parser")


def split_team_score(cell_text):
    """
    Teamsideline concatenates score onto team name: 'Oakland A's16' -> ('Oakland A's', 16)
    If no trailing digits, score is None (game not yet played).
    """
    cell_text = cell_text.strip()
    m = TEAM_SCORE_RE.match(cell_text)
    if m:
        name  = m.group(1).strip()
        score = int(m.group(2))
        return name, score
    return cell_text, None


def parse_standings(soup):
    """
    Table #2: id contains 'standingsGrid' (not 'MobileStandingsGrid').
    Columns: Place | Team | W | L | T | GB | GP | PCT | Streak | Coach
    """
    standings = []

    table = None
    for tbl in soup.find_all("table"):
        tid = tbl.get("id", "")
        # Use the desktop standings grid, skip the mobile duplicate
        if "standingsGrid" in tid and "Mobile" not in tid:
            table = tbl
            break

    if table is None:
        # Fallback: any table whose headers include W, L, T, PCT
        for tbl in soup.find_all("table"):
            hdrs = [th.get_text(strip=True).upper() for th in tbl.find_all("th")]
            if {"W", "L", "PCT"}.issubset(set(hdrs)):
                table = tbl
                break

    if table is None:
        print(f"  WARNING: standings table not found", file=sys.stderr)
        return standings

    rows = table.find_all("tr")
    if not rows:
        return standings

    # Map headers to column indices
    header_cells = [c.get_text(strip=True).upper() for c in rows[0].find_all(["th", "td"])]
    if DEBUG:
        print(f"  [standings] headers: {header_cells}")

    def ci(name, default):
        try:
            return header_cells.index(name)
        except ValueError:
            return default

    col = {
        "place":  ci("PLACE", 0),
        "team":   ci("TEAM",  1),
        "w":      ci("W",     2),
        "l":      ci("L",     3),
        "t":      ci("T",     4),
        "gb":     ci("GB",    5),
        "gp":     ci("GP",    6),
        "pct":    ci("PCT",   7),
        "streak": ci("STREAK",8),
        "coach":  ci("COACH", 9),
    }

    for row in rows[1:]:   # skip header row
        cells = [c.get_text(strip=True) for c in row.find_all(["td", "th"])]
        if len(cells) < 5:
            continue

        def g(key):
            i = col[key]
            return cells[i] if 0 <= i < len(cells) else ""

        try:
            place = int(g("place"))
        except ValueError:
            continue  # not a data row

        w  = int(g("w")  or 0)
        l  = int(g("l")  or 0)
        t  = int(g("t")  or 0)
        gp_raw = g("gp")
        gp = int(gp_raw) if gp_raw.isdigit() else w + l + t
        pct_raw = g("pct")
        # Use the site's PCT directly; fall back to computing it
        try:
            pct = float(pct_raw)
        except ValueError:
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
            "streak": g("streak"),
            "coach":  g("coach"),
        })

    if DEBUG:
        print(f"  [standings] parsed {len(standings)} teams")

    return standings


def parse_games(soup):
    """
    Table #3: id contains 'ScheduleGrid' (not 'MobileScheduleGrid').
    Columns: Date | Time | Away | Home | Location
    Scores are embedded in the Away/Home cell text: 'TeamName<score>'
    Week headers appear as single-cell rows: ['Week 1'], ['Week 2'], etc.
    """
    games = []

    table = None
    for tbl in soup.find_all("table"):
        tid = tbl.get("id", "")
        if "ScheduleGrid" in tid and "Mobile" not in tid:
            table = tbl
            break

    if table is None:
        # Fallback: table with Date/Time/Away/Home headers
        for tbl in soup.find_all("table"):
            hdrs = [c.get_text(strip=True).upper() for c in tbl.find_all("th")]
            if "AWAY" in hdrs and "HOME" in hdrs:
                table = tbl
                break

    if table is None:
        print(f"  WARNING: schedule table not found", file=sys.stderr)
        return games

    rows = table.find_all("tr")
    if not rows:
        return games

    header_cells = [c.get_text(strip=True).upper() for c in rows[0].find_all(["th", "td"])]
    if DEBUG:
        print(f"  [games] headers: {header_cells}")

    def ci(name, default):
        try:
            return header_cells.index(name)
        except ValueError:
            return default

    col = {
        "date":  ci("DATE",     0),
        "time":  ci("TIME",     1),
        "away":  ci("AWAY",     2),
        "home":  ci("HOME",     3),
        "field": ci("LOCATION", 4),
    }

    current_week = 1

    for row in rows[1:]:   # skip header row
        cells = row.find_all(["td", "th"])
        texts = [c.get_text(strip=True) for c in cells]

        if not any(texts):
            continue

        # Week header row — single cell like "Week 1", "Week 2"
        if len(texts) == 1 or (len(texts) > 0 and re.match(r"^Week\s+(\d+)$", texts[0], re.I)):
            m = re.search(r"\d+", texts[0])
            if m:
                current_week = int(m.group())
                if DEBUG:
                    print(f"  [games] week marker: {texts[0]}")
            continue

        # Need at least date + away + home
        if len(texts) < 3:
            continue

        def g(key):
            i = col[key]
            return texts[i].strip() if 0 <= i < len(texts) else ""

        date_str  = g("date")
        time_str  = g("time")
        away_raw  = g("away")
        home_raw  = g("home")
        field_str = g("field")

        # Skip if no date (probably a spacer row)
        if not date_str:
            continue

        away_team, away_score = split_team_score(away_raw)
        home_team, home_score = split_team_score(home_raw)

        # Both scores must be present or neither (no half-scored games)
        if (away_score is None) != (home_score is None):
            away_score = home_score = None

        if DEBUG:
            print(f"  {date_str} | {time_str} | {away_team!r} {away_score} @ {home_team!r} {home_score} | {field_str}")

        if not away_team or not home_team:
            continue

        games.append({
            "week":       current_week,
            "date":       date_str,
            "time":       time_str,
            "away":       away_team,
            "home":       home_team,
            "awayScore":  away_score,
            "homeScore":  home_score,
            "field":      field_str,
        })

    return games


def scrape():
    result = {}
    for div_name, url in DIVISIONS.items():
        print(f"\nScraping {div_name}...")
        try:
            soup      = fetch(url)
            standings = parse_standings(soup)
            games     = parse_games(soup)
            played    = [g for g in games if g["awayScore"] is not None]
            upcoming  = [g for g in games if g["awayScore"] is None]
            rf_total  = sum(g["awayScore"] + g["homeScore"] for g in played)

            print(f"  {len(standings)} teams | {len(played)} played ({rf_total} total runs) | {len(upcoming)} upcoming")

            if played:
                print(f"  Sample: {played[0]['away']} {played[0]['awayScore']} @ "
                      f"{played[0]['home']} {played[0]['homeScore']}  ({played[0]['date']})")

            result[div_name] = {"standings": standings, "games": games}

        except Exception as e:
            import traceback
            print(f"  ERROR: {e}", file=sys.stderr)
            if DEBUG:
                traceback.print_exc()
            result[div_name] = {"standings": [], "games": [], "error": str(e)}

    return {
        "divisions": result,
        "updated":   datetime.now(timezone.utc).isoformat(),
        "season":    "Spring '26",
    }


if __name__ == "__main__":
    data = scrape()

    if DEBUG:
        print("\n=== SUMMARY ===")
        for div, d in data["divisions"].items():
            played = [g for g in d["games"] if g["awayScore"] is not None]
            rf = sum(g["awayScore"] + g["homeScore"] for g in played)
            print(f"  {div}: {len(d['standings'])} teams | {len(played)} scored games | {rf} total runs")
        print("\nNot writing standings.json in --debug mode.")
        sys.exit(0)

    out = "standings.json"
    with open(out, "w") as f:
        json.dump(data, f, indent=2)
    print(f"\nWrote {out}")

    for div, d in data["divisions"].items():
        played = [g for g in d["games"] if g["awayScore"] is not None]
        if played:
            rf = sum(g["awayScore"] + g["homeScore"] for g in played)
            print(f"  {div}: {len(played)} scored games | {rf} total runs")
        else:
            print(f"  {div}: WARNING — no scored games found!")
