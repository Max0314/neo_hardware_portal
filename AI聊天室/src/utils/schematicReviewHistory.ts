import axios from 'axios';
import { apiUrl } from '@/utils/apiBase';
import type { SchematicCheckDispositionMap } from '@/utils/schematicReview';
import type { AIReviewEntry } from '@/components/NetlistResultsPanel';

export interface SchematicReviewHistorySummary {
  id: string;
  title: string;
  netlist_result_id?: string | null;
  summary_pass: number;
  summary_warning: number;
  summary_info: number;
  created_at: string;
}

export interface SchematicReviewHistoryPayload {
  aggregated_review_summary: any;
  ai_review_entries: Array<{
    id: string;
    content: string;
    parsed: any;
    timestamp?: string;
    aiName: string;
  }>;
  cleaned_netlist_text: string;
  check_dispositions: SchematicCheckDispositionMap;
  default_ai_name: string;
  netlist_name: string;
}

export interface SchematicReviewHistoryRecord extends SchematicReviewHistorySummary {
  payload: SchematicReviewHistoryPayload;
}

export async function listSchematicReviewHistory(): Promise<SchematicReviewHistorySummary[]> {
  const res = await axios.get(apiUrl('/api/schematic-review/history'), { withCredentials: true });
  if (!res.data?.success) throw new Error(res.data?.error || '加载历史失败');
  return res.data.records || [];
}

export async function getSchematicReviewHistory(
  id: string
): Promise<SchematicReviewHistoryRecord> {
  const res = await axios.get(apiUrl(`/api/schematic-review/history/${id}`), {
    withCredentials: true,
  });
  if (!res.data?.success) throw new Error(res.data?.error || '加载记录失败');
  return res.data.record;
}

export async function saveSchematicReviewHistory(body: {
  title: string;
  netlist_name: string;
  netlist_result_id: string | null;
  summary: { pass: number; warning: number; info: number };
  aggregated_review_summary: any;
  ai_review_entries: AIReviewEntry[];
  cleaned_netlist_text: string;
  check_dispositions: SchematicCheckDispositionMap;
  default_ai_name: string;
}): Promise<SchematicReviewHistorySummary> {
  const entries = body.ai_review_entries.map((e) => ({
    id: e.id,
    content: e.content,
    parsed: e.parsed,
    timestamp: e.timestamp instanceof Date ? e.timestamp.toISOString() : e.timestamp,
    aiName: e.aiName,
  }));
  const res = await axios.post(
    apiUrl('/api/schematic-review/history'),
    { ...body, ai_review_entries: entries },
    { withCredentials: true }
  );
  if (!res.data?.success) throw new Error(res.data?.error || '保存历史失败');
  return res.data.record;
}

export function parseHistoryAiReviewEntries(
  entries: SchematicReviewHistoryPayload['ai_review_entries']
): AIReviewEntry[] {
  return (entries || []).map((e) => ({
    id: e.id,
    content: e.content,
    parsed: e.parsed,
    timestamp: e.timestamp ? new Date(e.timestamp) : new Date(),
    aiName: e.aiName,
  }));
}
