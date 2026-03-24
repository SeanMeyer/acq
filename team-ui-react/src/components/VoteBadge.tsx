import type { VoteCounts } from "../types";

function VoteGroup({
  upvotes,
  downvotes,
  label,
}: {
  upvotes: number;
  downvotes: number;
  label: string;
}) {
  return (
    <span className="inline-flex items-center gap-1 text-xs">
      <span className={upvotes > 0 ? "text-green-600 font-medium" : "text-gray-400"}>
        {upvotes}↑
      </span>
      <span className={downvotes > 0 ? "text-red-600 font-medium" : "text-gray-400"}>
        {downvotes}↓
      </span>
      <span className="text-gray-400">({label})</span>
    </span>
  );
}

export function VoteBadge(votes: VoteCounts) {
  return (
    <span className="inline-flex items-center gap-2">
      <VoteGroup
        upvotes={votes.agent_upvotes}
        downvotes={votes.agent_downvotes}
        label="agent"
      />
      <span className="text-gray-300">·</span>
      <VoteGroup
        upvotes={votes.human_upvotes}
        downvotes={votes.human_downvotes}
        label="human"
      />
    </span>
  );
}
