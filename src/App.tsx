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
    return window.matchMedia("(prefers-color-scheme: dark)").matches;
  });

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", dark ? "dark" : "light");
    localStorage.setItem("fennec-theme", dark ? "dark" : "light");
  }, [dark]);

  useEffect(() => {
    fetch("./news.json")
      .then((r) => {
        if (!r.ok) throw new Error("Failed to load news feed.");
        return r.json();
      })
      .then(setData)
      .catch((e) => setError(e.message));
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