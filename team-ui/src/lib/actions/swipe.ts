/**
 * Svelte action: attach swipe-to-decide behavior to any element.
 *
 * Usage:
 *   <div use:swipe={{ onLeft, onRight, onUp, threshold: 100 }}>
 *
 * Provides visual feedback as you drag:
 * - Green tint + "Approve ✓" label when dragging right
 * - Red tint + "Reject ✕" label when dragging left
 * - Gray tint + "Skip" label when dragging up
 * - Flies off screen on commit, snaps back otherwise
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
	let label: HTMLDivElement | null = null;

	const threshold = () => opts.threshold ?? 120;

	function createLabel() {
		label = document.createElement('div');
		label.style.cssText = `
			position: absolute;
			top: 50%;
			left: 50%;
			transform: translate(-50%, -50%);
			font-size: 1.25rem;
			font-weight: 700;
			letter-spacing: 0.05em;
			text-transform: uppercase;
			pointer-events: none;
			opacity: 0;
			transition: opacity 100ms ease;
			z-index: 10;
			padding: 0.5rem 1.5rem;
			border-radius: 0.5rem;
			border: 3px solid transparent;
		`;
		node.style.position = 'relative';
		node.appendChild(label);
	}

	function updateLabel(progress: number, direction: 'left' | 'right' | 'up' | 'none') {
		if (!label) return;
		const opacity = Math.min(progress * 1.5, 1);
		label.style.opacity = String(opacity);

		if (direction === 'right') {
			label.textContent = '✓ Approve';
			label.style.color = '#15803d';
			label.style.borderColor = '#15803d';
			label.style.backgroundColor = 'rgba(220, 252, 231, 0.95)';
		} else if (direction === 'left') {
			label.textContent = '✕ Reject';
			label.style.color = '#dc2626';
			label.style.borderColor = '#dc2626';
			label.style.backgroundColor = 'rgba(254, 226, 226, 0.95)';
		} else if (direction === 'up') {
			label.textContent = '— Skip';
			label.style.color = '#475569';
			label.style.borderColor = '#475569';
			label.style.backgroundColor = 'rgba(241, 245, 249, 0.95)';
		} else {
			label.style.opacity = '0';
		}
	}

	function getDirection(
		currentDx: number,
		currentDy: number,
	): 'left' | 'right' | 'up' | 'none' {
		const absDx = Math.abs(currentDx);
		const absDy = Math.abs(currentDy);
		const t = threshold() * 0.3; // start showing feedback early
		if (absDx > t && absDx > absDy) return currentDx > 0 ? 'right' : 'left';
		if (absDy > t && absDy > absDx && currentDy < 0) return 'up';
		return 'none';
	}

	function getTint(direction: 'left' | 'right' | 'up' | 'none', progress: number): string {
		const alpha = Math.min(progress * 0.15, 0.12);
		if (direction === 'right') return `rgba(34, 197, 94, ${alpha})`;
		if (direction === 'left') return `rgba(239, 68, 68, ${alpha})`;
		if (direction === 'up') return `rgba(100, 116, 139, ${alpha})`;
		return 'transparent';
	}

	function getBorderColor(direction: 'left' | 'right' | 'up' | 'none', progress: number): string {
		const alpha = Math.min(progress * 0.8, 0.6);
		if (direction === 'right') return `rgba(34, 197, 94, ${alpha})`;
		if (direction === 'left') return `rgba(239, 68, 68, ${alpha})`;
		if (direction === 'up') return `rgba(100, 116, 139, ${alpha})`;
		return '';
	}

	function onPointerDown(e: PointerEvent) {
		if ((e.target as HTMLElement).closest('button, a, input, textarea')) return;
		dragging = true;
		startX = e.clientX;
		startY = e.clientY;
		dx = 0;
		dy = 0;
		node.style.transition = 'none';
		node.setPointerCapture(e.pointerId);
		if (!label) createLabel();
	}

	function onPointerMove(e: PointerEvent) {
		if (!dragging) return;
		dx = e.clientX - startX;
		dy = e.clientY - startY;

		const rotation = (dx / 400) * 6;
		const t = threshold();
		const progress = Math.max(Math.abs(dx), Math.abs(dy)) / t;
		const direction = getDirection(dx, dy);

		node.style.transform = `translate(${dx}px, ${dy}px) rotate(${rotation}deg)`;
		node.style.backgroundColor = getTint(direction, progress);

		const border = getBorderColor(direction, progress);
		if (border) {
			node.style.borderColor = border;
		}

		// Shadow grows with drag distance
		const shadowBlur = 8 + progress * 20;
		const shadowAlpha = 0.08 + progress * 0.08;
		node.style.boxShadow = `0 ${4 + progress * 8}px ${shadowBlur}px rgba(0,0,0,${shadowAlpha})`;

		updateLabel(progress, direction);
	}

	function onPointerUp() {
		if (!dragging) return;
		dragging = false;

		// Hide label
		if (label) label.style.opacity = '0';

		const absDx = Math.abs(dx);
		const absDy = Math.abs(dy);
		const t = threshold();

		if (absDx > t && absDx > absDy) {
			// Horizontal swipe — fly off
			const direction = dx > 0 ? 1 : -1;
			const flyX = direction * window.innerWidth;
			const flyRotation = direction * 25;
			node.style.transition =
				'transform 300ms ease-in, opacity 300ms ease-in, background-color 300ms ease-in';
			node.style.transform = `translate(${flyX}px, ${dy}px) rotate(${flyRotation}deg)`;
			node.style.opacity = '0';
			setTimeout(() => {
				if (direction > 0) opts.onRight?.();
				else opts.onLeft?.();
				resetStyles();
			}, 300);
		} else if (absDy > t && absDy > absDx && dy < 0) {
			// Upward swipe
			node.style.transition =
				'transform 300ms ease-in, opacity 300ms ease-in, background-color 300ms ease-in';
			node.style.transform = `translate(0, ${-window.innerHeight}px)`;
			node.style.opacity = '0';
			setTimeout(() => {
				opts.onUp?.();
				resetStyles();
			}, 300);
		} else {
			// Snap back
			node.style.transition =
				'transform 250ms ease-out, opacity 250ms ease-out, background-color 250ms ease-out, border-color 250ms ease-out, box-shadow 250ms ease-out';
			resetStyles();
		}
	}

	function resetStyles() {
		node.style.transform = '';
		node.style.opacity = '';
		node.style.backgroundColor = '';
		node.style.borderColor = '';
		node.style.boxShadow = '';
	}

	node.addEventListener('pointerdown', onPointerDown);
	node.addEventListener('pointermove', onPointerMove);
	node.addEventListener('pointerup', onPointerUp);
	node.addEventListener('pointercancel', onPointerUp);
	node.style.touchAction = 'none';
	node.style.userSelect = 'none';
	node.style.cursor = 'grab';

	return {
		update(newOptions: SwipeOptions) {
			opts = newOptions;
		},
		destroy() {
			node.removeEventListener('pointerdown', onPointerDown);
			node.removeEventListener('pointermove', onPointerMove);
			node.removeEventListener('pointerup', onPointerUp);
			node.removeEventListener('pointercancel', onPointerUp);
			if (label) {
				label.remove();
				label = null;
			}
		},
	};
}
