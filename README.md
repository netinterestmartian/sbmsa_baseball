# 7U SBMSA Baseball Dashboard

Live standings, schedules, and power rankings for SBMSA 7U  — Skenes, Skubal, and Yamamoto divisions.

Data is scraped daily from sbmsa.net and committed automatically via GitHub Actions.

---

## Setup (step by step)

### 1. Create your GitHub account and repo

1. Go to [github.com](https://github.com) and sign up for a free account if you don't have one.
2. Click **New repository** (the green button on your dashboard).
3. Name it something like `7u-midget-baseball` — make sure it is set to **Public**.
4. Click **Create repository**.

---

### 2. Add the files to your repo

You need to upload four things:

| File | Where it goes in the repo |
|---|---|
| `index.html` | root of the repo |
| `standings.json` | root of the repo |
| `scraper.py` | root of the repo |
| `scrape.yml` | `.github/workflows/scrape.yml` |

**Easiest way (no command line needed):**

1. On your new repo page, click **Add file → Upload files**.
2. Drag in `index.html`, `standings.json`, and `scraper.py`.
3. Click **Commit changes**.
4. Now create the workflow folder: click **Add file → Create new file**.
5. In the filename box, type `.github/workflows/scrape.yml` — GitHub will auto-create the folders.
6. Paste the contents of `scrape.yml` into the editor.
7. Click **Commit changes**.

---

### 3. Enable GitHub Pages

1. In your repo, click **Settings** (top tab).
2. In the left sidebar, click **Pages**.
3. Under **Source**, choose **Deploy from a branch**.
4. Set branch to `main` and folder to `/ (root)`.
5. Click **Save**.
6. After ~60 seconds, your dashboard will be live at:
   `https://YOUR-USERNAME.github.io/7u-midget-baseball/`

---

### 4. Test the scraper manually

Before waiting for the scheduled run, trigger it yourself:

1. In your repo, click the **Actions** tab.
2. Click **Daily standings scrape** in the left sidebar.
3. Click **Run workflow → Run workflow**.
4. Wait ~30 seconds, then click the run to see logs.
5. If it succeeded, check your repo — `standings.json` should have a new commit.

---

### 5. You're done

The scraper runs automatically every day at 7 AM Central. When anyone opens your dashboard, it fetches the latest `standings.json` and renders fresh data.

---

## Troubleshooting

**The scraper ran but the data looks wrong / empty**

teamsideline.com occasionally changes its HTML structure. Open the Actions log (step 4 above), look for `WARNING` lines, and open an issue or ping whoever maintains the scraper.

**I want to change the scrape time**

Edit `.github/workflows/scrape.yml` and change the `cron` line. The format is `minute hour day month weekday` in UTC. For example:
- `0 13 * * *` = 8 AM Central (UTC−5 in winter, UTC−6 in summer)
- `0 5 * * *` = midnight Central
- `0 13 * * 0` = Sundays only

**The dashboard still shows old data after a scrape**

GitHub Pages has a CDN cache. Hard-refresh your browser (Ctrl+Shift+R / Cmd+Shift+R) or wait a few minutes.

---

## File overview

```
├── index.html              Dashboard (loads standings.json on page load)
├── standings.json          Data file written by the scraper
├── scraper.py              Python scraper (fetches + parses sbmsa.net)
└── .github/
    └── workflows/
        └── scrape.yml      GitHub Actions workflow (runs scraper daily)
```
