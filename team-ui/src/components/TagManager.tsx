import { useState } from "react";
import { api } from "../api";
import type { Tag } from "../types";

interface Props {
  tags: Tag[];
  onRefresh: () => void;
}

export function TagManager({ tags, onRefresh }: Props) {
  const [open, setOpen] = useState(false);
  const [mergingTagId, setMergingTagId] = useState<string | null>(null);
  const [targetTagId, setTargetTagId] = useState<string>("");
  const [merging, setMerging] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleMerge(sourceId: string) {
    if (!targetTagId || targetTagId === sourceId) return;
    setMerging(true);
    setError(null);
    try {
      await api.mergeTags(sourceId, targetTagId);
      setMergingTagId(null);
      setTargetTagId("");
      onRefresh();
    } catch {
      setError("Merge failed — try again");
    } finally {
      setMerging(false);
    }
  }

  const sorted = [...tags].sort((a, b) => b.usage_count - a.usage_count);

  return (
    <div className="bg-white rounded-lg border border-gray-200">
      <button
        onClick={() => setOpen((o) => !o)}
        className="w-full flex items-center justify-between px-4 py-3 text-left"
      >
        <h3 className="text-xs font-semibold text-gray-500 uppercase">
          Tags ({tags.length})
        </h3>
        <span className="text-gray-400 text-sm">{open ? "▲" : "▼"}</span>
      </button>

      {open && (
        <div className="px-4 pb-4">
          {error && (
            <p className="text-sm text-red-600 mb-3">{error}</p>
          )}
          <div className="space-y-2 max-h-64 overflow-y-auto">
            {sorted.map((tag) => (
              <div key={tag.id} className="flex items-center gap-2">
                <span className="flex-1 text-sm text-gray-700 truncate">
                  {tag.name}
                  <span className="ml-1.5 text-xs text-gray-400">({tag.usage_count})</span>
                </span>

                {mergingTagId === tag.id ? (
                  <div className="flex items-center gap-1">
                    <select
                      value={targetTagId}
                      onChange={(e) => setTargetTagId(e.target.value)}
                      className="text-xs border border-gray-300 rounded px-1 py-0.5"
                      disabled={merging}
                    >
                      <option value="">Merge into...</option>
                      {sorted
                        .filter((t) => t.id !== tag.id)
                        .map((t) => (
                          <option key={t.id} value={t.id}>
                            {t.name}
                          </option>
                        ))}
                    </select>
                    <button
                      onClick={() => handleMerge(tag.id)}
                      disabled={merging || !targetTagId}
                      className="text-xs font-medium text-indigo-600 hover:text-indigo-800 disabled:opacity-50"
                    >
                      {merging ? "..." : "Go"}
                    </button>
                    <button
                      onClick={() => { setMergingTagId(null); setTargetTagId(""); }}
                      className="text-xs text-gray-400 hover:text-gray-600"
                    >
                      Cancel
                    </button>
                  </div>
                ) : (
                  <button
                    onClick={() => setMergingTagId(tag.id)}
                    className="text-xs text-gray-400 hover:text-indigo-600"
                  >
                    Merge
                  </button>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
