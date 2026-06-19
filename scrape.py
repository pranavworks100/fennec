"""
Fennec scraper — runs once daily via GitHub Actions at 13:00 UTC.
Pulls the past 24 hours of tech news from HN + RSS, ranks top 10,
roasts and classifies, writes public/news.json.

Pipeline:
  Stage 0 — fetch_signals:      HN top stories (score-ranked) + RSS from 4 curated feeds
                                  filtered to past 24 hours only
  Stage 1 — rank_headlines:     send all headlines to AI, get back top 10 by importance
  Stage 2 — roast_and_classify: send top 10 full articles to AI in batches, roast + classify
  Stage 3 — summarize_scene:    write scene_summary, compute ratio_statement in Python
  Stage 4 — write_output:       serialize to public/news.json

Requirements:
  pip install google-genai langgraph pydantic requests python-dotenv feedparser

Set env vars:
  GEMINI_API_KEY=your_key_here
"""

import json
import time
import os
import re
import feedparser
from datetime import datetime, timezone, timedelta
from typing import Annotated, Any
from urllib.parse import urlparse

import requests
from dotenv import load_dotenv
from pydantic import BaseModel, Field, field_validator
from langgraph.graph import StateGraph, END
from langgraph.types import RetryPolicy
from langgraph.graph.message import add_messages
from google import genai
from google.genai import types
from google.genai import errors as genai_errors

load_dotenv()

# ── CONFIG ──────────────────────────────────────────────────
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
MODEL           = "gemini-3.1-flash-lite"
OUTPUT_PATH     = os.path.join(os.path.dirname(__file__), "public", "news.json")

# Past N hours to consider — we run at 13:00 UTC so 24h = full previous day
LOOKBACK_HOURS  = 24

# How many HN stories to inspect (top N by HN rank before score filter)
HN_CANDIDATE_LIMIT = 60

# Minimum HN score to be considered worth reading
HN_MIN_SCORE    = 15

# How many total candidates we send to the ranker
RANK_POOL_SIZE  = 50

# Final top N after ranking
TOP_N           = 10

# Batch size for roast stage
ROAST_BATCH_SIZE = 2

# RSS feeds — curated high-signal tech sources
RSS_FEEDS = [
    # ── News sources ─────────────────────────────
    "https://techcrunch.com/feed/",
    "https://www.theverge.com/rss/index.xml",
    "https://feeds.arstechnica.com/arstechnica/technology-lab",
    "https://www.wired.com/feed/rss",
    "https://hnrss.org/frontpage?points=15",

    # ── Company blogs (high signal only) ─────────
    "https://openai.com/blog/rss.xml",
    "https://anthropic.com/rss.xml",
    "https://blog.google/technology/ai/rss/",
    "https://engineering.fb.com/feed/",
    "https://blogs.microsoft.com/blog/feed/",
    "https://aws.amazon.com/blogs/aws/feed/",
    "https://developer.apple.com/news/rss/news.rss",
    "https://huggingface.co/blog/feed.xml",
    "https://mistral.ai/news/rss",
    "https://nvidia.com/en-us/about-nvidia/blogs/rss/",
]

client = genai.Client(api_key=GEMINI_API_KEY)


