import { NewsItem } from "../types/news";

interface Props {
  item: NewsItem;
  variant: "cooking" | "cooked";
}

export function NewsCard({ item, variant }: Props) {
  return (
    <a
      href={item.source_url}
      target="_blank"
      rel="noopener noreferrer"
      className={`news-card news-card--${variant}`}
    >
      <div className="card-favicon">
        <img
          src={`https://www.google.com/s2/favicons?domain=${item.domain}&sz=64`}
          alt={item.domain}
          width={28}
          height={28}
          loading="lazy"
          onError={(e) => {
            (e.target as HTMLImageElement).style.display = "none";
          }}
        />
      </div>

      <div className="card-body">
        <div className="card-meta">
          <span className={`card-status-dot card-status-dot--${variant}`} />
          <span className="card-domain">{item.domain}</span>
        </div>

        <h3 className="card-headline">{item.headline}</h3>

        <p className="card-summary">{item.summary}</p>

        <p className="card-plain">{item.plain_english}</p>
      </div>

      <div className="card-arrow">↗</div>
    </a>
  );
}
