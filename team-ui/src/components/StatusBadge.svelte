<script lang="ts">
  let { status }: { status: string } = $props();

  const colorClass = $derived(() => {
    switch (status) {
      case 'approved': return 'bg-green-100 text-green-800';
      case 'rejected': return 'bg-red-100 text-red-800';
      case 'proposed':
      case 'pending': return 'bg-amber-100 text-amber-800';
      default: return 'bg-gray-100 text-gray-700';
    }
  });
</script>

<span class="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium {colorClass()}">
  {status}
</span>