# ── HELPERS ──────────────────────────────────────────────────
def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def parse_dt(s: str | None) -> datetime | None:
    """Parse ISO-8601 or RFC-2822 datetime strings into UTC-aware datetime."""
    if not s:
        return None
    for fmt in (
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S%z",
        "%a, %d %b %Y %H:%M:%S %z",
        "%a, %d %b %Y %H:%M:%S GMT",
    ):
        try:
            dt = datetime.strptime(s, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            continue
    return None


def is_within_hours(dt: datetime | None, hours: int) -> bool:
    if dt is None:
        return True  # include if we can't determine age
    cutoff = utc_now() - timedelta(hours=hours)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt >= cutoff


def clean_domain(v: str) -> str:
    if v.startswith("http"):
        parsed = urlparse(v)
        v = parsed.netloc or v
    return v.lstrip("www.").strip().lower()


def generate_with_retries(max_attempts: int = 5, backoff_base: int = 2, **kwargs):
    for attempt in range(1, max_attempts + 1):
        try:
            return client.models.generate_content(**kwargs)
        except genai_errors.ServerError as e:
            print(f"   ⚠️  ServerError attempt {attempt}/{max_attempts}: {e}")
            if attempt == max_attempts:
                raise
            time.sleep(backoff_base ** (attempt - 1))
        except genai_errors.ClientError as e:
            print(f"   ⚠️  ClientError attempt {attempt}/{max_attempts}: {e}")
            retry_delay = None
            try:
                m = re.search(r"(\d+)s", str(e))
                if m:
                    retry_delay = int(m.group(1))
            except Exception:
                pass
            if retry_delay is None:
                retry_delay = max(5, backoff_base ** attempt)
            if attempt == max_attempts:
                raise
            print(f"      → retrying in {retry_delay}s...")
            time.sleep(retry_delay)
        except Exception:
            raise


def safe_json_loads(raw_text: str) -> Any:
    if not raw_text:
        raise ValueError("Empty response from model")
    s = re.sub(r"```(?:json)?\s*", "", raw_text).strip().rstrip("`").strip()
    s = s.replace('\u201c', '"').replace('\u201d', '"').replace('\u2018', "'").replace('\u2019', "'")
    try:
        return json.loads(s)
    except Exception:
        pass
    # find first balanced JSON block
    for i, ch in enumerate(s):
        if ch in '{[':
            open_ch, close_ch = ch, ('}' if ch == '{' else ']')
            depth = 0
            for j in range(i, len(s)):
                if s[j] == open_ch:
                    depth += 1
                elif s[j] == close_ch:
                    depth -= 1
                    if depth == 0:
                        block = s[i:j + 1]
                        block = re.sub(r",\s*([}\]])", r"\1", block)
                        try:
                            return json.loads(block)
                        except Exception:
                            pass
    raise ValueError(f"Could not parse JSON from model output: {s[:200]}")


def _ensure_two_sentences(text: str) -> str:
    text = (text or "").strip()
    sentences = [p.strip() for p in re.split(r"(?<=[.!?])\s+", text) if p.strip()]
    if len(sentences) >= 2:
        return " ".join(sentences[:2])
    if len(sentences) == 1:
        parts = re.split(r"[;\-]\s*", text)
        if len(parts) >= 2:
            s1 = parts[0].strip().rstrip(".") + "."
            s2 = parts[1].strip().rstrip(".") + "."
            return f"{s1} {s2}"
    if not text.endswith((".", "!", "?")):
        text += "."
    return f"{text} More details in the original article."


def normalize_roasted_batch(data: dict) -> dict:
    items = data.get("items") if isinstance(data, dict) else None
    if items is None and isinstance(data, list):
        items = data
    if not isinstance(items, list):
        raise ValueError("No items list found in roasted batch")
    repaired = []
    for itm in items:
        if not isinstance(itm, dict):
            continue
        verdict = (itm.get("verdict") or "").strip().lower()
        verdict = "cooking" if "cook" in verdict and "cooked" not in verdict else "cooked"
        plain = (itm.get("plain_english") or "").strip()
        plain_sents = [p.strip() for p in re.split(r"(?<=[.!?])\s+", plain) if p.strip()]
        plain = plain_sents[0] if plain_sents else plain
        summary = _ensure_two_sentences(itm.get("summary") or plain)
        repaired.append({
            "id":            itm.get("id"),
            "verdict":       verdict,
            "domain":        itm.get("domain") or "",
            "headline":      (itm.get("headline") or "").strip(),
            "summary":       summary,
            "plain_english": plain,
        })
    return {"items": repaired}


# ── PYDANTIC SCHEMAS ─────────────────────────────────────────
class NewsItem(BaseModel):
    id:            int
    domain:        str
    headline:      str
    summary:       str
    plain_english: str
    source_url:    str

    @field_validator("domain")
    @classmethod
    def _domain(cls, v: str) -> str:
        return clean_domain(v)

    @field_validator("summary")
    @classmethod
    def _two(cls, v: str) -> str:
        sents = [s.strip() for s in re.split(r"(?<=[.!?])\s+", v.strip()) if s.strip()]
        if len(sents) < 2:
            raise ValueError("summary must have 2 sentences")
        return " ".join(sents[:2])

    @field_validator("plain_english")
    @classmethod
    def _one(cls, v: str) -> str:
        sents = [s.strip() for s in re.split(r"(?<=[.!?])\s+", v.strip()) if s.strip()]
        return sents[0] if sents else v


class NewsOutput(BaseModel):
    scene_summary:    str
    ratio_statement:  str
    cooking:          list[NewsItem]
    cooked:           list[NewsItem]

    def total(self) -> int:
        return len(self.cooking) + len(self.cooked)


class RankedHeadlines(BaseModel):
    ranked_ids: list[int]


class RoastedItem(BaseModel):
    id:            int
    verdict:       str
    domain:        str
    headline:      str
    summary:       str
    plain_english: str

    @field_validator("verdict")
    @classmethod
    def _verdict(cls, v: str) -> str:
        v = v.strip().lower()
        if v not in ("cooking", "cooked"):
            raise ValueError(f"verdict must be cooking or cooked, got {v!r}")
        return v

    @field_validator("domain")
    @classmethod
    def _domain(cls, v: str) -> str:
        return clean_domain(v)

    @field_validator("summary")
    @classmethod
    def _two(cls, v: str) -> str:
        sents = [s.strip() for s in re.split(r"(?<=[.!?])\s+", v.strip()) if s.strip()]
        if len(sents) < 2:
            raise ValueError("summary must have 2 sentences")
        return " ".join(sents[:2])

    @field_validator("plain_english")
    @classmethod
    def _one(cls, v: str) -> str:
        sents = [s.strip() for s in re.split(r"(?<=[.!?])\s+", v.strip()) if s.strip()]
        return sents[0] if sents else v


class RoastedBatch(BaseModel):
    items: list[RoastedItem]


class SceneSummaryOutput(BaseModel):
    scene_summary: str


# ── LANGGRAPH STATE ──────────────────────────────────────────
class AgentState(BaseModel):
    model_config = {"arbitrary_types_allowed": True}
    messages:      Annotated[list[Any], add_messages] = Field(default_factory=list)
    candidates:    list[dict] = Field(default_factory=list)
    top_articles:  list[dict] = Field(default_factory=list)
    roasted_items: list[dict] = Field(default_factory=list)
    news_output:   NewsOutput | None = None
    error:         str = ""


# ── STAGE 0: FETCH ───────────────────────────────────────────
def fetch_signals(state: AgentState) -> AgentState:
    """Pull past 24h tech news from HN API + curated RSS feeds."""
    print("🔍 Fetching past 24h tech signals from HN + RSS...")
    candidates: list[dict] = []
    seen_urls: set[str] = set()
    article_id = 1

    # ── A. Hacker News API ──────────────────────────────────
    print("   → HN API...")
    try:
        hn_resp = requests.get(
            "https://hn.algolia.com/api/v1/search",
            params={
                "tags": "story",
                "numericFilters": [
                    f"created_at_i>{int((datetime.now(timezone.utc) - timedelta(hours=LOOKBACK_HOURS)).timestamp())}",
                    f"points>{HN_MIN_SCORE}",
                ],
                "hitsPerPage": HN_CANDIDATE_LIMIT,
            },
            timeout=10,
        )
        hn_resp.raise_for_status()
        hits = hn_resp.json().get("hits", [])

        hn_stories = []
        for hit in hits:
            url = hit.get("url") or f"https://news.ycombinator.com/item?id={hit.get('objectID')}"
            if url in seen_urls:
                continue
            seen_urls.add(url)
            pub_dt = datetime.fromtimestamp(hit["created_at_i"], tz=timezone.utc)
            hn_stories.append({
                "id":          article_id,
                "title":       hit.get("title", ""),
                "description": "",
                "source":      "Hacker News",
                "url":         url,
                "publishedAt": pub_dt.isoformat(),
                "hn_score":    hit.get("points", 0),
            })
            article_id += 1

        hn_stories.sort(key=lambda x: x["hn_score"], reverse=True)
        candidates.extend(hn_stories)
        print(f"      ✓ {len(hn_stories)} HN stories (score >= {HN_MIN_SCORE}, past {LOOKBACK_HOURS}h)")
    except Exception as e:
        print(f"      ✗ HN fetch failed: {e}")

    # ── B. RSS Feeds ────────────────────────────────────────
    print("   → RSS feeds...")
    rss_count = 0
    for feed_url in RSS_FEEDS:
        try:
            feed = feedparser.parse(feed_url)
            for entry in feed.entries:
                url = entry.get("link") or ""
                if not url or url in seen_urls:
                    continue

                # Parse published date
                pub_str = (
                    entry.get("published")
                    or entry.get("updated")
                    or entry.get("dc_date")
                )
                pub_dt = parse_dt(pub_str)

                # Use struct_time from feedparser if string parse failed
                if pub_dt is None and hasattr(entry, "published_parsed") and entry.published_parsed:
                    try:
                        import calendar
                        ts = calendar.timegm(entry.published_parsed)
                        pub_dt = datetime.fromtimestamp(ts, tz=timezone.utc)
                    except Exception:
                        pass

                if not is_within_hours(pub_dt, LOOKBACK_HOURS):
                    continue

                title = entry.get("title", "").strip()
                if not title:
                    continue

                description = (
                    entry.get("summary")
                    or entry.get("description")
                    or ""
                )
                # Strip HTML tags from description
                description = re.sub(r"<[^>]+>", "", description)[:600].strip()

                seen_urls.add(url)
                candidates.append({
                    "id":          article_id,
                    "title":       title,
                    "description": description,
                    "source":      feed.feed.get("title", feed_url),
                    "url":         url,
                    "publishedAt": pub_dt.isoformat() if pub_dt else None,
                    "hn_score":    0,
                })
                article_id += 1
                rss_count += 1
        except Exception as e:
            print(f"      ✗ RSS feed failed ({feed_url}): {e}")
            continue

    print(f"      ✓ {rss_count} RSS articles (past {LOOKBACK_HOURS}h)")

    # Cap pool size — HN stories (already score-sorted) come first
    candidates = candidates[:RANK_POOL_SIZE]
    print(f"   ✓ Total candidate pool: {len(candidates)} articles → sending to ranker")

    return AgentState(**{**state.model_dump(), "candidates": candidates})


# ── STAGE 1: RANK ────────────────────────────────────────────
def rank_headlines(state: AgentState) -> AgentState:
    """Send ONLY headlines + source to AI. Get back top TOP_N by importance."""
    print(f"🏆 Ranking {len(state.candidates)} headlines → top {TOP_N}...")

    if not state.candidates:
        return AgentState(**{**state.model_dump(), "error": "No candidates to rank."})

    headlines_only = [
        {"id": c["id"], "title": c["title"], "source": c["source"]}
        for c in state.candidates
    ]

    schema = RankedHeadlines.model_json_schema()

    prompt = f"""You are a senior tech editor ranking today's headlines for a daily digest
read by software engineers, founders, and people who follow tech closely.

Your ONLY job right now is to rank these headlines by IMPORTANCE.

Definition of important:
- Affects a large number of developers, companies, or users
- Major product launches, acquisitions, shutdowns, funding rounds, security incidents
- Shifts in AI, cloud, open-source, chips, or developer tooling
- Stories that will still matter in a week

NOT important:
- Opinion pieces, tutorials, how-to guides
- Minor product updates or changelog posts
- Anything that is essentially an ad or press release
- Niche stories with very limited audience

Headlines from the past 24 hours:
---
{json.dumps(headlines_only, indent=2, ensure_ascii=False)}
---

Return the IDs of the top {TOP_N} most important headlines, ordered from
most important to least important.

Do NOT write any jokes, summaries, or classifications.
Just rank and return the top {TOP_N} IDs.

Respond ONLY with valid JSON:
{json.dumps(schema, indent=2)}
"""

    response = generate_with_retries(
        model=MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=0.2,
            response_mime_type="application/json",
        ),
    )

    try:
        data = safe_json_loads(response.text or "")
        if isinstance(data, list):
            data = {"ranked_ids": data}
        data["ranked_ids"] = [int(x) for x in data.get("ranked_ids", [])]
        ranked = RankedHeadlines(**data)
    except Exception as e:
        print(f"   ✗ Ranking parse error: {e}")
        return AgentState(**{**state.model_dump(), "error": str(e)})

    by_id = {c["id"]: c for c in state.candidates}
    top_ids = ranked.ranked_ids[:TOP_N]
    top_articles = [by_id[i] for i in top_ids if i in by_id]

    if not top_articles:
        return AgentState(**{**state.model_dump(), "error": "Ranking returned no valid IDs."})

    print(f"   ✓ Top {len(top_articles)} selected. Discarding the rest.")
    for a in top_articles:
        print(f"      #{a['id']} — {a['title'][:80]}")

    return AgentState(**{**state.model_dump(), "top_articles": top_articles})


