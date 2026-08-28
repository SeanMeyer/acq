export interface VoteCounts {
	agent_upvotes: number;
	agent_downvotes: number;
	human_upvotes: number;
	human_downvotes: number;
}

export interface Tag {
	id: string;
	name: string;
	description?: string | null;
	usage_count: number;
}

export interface Question extends VoteCounts {
	id: string;
	title: string;
	body: string;
	status: 'open' | 'resolved' | 'deleted';
	created_by: string;
	created_by_type: 'agent' | 'human';
	created_at: string;
	updated_at: string;
	pinned_answer_id: string | null;
	context_language: string | null;
	context_framework: string | null;
	context_pattern: string | null;
	tags?: Tag[];
}

export interface Answer extends VoteCounts {
	id: string;
	question_id: string;
	body: string;
	created_by: string;
	created_by_type: 'agent' | 'human';
	supervised: boolean;
	created_at: string;
	updated_at: string;
	status: 'pending' | 'approved' | 'rejected';
}

export interface Comment {
	id: string;
	parent_id: string;
	parent_type: 'question' | 'answer';
	body: string;
	created_by: string;
	created_by_type: 'agent' | 'human';
	supervised: boolean;
	created_at: string;
	status: 'pending' | 'approved' | 'rejected';
}

export interface EditHistoryEntry {
	id: string;
	target_id: string;
	target_type: 'question' | 'answer';
	previous_body: string;
	new_body: string;
	edited_by: string;
	edited_by_type: 'agent' | 'human';
	edited_at: string;
}

export interface QuestionListItem {
	question: Question;
	tags: { name: string }[];
	answer_count: number;
}

export interface QuestionListResponse {
	items: QuestionListItem[];
	total: number;
}

export interface AnswerThread {
	answer: Answer;
	comments: Comment[];
}

export interface QuestionThread {
	question: Question;
	tags: { name: string }[];
	comments: Comment[];
	answers: AnswerThread[];
	user_votes: Record<string, number>;
}

export interface SearchResult {
	question: Question;
	comments: Comment[];
	answers: AnswerThread[];
}

export interface SearchResponse {
	results: SearchResult[];
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
	type: 'proposed' | 'approved' | 'rejected';
	item_type: 'question' | 'answer' | 'comment';
	item_id: string;
	summary: string;
	created_by: string;
	supervised: boolean;
	timestamp: string;
}

export interface ReviewStats {
	total_questions: number;
	total_answers: number;
	total_pending: number;
	total_unanswered: number;
	tags: Tag[];
	recent_activity: ActivityEvent[];
	vote_distribution: { bucket: string; count: number }[];
	total_votes: number;
}
