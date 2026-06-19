export interface NewsItem {
  id: number;
  domain: string;
  headline: string;
  summary: string;
  plain_english: string;
  source_url: string;
}

export interface NewsMeta {
  date: string;
  scene_summary: string;
  ratio_statement: string;
}

export interface NewsData {
  meta: NewsMeta;
  cooking: NewsItem[];
  cooked: NewsItem[];
}