# ── STAGE 2: ROAST & CLASSIFY ────────────────────────────────
def roast_and_classify(state: AgentState) -> AgentState:
    """Roast and classify top articles in batches."""
    print(f"✍️  Roasting {len(state.top_articles)} articles in batches of {ROAST_BATCH_SIZE}...")

    articles  = state.top_articles
    schema    = RoastedBatch.model_json_schema()
    roasted: list[dict] = []
    batches   = [articles[i:i + ROAST_BATCH_SIZE] for i in range(0, len(articles), ROAST_BATCH_SIZE)]

    for batch_num, batch in enumerate(batches, start=1):
        print(f"   → Batch {batch_num}/{len(batches)} ({len(batch)} articles)...")

        prompt = f"""You are the editor of Fennec, a daily tech digest for developers.

Your job is to explain tech news in a way that is genuinely fun to read.

Fennec sounds like the smartest and funniest developer in a Discord server explaining what happened today.

The goal:
1. Find the most interesting thing about the story.
2. Find the most absurd, ironic, or funny part of that reality.
3. Build the joke around that ONE thing.
4. Help the reader understand the news while entertaining them.

Humor must come FROM the news. Do not invent random absurdity.

---

RAW ARTICLES:
{json.dumps(batch, indent=2, ensure_ascii=False)}

---

TASK: For each article produce:

VERDICT: "cooking" = gaining momentum / exciting / important. "cooked" = failing / embarrassing / declining.

HEADLINE: Smart observation, under 120 chars. Makes a developer smile immediately.
Good: "ChatGPT can now nag you on a schedule"
Good: "Rebranding to AI is the new .io domain"
Bad: "The AI Singularity Enters Its Villain Arc"

SUMMARY: EXACTLY 2 SENTENCES.
- Sentence 1: set up the irony, contradiction, or interesting observation
- Sentence 2: ONE punchline or developer observation
Must feel conversational. NOT a press release. NOT a meme. NOT word salad.

Good summary:
"OpenAI built scheduled reminders, which means your procrastination now has API access. The feature works great unless you were already ignoring your calendar."

Bad summary:
"Technical debt has reached orbital altitudes powered by hallucinations and vibes."

PLAIN_ENGLISH: EXACTLY 1 SENTENCE. No humor, no slang, no opinions. Clinical and clear. A non-technical person should understand it.

DOMAIN: Base domain of the COMPANY THE STORY IS ABOUT, NOT the publisher.
- CNBC reports on Tesla → tesla.com
- TechCrunch reports on OpenAI → openai.com
- Ars Technica reports on Intel → intel.com

---

HUMOR & RELATABILITY RULE

The best Fennec jokes should be understandable by:

* software engineers
* students learning programming
* founders
* tech enthusiasts

A reader should get the joke instantly without needing niche technical knowledge.

Prefer analogies from everyday life:

* group projects
* school
* exams
* meetings
* deadlines
* subscriptions
* customer support
* landlords
* airports
* traffic
* bureaucracy
* shopping
* sports

Use light internet-native language naturally when it fits:

* cooked
* cooking
* side quest
* plot twist
* vibe check
* somehow
* of course
* speedrun
* main character energy

Use these sparingly.

If every story contains slang, the writing becomes exhausting.

The joke should come from the situation itself, not from slang.

Good:

"OpenAI gave procrastination API access."

"Being the best AI model in the world currently has the shelf life of milk."

"Giving five AI agents a task feels like assigning a group project and hoping someone actually does the work."

"Meta is buying enough electricity to make your utility bill feel personally attacked."

"The feature passed the vibe check. The infrastructure didn't."

Bad:

"CUDA memory fragmentation has entered its villain arc."

"The AI singularity is speedrunning its main character arc."

"Hypergrowth has reached orbital vibes."

"Kubernetes operators are basically recursive control loops with a SaaS business model."

The goal is to sound like a smart developer making an observation, not a meme account trying to win a reply section.

When in doubt:
Observation > Joke
Joke > Slang
Slang is optional.


Preserve original id for each item.

Return ONLY valid JSON matching this schema:
{json.dumps(schema, indent=2)}
"""

        max_retries = 3
        success = False
        last_error = None

        for attempt in range(1, max_retries + 1):
            response = generate_with_retries(
                model=MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0.7,
                    response_mime_type="application/json",
                ),
            )
            try:
                data = safe_json_loads(response.text or "")
                if isinstance(data, list):
                    data = {"items": data}
                if not isinstance(data, dict) or "items" not in data:
                    raise ValueError("Expected object with 'items' key")
                data = normalize_roasted_batch(data)
                batch_result = RoastedBatch(**data)
                roasted.extend(item.model_dump() for item in batch_result.items)
                print(f"     ✓ Batch {batch_num} done ({len(batch_result.items)} items)")
                success = True
                break
            except Exception as e:
                last_error = e
                print(f"     ⚠️  Batch {batch_num} attempt {attempt} failed: {e}")
                if attempt < max_retries:
                    time.sleep(2 ** attempt)

        if not success:
            print(f"     ✗ Batch {batch_num} failed all retries: {last_error}")
            return AgentState(**{**state.model_dump(), "error": str(last_error)})

    print(f"   ✓ Roasted {len(roasted)} items total")
    return AgentState(**{**state.model_dump(), "roasted_items": roasted})


