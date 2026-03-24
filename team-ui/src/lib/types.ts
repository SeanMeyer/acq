export interface VoteCounts {
  agent_upvotes: number;
  agent_downvotes: number;
  human_upvotes: number;
  human_downvotes: number;
}

export interface Tag {
  id: string;
  name: string;
  usage_count: number;
}

export interface Question {
  id: string;
  title: string;
  body: string;
  author: string;
  created_at: string;
  updated_at: string;
  status: string;
  tags: Tag[];
  votes: VoteCounts;
  pinned_answer_id?: string | null;
}

export interface Answer {
  id: string;
  question_id: string;
  body: string;
  author: string;
  created_at: string;
  updated_at: string;
  status: string;
  supervised: boolean;
  votes: VoteCounts;
}

export interface Comment {
  id: string;
  question_id?: string;
  answer_id?: string;
  body: string;
  author: string;
  created_at: string;
  updated_at: string;
  status: string;
}

export interface EditHistoryEntry {
  id: string;
  edited_by: string;
  edited_at: string;
  previous_body: string;
  new_body: string;
}

export interface ReviewItem {
  id: string;
  type: 'answer' | 'comment';
  content: Answer | Comment;
  question: Question;
  status: string;
}

export interface ReviewQueueResponse {
  items: ReviewItem[];
  total: number;
}

export interface ActivityEvent {
  id: string;
  event_type: string;
  description: string;
  actor: string;
  created_at: string;
}

export interface ReviewStats {
  total_questions: number;
  total_answers: number;
  total_pending: number;
  total_unanswered: number;
  tags: Tag[];
  recent_activity: ActivityEvent[];
  vote_distribution: unknown[];
  total_votes: number;
}
