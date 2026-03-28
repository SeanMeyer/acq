import { sveltekit } from '@sveltejs/kit/vite';
import tailwindcss from '@tailwindcss/vite';
import { defineConfig } from 'vite';

export default defineConfig({
	plugins: [tailwindcss(), sveltekit()],
	server: {
		host: '0.0.0.0',
		port: 3000,
		allowedHosts: ['smeyer-1.workspace.infra.dog'],
		proxy: {
			'/api/questions': {
				target: 'http://localhost:8000'
			},
			'/auth': {
				target: 'http://localhost:8000'
			},
			'/review': {
				target: 'http://localhost:8000'
			},
			'/health': {
				target: 'http://localhost:8000'
			},
			'/status': {
				target: 'http://localhost:8000'
			},
			'/search': {
				target: 'http://localhost:8000'
			},
			'/tags': {
				target: 'http://localhost:8000'
			}
		}
	}
});