# ── STAGE 3: SCENE SUMMARY ───────────────────────────────────
def summarize_scene(state: AgentState) -> AgentState:
    """Write scene_summary; compute ratio_statement in Python."""
    print("🎬 Writing scene summary...")

    if not state.roasted_items:
        return AgentState(**{**state.model_dump(), "error": "No roasted items."})

    by_id = {a["id"]: a for a in state.top_articles}
    cooking_items: list[NewsItem] = []
    cooked_items:  list[NewsItem] = []
    next_id = 1

    # cooking first, then cooked
    sorted_ri = sorted(state.roasted_items, key=lambda x: x["verdict"] == "cooked")

    for ri in sorted_ri:
        source = by_id.get(ri["id"], {})
        item = NewsItem(
            id=next_id,
            domain=ri["domain"],
            headline=ri["headline"],
            summary=ri["summary"],
            plain_english=ri["plain_english"],
            source_url=source.get("url", ""),
        )
        next_id += 1
        if ri["verdict"] == "cooking":
            cooking_items.append(item)
        else:
            cooked_items.append(item)

    ratio_statement = f"{len(cooking_items)}:{len(cooked_items)}"

    headline_digest = (
        [{"headline": i.headline, "verdict": "cooking"} for i in cooking_items]
        + [{"headline": i.headline, "verdict": "cooked"}  for i in cooked_items]
    )

    schema  = SceneSummaryOutput.model_json_schema()
    prompt  = f"""Today's Fennec digest is {ratio_statement} cooking:cooked.

Headlines:
---
{json.dumps(headline_digest, indent=2, ensure_ascii=False)}
---

Today's Hunt is the cover caption for today's issue.

Write ONE punchy sentence that captures the funniest or most interesting observation connecting today's stories.

Today's Hunt is NOT a summary.

Today's Hunt is NOT a list of topics.

Today's Hunt should feel like a clever observation a developer would make after reading the entire issue.

Prioritize memorable, relatable, and shareable over comprehensive.

The best Hunts make readers smile before they start reading.

Keep it short.

Avoid corporate language, buzzwords, and word salad.

Good examples:

* Everyone wants AGI. Nobody wants the electricity bill.
* The future is arriving right on schedule. The infrastructure isn't.
* Tech companies are spending billions building tomorrow and hoping somebody else maintains it.
* The industry keeps shipping faster than the consequences can load.
* Everyone wants autonomous software. Nobody wants autonomous problems.

Bad examples:

* The industry is scaling technical debt and vibes.
* Technology continues to evolve rapidly.
* The ecosystem is entering a transformative phase.
* Hypergrowth has entered its orbital era.


Respond ONLY with valid JSON:
{json.dumps(schema, indent=2)}
"""

    response = generate_with_retries(
        model=MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=0.7,
            response_mime_type="application/json",
        ),
    )

    try:
        data  = safe_json_loads(response.text or "")
        scene = SceneSummaryOutput(**data)
    except Exception as e:
        print(f"   ✗ Scene summary parse error: {e}")
        return AgentState(**{**state.model_dump(), "error": str(e)})

    news = NewsOutput(
        scene_summary=scene.scene_summary,
        ratio_statement=ratio_statement,
        cooking=cooking_items,
        cooked=cooked_items,
    )

    print(f"   ✓ Done. Ratio {ratio_statement} — \"{scene.scene_summary[:80]}\"")
    return AgentState(**{**state.model_dump(), "news_output": news})


