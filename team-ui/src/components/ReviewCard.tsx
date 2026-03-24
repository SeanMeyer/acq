import { forwardRef, useState } from "react";
import type { ReviewItem, Answer, Selection } from "../types";
import { VoteBadge } from "./VoteBadge";
import { EditModal } from "./EditModal";
import { timeAgo } from "../utils";
import { api } from "../api";
import type { DragState, PointerHandlers } from "../hooks/useCardDrag";
import { FLY_OFF_MS, MAX_ROTATION_DEG, SNAP_BACK_MS } from "../hooks/useCardDrag";

interface Props {
  item: ReviewItem;
  selection: Selection;
  drag: DragState;
  pointerHandlers: PointerHandlers;
  onContentEdited?: (newBody: string) => void;
}

const CARD_STYLES: Record<string, string> = {
  neutral: "border-gray-200 bg-white",
  approve: "border-green-300 bg-green-50",
  reject: "border-red-300 bg-red-50",
  skip: "border-slate-400 bg-slate-50",
};

export const ReviewCard = forwardRef<HTMLDivElement, Props>(
  function ReviewCard({ item, selection, drag, pointerHandlers, onContentEdited }, ref) {
    const [editOpen, setEditOpen] = useState(false);

    const activeState = drag.isDragging || drag.isFlyingOff ? drag.dragAction : selection;
    const cardStyle = CARD_STYLES[activeState ?? "neutral"];

    const rotation = drag.isDragging
      ? (drag.offset.x / 300) * MAX_ROTATION_DEG
      : 0;
    const shadowScale = drag.isDragging ? 1 + drag.dragProgress * 0.5 : 1;
    const transform = `translate(${drag.offset.x}px, ${drag.offset.y}px) rotate(${rotation}deg)`;
    const transition = drag.isDragging
      ? "none"
      : drag.isFlyingOff
        ? `transform ${FLY_OFF_MS}ms ease-in, box-shadow ${FLY_OFF_MS}ms ease-in`
        : `transform ${SNAP_BACK_MS}ms ease-out, box-shadow ${SNAP_BACK_MS}ms ease-out`;
    const shadow = `0 ${4 * shadowScale}px ${20 * shadowScale}px rgba(0,0,0,${0.08 * shadowScale})`;

    const { question, content, type } = item;
    const contentBody = content.body;

    async function handleSave(newBody: string) {
      if (type === "answer") {
        await api.editAnswer(content.id, newBody);
      } else {
        await api.editAnswer(content.id, newBody);
      }
      onContentEdited?.(newBody);
    }

    const isSupervised = "supervised" in content && content.supervised;

    return (
      <>
        <div
          ref={ref}
          className={`relative z-0 border-2 rounded-lg p-5 max-w-xl mx-auto select-none touch-none ${cardStyle}`}
          style={{ transform, transition, boxShadow: shadow }}
          {...pointerHandlers}
        >
          {/* Question context */}
          <div className="mb-4">
            <div className="flex items-start justify-between gap-2 mb-1">
              <h2 className="text-base font-semibold text-gray-900 leading-snug">
                {question.title}
              </h2>
              <span className="shrink-0 text-xs text-gray-400 whitespace-nowrap">
                {timeAgo(question.created_at)}
              </span>
            </div>

            {question.tags.length > 0 && (
              <div className="flex flex-wrap gap-1 mb-2">
                {question.tags.map((tag) => (
                  <span
                    key={tag.id}
                    className="inline-block rounded-full bg-indigo-50 px-2 py-0.5 text-xs font-medium text-indigo-700"
                  >
                    {tag.name}
                  </span>
                ))}
              </div>
            )}

            <VoteBadge {...question} />

            {question.body && (
              <p className="mt-2 text-sm text-gray-500 leading-relaxed line-clamp-3">
                {question.body}
              </p>
            )}
          </div>

          <div className="border-t border-gray-200 my-3" />

          {/* Item under review */}
          <div className="relative">
            <div className="flex items-center justify-between mb-2">
              <div className="flex items-center gap-2">
                <span className="text-xs font-semibold text-gray-500 uppercase tracking-wide">
                  {type === "answer" ? "Answer" : "Comment"}
                </span>
                {isSupervised && (
                  <span className="inline-block rounded-full bg-blue-100 px-2 py-0.5 text-xs font-medium text-blue-700">
                    supervised
                  </span>
                )}
              </div>
              <div className="flex items-center gap-2">
                {"agent_upvotes" in content && (
                  <VoteBadge {...(content as Answer)} />
                )}
                <button
                  onPointerDown={(e) => e.stopPropagation()}
                  onClick={(e) => {
                    e.stopPropagation();
                    setEditOpen(true);
                  }}
                  className="text-xs text-indigo-500 hover:text-indigo-700 font-medium"
                >
                  Edit
                </button>
              </div>
            </div>

            <p className="text-sm text-gray-800 leading-relaxed whitespace-pre-wrap">
              {contentBody}
            </p>

            <p className="mt-2 text-xs text-gray-400">
              by {content.created_by} ({content.created_by_type}) · {timeAgo(content.created_at)}
            </p>
          </div>
        </div>

        <EditModal
          isOpen={editOpen}
          onClose={() => setEditOpen(false)}
          onSave={handleSave}
          title={`Edit ${type}`}
          initialBody={contentBody}
        />
      </>
    );
  },
);
