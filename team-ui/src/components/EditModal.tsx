import { useState, useEffect } from "react";

interface Props {
  isOpen: boolean;
  onClose: () => void;
  onSave: (newBody: string) => Promise<void>;
  title: string;
  initialBody: string;
}

export function EditModal({ isOpen, onClose, onSave, title, initialBody }: Props) {
  const [body, setBody] = useState(initialBody);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<"edit" | "diff">("edit");

  useEffect(() => {
    if (isOpen) {
      setBody(initialBody);
      setError(null);
      setTab("edit");
    }
  }, [isOpen, initialBody]);

  if (!isOpen) return null;

  async function handleSave() {
    setSaving(true);
    setError(null);
    try {
      await onSave(body);
      onClose();
    } catch {
      setError("Failed to save — try again");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40"
      onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}
    >
      <div className="bg-white rounded-lg shadow-xl w-full max-w-2xl mx-4 flex flex-col max-h-[90vh]">
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200">
          <h2 className="text-base font-semibold text-gray-900">{title}</h2>
          <button
            onClick={onClose}
            className="text-gray-400 hover:text-gray-600 text-lg leading-none"
            aria-label="Close"
          >
            ×
          </button>
        </div>

        <div className="flex border-b border-gray-200 px-6">
          <button
            onClick={() => setTab("edit")}
            className={`py-2 pr-4 text-sm font-medium border-b-2 -mb-px ${
              tab === "edit"
                ? "border-indigo-500 text-indigo-600"
                : "border-transparent text-gray-500 hover:text-gray-700"
            }`}
          >
            Edit
          </button>
          <button
            onClick={() => setTab("diff")}
            className={`py-2 px-4 text-sm font-medium border-b-2 -mb-px ${
              tab === "diff"
                ? "border-indigo-500 text-indigo-600"
                : "border-transparent text-gray-500 hover:text-gray-700"
            }`}
          >
            Compare
          </button>
        </div>

        <div className="flex-1 overflow-auto p-6">
          {tab === "edit" ? (
            <textarea
              value={body}
              onChange={(e) => setBody(e.target.value)}
              className="w-full h-64 border border-gray-300 rounded-lg px-3 py-2 text-sm font-mono focus:border-indigo-500 focus:outline-none resize-y"
              disabled={saving}
            />
          ) : (
            <div className="grid grid-cols-2 gap-4">
              <div>
                <p className="text-xs font-semibold text-gray-400 uppercase mb-2">Original</p>
                <pre className="text-sm text-gray-700 whitespace-pre-wrap font-mono bg-red-50 border border-red-100 rounded-lg p-3 min-h-32">
                  {initialBody}
                </pre>
              </div>
              <div>
                <p className="text-xs font-semibold text-gray-400 uppercase mb-2">Edited</p>
                <pre className="text-sm text-gray-700 whitespace-pre-wrap font-mono bg-green-50 border border-green-100 rounded-lg p-3 min-h-32">
                  {body}
                </pre>
              </div>
            </div>
          )}
        </div>

        {error && (
          <p className="px-6 py-2 text-sm text-red-600">{error}</p>
        )}

        <div className="flex items-center justify-end gap-3 px-6 py-4 border-t border-gray-200">
          <button
            onClick={onClose}
            disabled={saving}
            className="px-4 py-2 text-sm font-medium text-gray-700 hover:text-gray-900 disabled:opacity-50"
          >
            Cancel
          </button>
          <button
            onClick={handleSave}
            disabled={saving || body === initialBody}
            className="px-4 py-2 text-sm font-medium bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 disabled:opacity-50"
          >
            {saving ? "Saving..." : "Save"}
          </button>
        </div>
      </div>
    </div>
  );
}
