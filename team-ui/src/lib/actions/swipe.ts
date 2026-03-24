/**
 * Svelte action: attach swipe-to-decide behavior to any element.
 *
 * Usage:
 *   <div use:swipe={{ onLeft, onRight, onUp, threshold: 100 }}>
 *
 * The element follows the pointer, rotates slightly, and flies off
 * when the swipe exceeds the threshold. Snaps back otherwise.
 */
export interface SwipeOptions {
	onLeft?: () => void;
	onRight?: () => void;
	onUp?: () => void;
	threshold?: number;
}

export function swipe(node: HTMLElement, options: SwipeOptions) {
	let opts = options;
	let startX = 0;
	let startY = 0;
	let dx = 0;
	let dy = 0;
	let dragging = false;

	const threshold = () => opts.threshold ?? 120;

	function onPointerDown(e: PointerEvent) {
		if ((e.target as HTMLElement).closest('button, a, input, textarea')) return;
		dragging = true;
		startX = e.clientX;
		startY = e.clientY;
		dx = 0;
		dy = 0;
		node.style.transition = 'none';
		node.setPointerCapture(e.pointerId);
	}

	function onPointerMove(e: PointerEvent) {
		if (!dragging) return;
		dx = e.clientX - startX;
		dy = e.clientY - startY;
		const rotation = (dx / 400) * 8;
		node.style.transform = `translate(${dx}px, ${dy}px) rotate(${rotation}deg)`;
		node.style.opacity = String(1 - Math.min(Math.abs(dx) / (threshold() * 2), 0.4));
	}

	function onPointerUp() {
		if (!dragging) return;
		dragging = false;

		const absDx = Math.abs(dx);
		const absDy = Math.abs(dy);
		const t = threshold();

		if (absDx > t && absDx > absDy) {
			// Horizontal swipe — fly off
			const direction = dx > 0 ? 1 : -1;
			const flyX = direction * window.innerWidth;
			const flyRotation = direction * 30;
			node.style.transition = 'transform 300ms ease-in, opacity 300ms ease-in';
			node.style.transform = `translate(${flyX}px, ${dy}px) rotate(${flyRotation}deg)`;
			node.style.opacity = '0';
			setTimeout(() => {
				if (direction > 0) opts.onRight?.();
				else opts.onLeft?.();
				// Reset after callback
				node.style.transition = 'none';
				node.style.transform = '';
				node.style.opacity = '';
			}, 300);
		} else if (absDy > t && absDy > absDx && dy < 0) {
			// Upward swipe
			node.style.transition = 'transform 300ms ease-in, opacity 300ms ease-in';
			node.style.transform = `translate(0, ${-window.innerHeight}px)`;
			node.style.opacity = '0';
			setTimeout(() => {
				opts.onUp?.();
				node.style.transition = 'none';
				node.style.transform = '';
				node.style.opacity = '';
			}, 300);
		} else {
			// Snap back
			node.style.transition = 'transform 250ms ease-out, opacity 250ms ease-out';
			node.style.transform = '';
			node.style.opacity = '';
		}
	}

	node.addEventListener('pointerdown', onPointerDown);
	node.addEventListener('pointermove', onPointerMove);
	node.addEventListener('pointerup', onPointerUp);
	node.addEventListener('pointercancel', onPointerUp);
	node.style.touchAction = 'none';
	node.style.userSelect = 'none';

	return {
		update(newOptions: SwipeOptions) {
			opts = newOptions;
		},
		destroy() {
			node.removeEventListener('pointerdown', onPointerDown);
			node.removeEventListener('pointermove', onPointerMove);
			node.removeEventListener('pointerup', onPointerUp);
			node.removeEventListener('pointercancel', onPointerUp);
		}
	};
}
