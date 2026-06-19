# 🦊 Fennec

> Zero-cost, ultra-premium daily tech news digest for software engineers.
> Runs fully serverless on GitHub. No hosting fees. No databases. No nonsense.

---

## How It Works

A Python script (`scrape.py`) runs once a day via GitHub Actions. It uses the **Google Gemini API** and **LangGraph** to:
1. Pull the past 24 hours of tech signals from Hacker News (top stories) and a curated set of RSS feeds
2. Filter and de-duplicate results, prioritise high-score HN stories, and cap the candidate pool
3. Ask the model to rank the candidate headlines and keep the top 10
4. Roast and classify each of the top items as **COOKING** 🔥 or **COOKED** 💀 and write them to `public/news.json`

A **Vite + React + TypeScript** frontend hosted on **GitHub Pages** reads `news.json` as a static file — no backend, no API, zero cost.

---

## Stack

| Layer | Technology |
|---|---|
| Frontend | Vite + React + TypeScript |
| Hosting | GitHub Pages (free) |
| Scraper | Python + Google Gemini 3.1 Flash Lite (via google-genai) |
| AI Orchestration | LangGraph |
| Data validation | Pydantic v2 |
| Automation | GitHub Actions |
| Cost | **$0/month** |

---

## Local Setup

### Prerequisites
- Node.js 18+
- Python 3.11+
- A [Gemini API key](https://aistudio.google.com/apikey) (free tier works)

### 1. Clone and install

```bash
git clone https://github.com/yourusername/fennec.git
cd fennec
./dev.sh --setup
```

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env and add your GEMINI_API_KEY
```

### 3. Run locally

```bash
# Scrape fresh news AND start dev server (recommended)
./dev.sh

# Skip scraping, use existing news.json
./dev.sh --skip

# Or via npm
npm run start    # scrape + dev server
npm run dev      # just dev server
npm run scrape   # just scraper
```

The app will be available at **http://localhost:5173**

---

## GitHub Setup

### 1. Enable GitHub Pages

Go to your repo → **Settings** → **Pages** → Source: **GitHub Actions**

### 2. Set the repo name in Vite config

Edit `vite.config.ts` and set `base` to your repo name:

```ts
base: "/your-repo-name/",
```

### 3. Add your Gemini API key as a secret

Go to **Settings** → **Secrets and variables** → **Actions** → **New repository secret**

```
Name:  GEMINI_API_KEY
Value: your_key_here
```

### 4. Push to main

Both workflows trigger automatically:
- `deploy.yml` → builds and deploys the frontend
- `scrape.yml` → runs daily at 13:00 UTC to refresh `news.json` (scheduled cron)

---

## Workflows

| Workflow | Trigger | What it does |
|---|---|---|
| `scrape.yml` | Daily cron (13:00 UTC) + manual | Runs `scrape.py`, commits new `news.json` to main |
| `deploy.yml` | Push to main | Builds Vite app, deploys to GitHub Pages |

When the scraper commits `news.json`, it triggers `deploy.yml` automatically — so the live site always reflects today's news within minutes.

To trigger a manual scrape: **Actions** → **Daily News Scraper** → **Run workflow**

---

## Customizing the Scraper

The scraper is intentionally opinionated. Edit `scrape.py` to change:

- **`MODEL`** — swap to `gemini-3.1-flash-lite`, `gemini-2.0-flash`, or `gemini-1.5-pro`
- **`fetch_signals` prompt** — change which topics/companies are included
- **`curate_and_format` prompt** — adjust the tone, wit level, or format
- **Cron schedule** in `scrape.yml` — change `0 7 * * *` to any time you want

---

## Project Structure

```
fennec/
├── .github/
│   └── workflows/
│       ├── scrape.yml      # Daily cron: runs scrape.py
│       └── deploy.yml      # On push: builds + deploys to Pages
├── public/
│   ├── favicon.svg
│   └── news.json           # Generated daily by scrape.py
├── src/
│   ├── components/
│   │   ├── Header.tsx
│   │   ├── SceneOverview.tsx
│   │   ├── Feed.tsx
│   │   └── NewsCard.tsx
│   ├── types/
│   │   └── news.ts
│   ├── App.tsx
│   ├── main.tsx
│   └── index.css
├── scrape.py               # Python scraper (LangGraph + Gemini)
├── requirements.txt
├── dev.sh                  # Local dev runner
├── index.html
├── package.json
├── vite.config.ts
└── tsconfig.json
```

---

## License

MIT — fork it, ship it, make it yours.