# ── STAGE 4: WRITE ───────────────────────────────────────────
def write_output(state: AgentState) -> AgentState:
    if not state.news_output:
        print(f"✗ Nothing to write. Error: {state.error}")
        return state

    news  = state.news_output
    today = datetime.now().strftime("%A, %B %d, %Y")

    payload = {
        "meta": {
            "date":           today,
            "scene_summary":  news.scene_summary,
            "ratio_statement": news.ratio_statement,
        },
        "cooking": [i.model_dump() for i in news.cooking],
        "cooked":  [i.model_dump() for i in news.cooked],
    }

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)

    print(f"\n✅ Written → {OUTPUT_PATH}")
    print(f"   📰 {len(news.cooking)} cooking + {len(news.cooked)} cooked = {news.total()} items")
    print(f"   💬 \"{news.scene_summary}\"")
    return state


# ── ROUTING ──────────────────────────────────────────────────
def should_continue(state: AgentState) -> str:
    return END if state.error else "continue"


# ── BUILD GRAPH ──────────────────────────────────────────────
def build_graph() -> Any:
    builder = StateGraph(AgentState)

    builder.add_node(
        "fetch",
        fetch_signals,
        retry_policy=RetryPolicy(max_attempts=3, backoff_factor=2),
    )
    builder.add_node("rank",  rank_headlines)
    builder.add_node("roast", roast_and_classify)
    builder.add_node("scene", summarize_scene)
    builder.add_node("write", write_output)

    builder.set_entry_point("fetch")
    builder.add_edge("fetch", "rank")
    builder.add_conditional_edges("rank",  should_continue, {"continue": "roast", END: END})
    builder.add_conditional_edges("roast", should_continue, {"continue": "scene", END: END})
    builder.add_conditional_edges("scene", should_continue, {"continue": "write", END: END})
    builder.add_edge("write", END)

    return builder.compile()


# ── ENTRYPOINT ───────────────────────────────────────────────
if __name__ == "__main__":
    print("🦊 Fennec scraper starting...")
    graph = build_graph()
    final = graph.invoke(AgentState())
    if final.get("error"):
        print(f"\n❌ Failed: {final['error']}")
        exit(1)
    print("\n🦊 Fennec scraper done.")