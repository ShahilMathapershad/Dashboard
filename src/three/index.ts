/**
 * Dash 3D Scenes — Entry Point
 *
 * Auto-detects the current page and initializes the appropriate
 * Three.js scenes and interaction modules.
 *
 * Landing page  → LandingScene (3D globe + flowing mesh)
 * Dashboard     → ChartTilt + CardDepth (interactive 3D depth)
 */

import { LandingScene } from './LandingScene';
import { ChartTilt } from './ChartTilt';
import { CardDepth } from './CardDepth';

let landingScene: LandingScene | null = null;
let chartTilt: ChartTilt | null = null;
let cardDepth: CardDepth | null = null;

function initLanding(): void {
  const container = document.getElementById('three-canvas-landing');
  if (!container || landingScene) return;

  // Only init if container is visible (not display:none)
  const rect = container.getBoundingClientRect();
  if (rect.width === 0 || rect.height === 0) return;

  landingScene = new LandingScene(container);
}

function initDashboard(): void {
  if (!chartTilt) chartTilt = new ChartTilt();
  if (!cardDepth) cardDepth = new CardDepth();
}

function detectAndInit(): void {
  // Landing page
  const landingContainer = document.getElementById('three-canvas-landing');
  if (landingContainer) {
    initLanding();
  }

  // Dashboard
  const dashContainer = document.getElementById('dashboard-container');
  if (dashContainer) {
    initDashboard();
  }
}

// ── Boot ──
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', detectAndInit);
} else {
  detectAndInit();
}

// Re-check on Dash SPA navigation (pages load dynamically)
const pageObserver = new MutationObserver(() => {
  // Debounce
  clearTimeout((pageObserver as any)._timer);
  (pageObserver as any)._timer = setTimeout(detectAndInit, 100);
});
pageObserver.observe(document.body, { childList: true, subtree: true });

// Cleanup on page unload
window.addEventListener('beforeunload', () => {
  landingScene?.destroy();
  chartTilt?.destroy();
  cardDepth?.destroy();
  pageObserver.disconnect();
});

// Export for debugging
(window as any).DashScenes = { landingScene, chartTilt, cardDepth };
