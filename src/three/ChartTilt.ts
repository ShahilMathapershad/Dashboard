/**
 * ChartTilt — Apple-style interactive 3D tilt for chart containers.
 *
 * On hover, chart panels tilt gently to follow the cursor, creating a
 * spatial, floating-card feel. On leave, they spring back smoothly.
 * Also adds a glass-shine highlight that follows the cursor.
 *
 * Apply the `chart-3d` class to any container you want to tilt.
 */

const MAX_TILT      = 3;      // degrees
const SPRING        = 'cubic-bezier(0.16, 1, 0.3, 1)';
const SPRING_DUR    = '0.6s';
const SHINE_SIZE    = 280;    // px — diameter of the shine highlight

interface TiltState {
  el: HTMLElement;
  shine: HTMLDivElement;
  bound: boolean;
}

export class ChartTilt {
  private elements: Map<HTMLElement, TiltState> = new Map();
  private observer: MutationObserver;

  constructor() {
    this.scan = this.scan.bind(this);
    this.scan();

    this.observer = new MutationObserver(this.scan);
    this.observer.observe(document.body, { childList: true, subtree: true });
  }

  private scan(): void {
    document.querySelectorAll<HTMLElement>('.chart-3d').forEach((el) => {
      if (this.elements.has(el)) return;

      // Create shine overlay
      const shine = document.createElement('div');
      shine.className = 'chart-3d-shine';
      el.style.position = 'relative';
      el.style.overflow = 'hidden';
      el.appendChild(shine);

      const state: TiltState = { el, shine, bound: true };
      this.elements.set(el, state);

      el.addEventListener('mousemove', (e: MouseEvent) => this.onMove(state, e), { passive: true });
      el.addEventListener('mouseleave', () => this.onLeave(state), { passive: true });
      el.addEventListener('mouseenter', () => this.onEnter(state), { passive: true });
    });
  }

  private onEnter(state: TiltState): void {
    state.el.style.transition = 'none';
    state.shine.style.opacity = '1';
  }

  private onMove(state: TiltState, e: MouseEvent): void {
    const rect = state.el.getBoundingClientRect();
    const x = (e.clientX - rect.left) / rect.width - 0.5;  // -0.5 → 0.5
    const y = (e.clientY - rect.top) / rect.height - 0.5;

    const tiltX = -y * MAX_TILT;
    const tiltY = x * MAX_TILT;

    state.el.style.transform =
      `perspective(1200px) rotateX(${tiltX.toFixed(2)}deg) rotateY(${tiltY.toFixed(2)}deg) translateZ(4px)`;

    // Move shine highlight
    const shineX = e.clientX - rect.left - SHINE_SIZE / 2;
    const shineY = e.clientY - rect.top - SHINE_SIZE / 2;
    state.shine.style.transform = `translate(${shineX}px, ${shineY}px)`;
  }

  private onLeave(state: TiltState): void {
    state.el.style.transition = `transform ${SPRING_DUR} ${SPRING}`;
    state.el.style.transform = 'perspective(1200px) rotateX(0) rotateY(0) translateZ(0)';
    state.shine.style.opacity = '0';
  }

  destroy(): void {
    this.observer.disconnect();
    this.elements.clear();
  }
}
