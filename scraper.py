#!/usr/bin/env python3
"""
SBMSA 7u Midget scraper — fetches Skenes, Skubal, Yamamoto schedule pages
from teamsideline.com and writes standings.json.

Usage:
  python scraper.py            # normal run, writes standings.json
  python scraper.py --debug    # prints every table found + raw rows, no file write
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


def fetch(url):
    resp = requests.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    return BeautifulSoup(resp.text, "html.parser")


def safe_int(s):
    s = str(s).strip()
    return int(s) if re.fullmatch(r"-?\d+", s) else None


def debug_tables(soup, div_name):
    tables = soup.find_all("table")
    print(f"\n{'='*60}")
    print(f"DEBUG: {div_name} — {len(tables)} table(s) found on page")
    for i, tbl in enumerate(tables):
        tid = tbl.get("id", "")
        tcls = " ".join(tbl.get("class") or [])
        rows = tbl.find_all("tr")
        print(f"\n  Table #{i+1}  id='{tid}'  class='{tcls}'  rows={len(rows)}")
        for j, row in enumerate(rows[:6]):
            cells = [c.get_text(strip=True) for c in row.find_all(["th","td"])]
            print(f"    row {j}: {cells}")


DATE_RE  = re.compile(r"\b\d{1,2}/\d{1,2}\b|\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*\s+\d{1,2}\b", re.I)
TIME_RE  = re.compile(r"\b\d{1,2}:\d{2}\s*(?:AM|PM)\b", re.I)
SCORE_RE = re.compile(r"^\d{1,2}$")


def parse_standings(soup):
    standings = []

    table = None
    for tbl in soup.find_all("table"):
        tid  = (tbl.get("id") or "").lower()
        tcls = " ".join(tbl.get("class") or []).lower()
        if "standing" in tid or "standing" in tcls:
            table = tbl
            break

    if table is None:
        for tbl in soup.find_all("table"):
            hdrs = [th.get_text(strip=True).upper() for th in tbl.find_all("th")]
            if "W" in hdrs and "L" in hdrs:
                table = tbl
                break

    if table is None:
        print("  WARNING: no standings table found", file=sys.stderr)
        return standings

    header_row = table.find("tr")
    headers = [c.get_text(strip=True).upper() for c in header_row.find_all(["th","td"])] if header_row else []

    def colidx(names, default):
        for name in names:
            for i, h in enumerate(headers):
                if name in h:
                    return i
        return default

    idx = {
        "team":   colidx(["TEAM","NAME"], 0),
        "w":      colidx(["W"],    1),
        "l":      colidx(["L"],    2),
        "t":      colidx(["T"],    3),
        "pct":    colidx(["PCT","%"], 4),
        "gb":     colidx(["GB"],   5),
        "streak": colidx(["STR"],  6),
        "coach":  colidx(["COACH","MGR"], -1),
    }

    place = 0
    for row in table.find_all("tr"):
        cells = row.find_all(["td","th"])
        if len(cells) < 4:
            continue
        texts = [c.get_text(strip=True) for c in cells]
        if texts[idx["team"]].upper() in ("TEAM","NAME",""):
            continue
        if any(int(c.get("colspan",1)) > 3 for c in cells):
            continue

        place += 1

        def g(key):
            i = idx[key]
            return texts[i] if 0 <= i < len(texts) else ""

        w  = safe_int(g("w"))  or 0
        l  = safe_int(g("l"))  or 0
        t  = safe_int(g("t"))  or 0
        gp = w + l + t
        pct = round(w / gp, 3) if gp > 0 else 0.0

        standings.append({
            "place":  place,
            "team":   g("team"),
            "w":      w, "l": l, "t": t, "gp": gp,
            "pct":    f"{pct:.3f}",
            "gb":     g("gb") or "--",
            "streak": g("streak"),
            "coach":  g("coach"),
        })

    return standings


def parse_games(soup):
    games = []

    # Find the best schedule table
    candidates = []
    for tbl in soup.find_all("table"):
        tid  = (tbl.get("id") or "").lower()
        tcls = " ".join(tbl.get("class") or []).lower()
        rows = tbl.find_all("tr")
        if len(rows) < 3:
            continue
        score = 0
        if "schedule" in tid or "schedule" in tcls: score += 10
        if "game" in tid or "game" in tcls:         score += 10
        sample = " ".join(r.get_text(" ") for r in rows[:10])
        if DATE_RE.search(sample): score += 5
        if TIME_RE.search(sample): score += 3
        if score > 0:
            candidates.append((score, tbl))

    if not candidates:
        for tbl in soup.find_all("table"):
            if len(tbl.find_all("tr")) >= 5:
                candidates.append((1, tbl))

    if not candidates:
        print("  WARNING: no schedule table found", file=sys.stderr)
        return games

    candidates.sort(key=lambda x: -x[0])
    sched_table = candidates[0][1]

    header_row = sched_table.find("tr")
    headers = [c.get_text(strip=True).upper() for c in header_row.find_all(["th","td"])] if header_row else []

    if DEBUG:
        print(f"  [games] headers: {headers}")

    def colidx(names, default):
        for name in names:
            for i, h in enumerate(headers):
                if name in h:
                    return i
        return default

    idx = {
        "date":       colidx(["DATE","DAY"], 0),
        "time":       colidx(["TIME"], 1),
        "away":       colidx(["AWAY","VISITOR","VIS"], 2),
        "away_score": colidx(["ASCORE","AWAY SCORE","VIS SCORE","VISITOR SCORE","A SCORE"], -1),
        "home":       colidx(["HOME"], -1),
        "home_score": colidx(["HSCORE","HOME SCORE","H SCORE"], -1),
        "field":      colidx(["FIELD","LOCATION","LOC","VENUE","SITE"], -1),
    }

    if DEBUG:
        print(f"  [games] col map: {idx}")

    week_counter = 0
    last_date_str = None

    for row in sched_table.find_all("tr"):
        cells = row.find_all(["td","th"])
        if len(cells) < 3:
            continue
        texts = [c.get_text(strip=True) for c in cells]

        if not any(texts):
            continue
        if all(int(c.get("colspan",1)) > 2 for c in cells):
            continue

        # Find date
        date_str = ""
        if 0 <= idx["date"] < len(texts):
            date_str = texts[idx["date"]].strip()
        if not DATE_RE.search(date_str):
            for t in texts:
                if DATE_RE.search(t):
                    date_str = t.strip()
                    break
        if not date_str:
            continue

        if date_str != last_date_str:
            nw = _week_of(date_str)
            ow = _week_of(last_date_str) if last_date_str else None
            if nw and ow and nw > ow:
                week_counter = nw
            elif week_counter == 0:
                week_counter = 1
            last_date_str = date_str

        # Find time
        time_str = ""
        if 0 <= idx["time"] < len(texts):
            time_str = texts[idx["time"]].strip()
        if not TIME_RE.search(time_str):
            for t in texts:
                if TIME_RE.search(t):
                    time_str = t.strip()
                    break

        # Extract teams and scores
        away_team  = texts[idx["away"]]       if 0 <= idx["away"]       < len(texts) else ""
        home_team  = texts[idx["home"]]       if 0 <= idx["home"]       < len(texts) else ""
        away_score_raw = texts[idx["away_score"]] if 0 <= idx["away_score"] < len(texts) else ""
        home_score_raw = texts[idx["home_score"]] if 0 <= idx["home_score"] < len(texts) else ""

        # Fallback: infer from content cells if explicit columns missing
        if not home_team or not away_team:
            content = []
            for t in texts:
                t = t.strip()
                if not t: continue
                if t == date_str: continue
                if t == time_str: continue
                content.append(t)

            team_cells  = [c for c in content if not SCORE_RE.match(c)]
            score_cells = [c for c in content if SCORE_RE.match(c)]

            if len(team_cells) >= 2:
                away_team = team_cells[0]
                home_team = team_cells[1]
            if len(score_cells) >= 2:
                away_score_raw, home_score_raw = score_cells[0], score_cells[1]
            elif len(score_cells) == 1:
                m = re.match(r"(\d+)\s*[-–]\s*(\d+)", score_cells[0])
                if m:
                    away_score_raw, home_score_raw = m.group(1), m.group(2)

        # Field
        field = ""
        if 0 <= idx["field"] < len(texts):
            field = texts[idx["field"]].strip()
        if not field:
            for t in reversed(texts):
                t = t.strip()
                if t and not SCORE_RE.match(t) and t not in (away_team, home_team, date_str, time_str):
                    field = t
                    break

        if not away_team or not home_team:
            continue

        away_score = safe_int(away_score_raw)
        home_score = safe_int(home_score_raw)
        if (away_score is None) != (home_score is None):
            away_score = home_score = None

        games.append({
            "week": week_counter or 1,
            "date": date_str, "time": time_str,
            "away": away_team, "home": home_team,
            "awayScore": away_score, "homeScore": home_score,
            "field": field,
        })

    return games


def _week_of(date_str):
    if not date_str:
        return None
    m = re.search(r"(\d{1,2})/(\d{1,2})", date_str)
    if not m:
        return None
    try:
        d = datetime(2026, int(m.group(1)), int(m.group(2)))
        return max(1, (d - datetime(2026, 3, 16)).days // 7 + 1)
    except ValueError:
        return None


def scrape():
    result = {}
    for div_name, url in DIVISIONS.items():
        print(f"\nScraping {div_name}...")
        try:
            soup = fetch(url)
            if DEBUG:
                debug_tables(soup, div_name)
            standings = parse_standings(soup)
            games     = parse_games(soup)
            played    = [g for g in games if g["awayScore"] is not None]
            upcoming  = [g for g in games if g["awayScore"] is None]
            rf_total  = sum(g["awayScore"] + g["homeScore"] for g in played)
            print(f"  {len(standings)} teams | {len(played)} played ({rf_total} runs) | {len(upcoming)} upcoming")
            if DEBUG and played:
                print("  Sample played games:")
                for g in played[:4]:
                    print(f"    {g['date']} | {g['away']} {g['awayScore']} @ {g['home']} {g['homeScore']} | {g['field']}")
            result[div_name] = {"standings": standings, "games": games}
        except Exception as e:
            import traceback
            print(f"  ERROR: {e}", file=sys.stderr)
            if DEBUG: traceback.print_exc()
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
            print(f"  {div}: {len(d['standings'])} teams, {len(d['games'])} games, {len(played)} with scores")
        print("Not writing standings.json in --debug mode.")
        sys.exit(0)

    out = "standings.json"
    with open(out, "w") as f:
        json.dump(data, f, indent=2)
    print(f"\nWrote {out}")
    for div, d in data["divisions"].items():
        played = [g for g in d["games"] if g["awayScore"] is not None]
        if played:
            rf = sum(g["awayScore"] + g["homeScore"] for g in played)
            print(f"  {div}: {len(played)} games scored, {rf} total runs")
        else:
            print(f"  {div}: WARNING — no scored games found!")
