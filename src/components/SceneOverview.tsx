import { NewsMeta } from "../types/news";

interface Props {
  meta: NewsMeta;
  cookingCount: number;
  cookedCount: number;
}

export function SceneOverview({ meta, cookingCount, cookedCount }: Props) {
  const total = cookingCount + cookedCount;
  const cookingPct = Math.round((cookingCount / total) * 100);
  const cookedPct = 100 - cookingPct;

  return (
    <section className="scene-overview">
      <p className="scene-summary">
        <span className="scene-label">Today's Hunt: </span>
        {meta.scene_summary}
      </p>

      <div className="ratio-bar-container">
        <div className="ratio-label ratio-label--cooking">
          <span className="ratio-dot ratio-dot--cooking" />
          <span className="ratio-badge">Cooking</span>
          <span className="ratio-pct">{cookingPct}%</span>
        </div>

        <div className="ratio-track">
          <div className="ratio-fill ratio-fill--cooking" style={{ width: `${cookingPct}%` }} />
          <div className="ratio-fill ratio-fill--cooked" style={{ width: `${cookedPct}%` }} />
        </div>

        <div className="ratio-label ratio-label--cooked">
          <span className="ratio-pct">{cookedPct}%</span>
          <span className="ratio-badge">Cooked</span>
          <span className="ratio-dot ratio-dot--cooked" />
        </div>
      </div>

      <p className="meta-date">{meta.date}</p>
    </section>
  );
}