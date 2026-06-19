import { useEffect, useState } from "react";
import { NewsData } from "./types/news";
import { Header } from "./components/Header";
import { SceneOverview } from "./components/SceneOverview";
import { Feed } from "./components/Feed";

function App() {
  const [data, setData] = useState<NewsData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [dark, setDark] = useState(() => {
    const saved = localStorage.getItem("fennec-theme");
    if (saved) return saved === "dark";
    // Default to dark for first-time visitors
    return true;
  });

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", dark ? "dark" : "light");
    localStorage.setItem("fennec-theme", dark ? "dark" : "light");
  }, [dark]);

  // Polling configuration (ms)
  const POLL_INTERVAL_MS = 300_000; // 5 minutes

  // Load feed once and then poll periodically. Uses cache-busting query
  // param and `cache: 'no-store'` to avoid stale cached responses.
  useEffect(() => {
    let mounted = true;
    async function load() {
      try {
        const res = await fetch(`/news.json?ts=${Date.now()}`, { cache: "no-store" });
        if (!res.ok) throw new Error("Failed to load news feed.");
        const json = await res.json();
        if (mounted) setData(json);
      } catch (e) {
        if (mounted) setError((e as Error).message);
      }
    }
    load();
    const id = setInterval(load, POLL_INTERVAL_MS);
    return () => {
      mounted = false;
      clearInterval(id);
    };
  }, []);

  if (error) {
    return (
      <div className="state-screen">
        <span className="state-icon">⚠</span>
        <p className="state-text">{error}</p>
        <p className="state-sub">Run the scraper to generate news.json first.</p>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="state-screen">
        <span className="state-icon loading-pulse">🦊</span>
        <p className="state-text">Loading feed…</p>
      </div>
    );
  }

  return (
    <div className="app">
      <Header dark={dark} onToggle={() => setDark((d) => !d)} />
      <SceneOverview
        meta={data.meta}
        cookingCount={data.cooking.length}
        cookedCount={data.cooked.length}
      />
      <Feed cooking={data.cooking} cooked={data.cooked} />
      <footer className="footer">
        <span>Fennec — built serverless on GitHub</span>
        <span className="footer-sep">·</span>
        <span>10 signals, daily, zero cost</span>
      </footer>
    </div>
  );
}

export default App;