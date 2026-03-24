import { forwardRef, useState } from "react";
import Markdown from "react-markdown";
import type { ReviewItem, Selection } from "../types";
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
    const [questionExpanded, setQuestionExpanded] = useState(false);

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
          className={`relative z-0 border-2 rounded-lg max-w-2xl mx-auto select-none touch-none ${cardStyle}`}
          style={{ transform, transition, boxShadow: shadow }}
          {...pointerHandlers}
        >
          {/* Question context — expandable */}
          <div
            className="p-4 bg-gray-50 rounded-t-lg cursor-pointer hover:bg-gray-100 transition-colors"
            onPointerDown={(e) => e.stopPropagation()}
            onClick={() => setQuestionExpanded(!questionExpanded)}
          >
            <div className="flex items-start justify-between gap-2">
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 mb-1">
                  <span className="text-[10px] font-semibold text-gray-400 uppercase tracking-wider">Question</span>
                  <span className="text-[10px] text-gray-400">
                    {questionExpanded ? "click to collapse" : "click to expand"}
                  </span>
                </div>
                <h2 className="text-base font-semibold text-gray-900 leading-snug">
                  {question.title}
                </h2>
              </div>
              <span className="shrink-0 text-xs text-gray-400 whitespace-nowrap mt-5">
                {timeAgo(question.created_at)}
              </span>
            </div>

            {question.tags && question.tags.length > 0 && (
              <div className="flex flex-wrap gap-1 mt-2">
                {question.tags.map((tag) => (
                  <span
                    key={tag.id ?? tag.name}
                    className="inline-block rounded-full bg-indigo-50 px-2 py-0.5 text-xs font-medium text-indigo-700"
                  >
                    {tag.name}
                  </span>
                ))}
              </div>
            )}

            {questionExpanded && question.body && (
              <div className="mt-3 prose prose-sm max-w-none text-gray-700 prose-headings:text-gray-900 prose-code:text-gray-900 prose-code:bg-gray-200 prose-code:px-1.5 prose-code:py-0.5 prose-code:rounded prose-code:text-xs prose-pre:bg-gray-900 prose-pre:text-gray-100 prose-pre:text-xs">
                <Markdown>{question.body}</Markdown>
              </div>
            )}
          </div>

          <div className="border-t border-gray-200" />

          {/* Item under review */}
          <div className="p-5">
            <div className="flex items-center justify-between mb-3">
              <div className="flex items-center gap-2">
                <span className="text-xs font-semibold text-indigo-600 uppercase tracking-wide">
                  {type === "answer" ? "Answer for review" : "Comment for review"}
                </span>
                {isSupervised && (
                  <span className="inline-block rounded-full bg-blue-100 px-2 py-0.5 text-xs font-medium text-blue-700">
                    supervised
                  </span>
                )}
              </div>
              <button
                onPointerDown={(e) => e.stopPropagation()}
                onClick={(e) => {
                  e.stopPropagation();
                  setEditOpen(true);
                }}
                className="text-xs text-indigo-500 hover:text-indigo-700 font-medium hover:underline"
              >
                Edit before approving
              </button>
            </div>

            <div className="prose prose-sm max-w-none text-gray-800 prose-headings:text-gray-900 prose-headings:mt-4 prose-headings:mb-2 prose-p:my-2 prose-code:text-gray-900 prose-code:bg-gray-200 prose-code:px-1.5 prose-code:py-0.5 prose-code:rounded prose-code:text-xs prose-code:before:content-none prose-code:after:content-none prose-pre:bg-gray-900 prose-pre:text-gray-100 prose-pre:text-xs prose-pre:rounded-lg prose-li:my-0.5 prose-ul:my-2 prose-ol:my-2">
              <Markdown>{contentBody}</Markdown>
            </div>

            <p className="mt-4 pt-3 border-t border-gray-100 text-xs text-gray-400">
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
