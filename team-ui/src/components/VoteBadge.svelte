<script lang="ts">
  let {
    agent_upvotes = 0,
    agent_downvotes = 0,
    human_upvotes = 0,
    human_downvotes = 0,
  }: {
    agent_upvotes?: number;
    agent_downvotes?: number;
    human_upvotes?: number;
    human_downvotes?: number;
  } = $props();
</script>

<span class="inline-flex items-center gap-2 text-xs text-gray-500">
  <span class="flex items-center gap-0.5">
    <span class={agent_upvotes > 0 ? 'text-green-600' : 'text-gray-400'}>{agent_upvotes}↑</span>
    <span class={agent_downvotes > 0 ? 'text-red-500' : 'text-gray-400'}>{agent_downvotes}↓</span>
    <span class="text-gray-400">(agent)</span>
  </span>
  <span class="text-gray-300">·</span>
  <span class="flex items-center gap-0.5">
    <span class={human_upvotes > 0 ? 'text-green-600' : 'text-gray-400'}>{human_upvotes}↑</span>
    <span class={human_downvotes > 0 ? 'text-red-500' : 'text-gray-400'}>{human_downvotes}↓</span>
    <span class="text-gray-400">(human)</span>
  </span>
</span>
