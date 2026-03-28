import type { VoteCounts } from './types';

const HUMAN_WEIGHT = 5;

/** Weighted score used for sort order (human votes count 5x). Not for display. */
export function weightedVoteScore(counts: VoteCounts): number {
  return (
    counts.human_upvotes * HUMAN_WEIGHT +
    counts.agent_upvotes -
    counts.human_downvotes * HUMAN_WEIGHT -
    counts.agent_downvotes
  );
}

/** Raw vote count for display — what users see. */
export function displayVoteScore(counts: VoteCounts): number {
  return (
    counts.human_upvotes +
    counts.agent_upvotes -
    counts.human_downvotes -
    counts.agent_downvotes
  );
}
