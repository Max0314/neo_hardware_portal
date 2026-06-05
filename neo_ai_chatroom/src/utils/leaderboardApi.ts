import axios from 'axios';
import { apiUrl } from '@/utils/apiBase';
import type { LeaderboardEntry, LeaderboardResponse } from '@/types/leaderboard';

interface ActiveUsersResponse {
  success: boolean;
  users?: { userKey: string; name: string }[];
  error?: string;
}

interface ScoresResponse {
  success: boolean;
  currentUserKey?: string;
  pointsByUserKey?: Record<string, { total: number; month: number }>;
  myTotalPoints?: number;
  myMonthPoints?: number;
  error?: string;
}

function buildEntriesFromParts(
  users: { userKey: string; name: string }[],
  pointsByUserKey: Record<string, { total: number; month: number }>,
  currentUserKey: string
): LeaderboardEntry[] {
  return users.map((u) => {
    const pts = pointsByUserKey[u.userKey] ?? { total: 0, month: 0 };
    return {
      userKey: u.userKey,
      name: u.name,
      totalPoints: pts.total ?? 0,
      monthPoints: pts.month ?? 0,
      isSelf: u.userKey === currentUserKey,
    };
  });
}

function rankFromEntries(entries: LeaderboardEntry[], mode: 'total' | 'month'): number {
  const key = mode === 'total' ? 'totalPoints' : 'monthPoints';
  const sorted = [...entries].sort((a, b) => b[key] - a[key] || a.name.localeCompare(b.name, 'zh-CN'));
  return sorted.findIndex((e) => e.isSelf) + 1;
}

export async function fetchLeaderboard(): Promise<LeaderboardResponse> {
  try {
    const res = await axios.get<LeaderboardResponse>(apiUrl('/api/leaderboard'), {
      withCredentials: true,
    });
    if (res.data?.success) return res.data;
    throw new Error(res.data?.error || '加载排行榜失败');
  } catch (primaryErr: unknown) {
    const status = (primaryErr as { response?: { status?: number } })?.response?.status;
    if (status !== 502 && status !== 404 && status !== 503) {
      throw primaryErr;
    }
    const [usersRes, scoresRes] = await Promise.all([
      axios.get<ActiveUsersResponse>(apiUrl('/api/neo/active-users'), { withCredentials: true }),
      axios.get<ScoresResponse>(apiUrl('/api/leaderboard/scores'), { withCredentials: true }),
    ]);
    if (!usersRes.data?.success || !scoresRes.data?.success) {
      throw new Error(usersRes.data?.error || scoresRes.data?.error || '加载排行榜失败');
    }
    const users = usersRes.data.users ?? [];
    const pointsByUserKey = scoresRes.data.pointsByUserKey ?? {};
    const currentUserKey = scoresRes.data.currentUserKey ?? '';
    const entries = buildEntriesFromParts(users, pointsByUserKey, currentUserKey);
    return {
      success: true,
      currentUserKey,
      myTotalPoints: scoresRes.data.myTotalPoints ?? 0,
      myMonthPoints: scoresRes.data.myMonthPoints ?? 0,
      myRankTotal: rankFromEntries(entries, 'total'),
      myRankMonth: rankFromEntries(entries, 'month'),
      entries,
    };
  }
}
