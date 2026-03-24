import { useState, useEffect, useCallback } from "react";
import { Link, useOutletContext } from "react-router";
import { api } from "../api";
import { StatusBadge } from "../components/StatusBadge";
import { TagManager } from "../components/TagManager";
import { timeAgo } from "../utils";
import type { ReviewStats } from "../types";

export function DashboardPage() {
  const { setPendingCount } = useOutletContext<{
    setPendingCount: (n: number) => void;
  }>();
  const [stats, setStats] = useState<ReviewStats | null>(null);
  const [error, setError] = useState<string | null>(null);

  const fetchStats = useCallback(() => {
    api
      .reviewStats()
      .then((s) => {
        setStats(s);
        setPendingCount(s.total_pending);
        setError(null);
      })
      .catch(() => setError("Failed to load dashboard. Retrying..."));
  }, [setPendingCount]);

  useEffect(() => {
    fetchStats();
    const interval = setInterval(fetchStats, 15_000);
    return () => clearInterval(interval);
  }, [fetchStats]);

  if (!stats && !error) {
    return (
      <div className="space-y-6">
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          {[1, 2, 3, 4].map((i) => (
            <div key={i} className="bg-white rounded-lg border border-gray-200 p-4">
              <div className="h-4 w-16 animate-pulse bg-gray-200 rounded mb-2" />
              <div className="h-8 w-12 animate-pulse bg-gray-200 rounded" />
            </div>
          ))}
        </div>
        {[1, 2].map((i) => (
          <div key={i} className="bg-white rounded-lg border border-gray-200 p-4 h-40 animate-pulse bg-gray-100" />
        ))}
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {error && (
        <div className="bg-red-50 border border-red-200 rounded-lg p-4 text-center">
          <p className="text-red-600 text-sm font-medium">{error}</p>
        </div>
      )}

      {stats && (
        <>
          {/* Stats cards */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <Link
              to="/review"
              className="bg-white rounded-lg border border-gray-200 p-4 text-center hover:border-amber-300 transition-colors"
            >
              <p className="text-3xl font-bold text-amber-500">{stats.total_pending}</p>
              <p className="text-xs text-gray-500 uppercase mt-1">Pending Review</p>
            </Link>
            <div className="bg-white rounded-lg border border-gray-200 p-4 text-center">
              <p className="text-3xl font-bold text-indigo-600">{stats.total_questions}</p>
              <p className="text-xs text-gray-500 uppercase mt-1">Questions</p>
            </div>
            <div className="bg-white rounded-lg border border-gray-200 p-4 text-center">
              <p className="text-3xl font-bold text-green-600">{stats.total_answers}</p>
              <p className="text-xs text-gray-500 uppercase mt-1">Answers</p>
            </div>
            <div className="bg-white rounded-lg border border-gray-200 p-4 text-center">
              <p className="text-3xl font-bold text-red-500">{stats.total_unanswered}</p>
              <p className="text-xs text-gray-500 uppercase mt-1">Unanswered</p>
            </div>
          </div>

          {/* Top tags */}
          {stats.tags.length > 0 && (
            <div className="bg-white rounded-lg border border-gray-200 p-4">
              <h3 className="text-xs font-semibold text-gray-500 uppercase mb-3">Top Tags</h3>
              <div className="space-y-2 max-h-48 overflow-y-auto">
                {[...stats.tags]
                  .sort((a, b) => b.usage_count - a.usage_count)
                  .slice(0, 10)
                  .map((tag) => {
                    const maxCount = Math.max(...stats.tags.map((t) => t.usage_count), 1);
                    return (
                      <div key={tag.id} className="flex items-center gap-3">
                        <span className="text-sm text-gray-700 w-28 truncate">{tag.name}</span>
                        <div className="flex-1 h-1.5 bg-gray-100 rounded-full overflow-hidden">
                          <div
                            className="h-full bg-indigo-500 rounded-full"
                            style={{ width: `${(tag.usage_count / maxCount) * 100}%` }}
                          />
                        </div>
                        <span className="text-xs text-gray-400 w-6 text-right">
                          {tag.usage_count}
                        </span>
                      </div>
                    );
                  })}
              </div>
            </div>
          )}

          {/* Vote distribution */}
          {stats.vote_distribution.length > 0 && (
            <div className="bg-white rounded-lg border border-gray-200 p-4">
              <h3 className="text-xs font-semibold text-gray-500 uppercase mb-3">Vote Distribution</h3>
              {(() => {
                const maxCount = Math.max(...stats.vote_distribution.map((b) => b.count), 1);
                return (
                  <div className="flex gap-2">
                    {stats.vote_distribution.map(({ bucket, count }) => (
                      <div
                        key={bucket}
                        className="flex-1 flex flex-col items-center gap-1"
                      >
                        <span className="text-xs text-gray-500 font-medium">{count}</span>
                        <div className="w-full h-24 flex items-end">
                          <div
                            className="w-full rounded-t bg-indigo-300"
                            style={{
                              height: maxCount > 0 ? `${(count / maxCount) * 100}%` : "0",
                              minHeight: count > 0 ? "8px" : "0",
                            }}
                          />
                        </div>
                        <span className="text-[10px] text-gray-500 truncate w-full text-center">
                          {bucket}
                        </span>
                      </div>
                    ))}
                  </div>
                );
              })()}
            </div>
          )}

          {/* Recent activity */}
          <div className="bg-white rounded-lg border border-gray-200 p-4">
            <h3 className="text-xs font-semibold text-gray-500 uppercase mb-3">Recent Activity</h3>
            <div className="max-h-60 overflow-y-auto">
              {stats.recent_activity.length === 0 ? (
                <p className="text-gray-400 text-sm">No activity yet</p>
              ) : (
                <table className="w-full">
                  <thead>
                    <tr className="border-b border-gray-200">
                      <th className="py-1.5 pr-3 text-left text-[10px] font-semibold text-gray-400 uppercase w-20">Status</th>
                      <th className="py-1.5 pr-3 text-left text-[10px] font-semibold text-gray-400 uppercase">Summary</th>
                      <th className="py-1.5 pr-3 text-left text-[10px] font-semibold text-gray-400 uppercase w-16">Type</th>
                      <th className="py-1.5 text-right text-[10px] font-semibold text-gray-400 uppercase w-16">Time</th>
                    </tr>
                  </thead>
                  <tbody>
                    {stats.recent_activity.map((event, i) => (
                      <tr key={`${event.item_id}-${i}`} className="border-b border-gray-50 last:border-0">
                        <td className="py-2 pr-3 w-20">
                          <StatusBadge status={event.type} />
                        </td>
                        <td className="py-2 pr-3 text-sm text-gray-700 truncate max-w-0">
                          {event.summary}
                          {event.supervised && (
                            <span className="ml-1.5 inline-block rounded-full bg-blue-100 px-1.5 py-0.5 text-[10px] font-medium text-blue-600">
                              supervised
                            </span>
                          )}
                        </td>
                        <td className="py-2 pr-3 text-xs text-gray-400 w-16">
                          {event.item_type}
                        </td>
                        <td className="py-2 text-xs text-gray-400 whitespace-nowrap w-16 text-right">
                          {event.timestamp ? timeAgo(event.timestamp) : ""}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </div>

          {/* Tag manager */}
          {stats.tags.length > 0 && (
            <TagManager tags={stats.tags} onRefresh={fetchStats} />
          )}
        </>
      )}
    </div>
  );
}
