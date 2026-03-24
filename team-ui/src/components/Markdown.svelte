<script lang="ts">
  import { marked } from 'marked';

  let { content }: { content: string } = $props();

  const html = $derived(marked(content ?? '') as string);
</script>

<div class="markdown-content prose prose-sm max-w-none prose-headings:text-gray-900 prose-p:my-2 prose-li:my-0.5 prose-ul:my-2 prose-ol:my-2">
  {@html html}
</div>

<style>
  /* Inline code: subtle gray background */
  .markdown-content :global(code) {
    background: #e5e7eb;
    color: #1f2937;
    padding: 0.15em 0.4em;
    border-radius: 0.25rem;
    font-size: 0.8em;
  }
  .markdown-content :global(code::before),
  .markdown-content :global(code::after) {
    content: none;
  }

  /* Code blocks: dark theme, override inline code styles */
  .markdown-content :global(pre) {
    background: #111827;
    border-radius: 0.5rem;
    padding: 1rem;
    overflow-x: auto;
    margin: 0.75rem 0;
  }
  .markdown-content :global(pre code) {
    background: none;
    color: #e5e7eb;
    padding: 0;
    border-radius: 0;
    font-size: 0.8em;
    line-height: 1.6;
  }
</style>
