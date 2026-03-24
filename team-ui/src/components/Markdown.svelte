<script lang="ts">
  import { marked } from 'marked';

  let { content }: { content: string } = $props();

  const html = $derived(marked(content ?? '') as string);
</script>

<div
  class="prose prose-sm max-w-none
    prose-headings:text-gray-900
    prose-code:text-gray-900
    prose-code:bg-gray-200
    prose-code:px-1.5
    prose-code:py-0.5
    prose-code:rounded
    prose-code:text-xs
    prose-code:before:content-none
    prose-code:after:content-none
    prose-pre:bg-gray-900
    prose-pre:text-gray-100
    prose-pre:text-xs
    prose-pre:rounded-lg
    prose-p:my-2
    prose-li:my-0.5
    prose-ul:my-2
    prose-ol:my-2"
>
  {@html html}
</div>
