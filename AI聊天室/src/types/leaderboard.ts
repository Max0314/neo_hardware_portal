export interface LeaderboardEntry {
  userKey: string;
  name: string;
  totalPoints: number;
  monthPoints: number;
  level?: number;
  levelTitle?: string;
  isSelf: boolean;
}

export interface LeaderboardPointsRules {
  aiCheckExport?: number;
  materialDbEdit?: number;
  compareTool?: number;
  sopComplete?: number;
  monthLabel: string;
}

export interface LeaderboardResponse {
  success: boolean;
  currentUserKey?: string;
  myTotalPoints?: number;
  myMonthPoints?: number;
  myLevel?: number;
  myLevelTitle?: string;
  myRankTotal?: number;
  myRankMonth?: number;
  entries?: LeaderboardEntry[];
  pointsRules?: LeaderboardPointsRules;
  error?: string;
}
