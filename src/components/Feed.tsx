import { NewsItem } from "../types/news";
import { NewsCard } from "./NewsCard";

interface Props {
  cooking: NewsItem[];
  cooked: NewsItem[];
}

export function Feed({ cooking, cooked }: Props) {
  return (
    <main className="feed">
      {/* COOKING SECTION */}
      <section className="feed-section">
        <div className="section-header">
          <div className="section-header-line" />
          <div className="section-header-label section-header-label--cooking">
            <span className="section-icon">🔥</span>
            <span className="section-title">COOKING</span>
            <span className="section-count">{cooking.length}</span>
          </div>
          <div className="section-header-line" />
        </div>

        <div className="cards-grid">
          {cooking.map((item) => (
            <NewsCard key={item.id} item={item} variant="cooking" />
          ))}
        </div>
      </section>

      {/* COOKED SECTION */}
      <section className="feed-section">
        <div className="section-header">
          <div className="section-header-line" />
          <div className="section-header-label section-header-label--cooked">
            <span className="section-icon">💀</span>
            <span className="section-title">COOKED</span>
            <span className="section-count">{cooked.length}</span>
          </div>
          <div className="section-header-line" />
        </div>

        <div className="cards-grid">
          {cooked.map((item) => (
            <NewsCard key={item.id} item={item} variant="cooked" />
          ))}
        </div>
      </section>
    </main>
  );
}
