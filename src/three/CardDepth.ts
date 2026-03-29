/**
 * CardDepth — Adds subtle 3D depth parallax to model-card elements.
 *
 * Cards shift very slightly based on scroll position, creating a
 * layered, spatial feel without heavy WebGL overhead.
 * Uses IntersectionObserver for performance — only animates visible cards.
 */

const PARALLAX_FACTOR = 0.015;
const SPRING = 'cubic-bezier(0.16, 1, 0.3, 1)';

export class CardDepth {
  private visible: Set<HTMLElement> = new Set();
  private observer: IntersectionObserver;
  private mutObserver: MutationObserver;
  private scrollContainer: HTMLElement | null = null;
  private rafId = 0;
  private lastScroll = -1;

  constructor() {
    this.onScroll = this.onScroll.bind(this);
    this.tick = this.tick.bind(this);
    this.scan = this.scan.bind(this);

    this.observer = new IntersectionObserver(
      (entries) => {
        entries.forEach(e => {
          if (e.isIntersecting) this.visible.add(e.target as HTMLElement);
          else this.visible.delete(e.target as HTMLElement);
        });
      },
      { threshold: 0.05, rootMargin: '50px' }
    );

    this.scan();
    this.mutObserver = new MutationObserver(this.scan);
    this.mutObserver.observe(document.body, { childList: true, subtree: true });

    // Listen to the scrolling content area
    this.attachScroll();
  }

  private scan(): void {
    document.querySelectorAll<HTMLElement>('.model-card:not([data-depth])').forEach(el => {
      el.dataset.depth = '1';
      el.style.willChange = 'transform';
      el.style.transition = `transform 0.1s ${SPRING}`;
      this.observer.observe(el);
    });

    if (!this.scrollContainer) this.attachScroll();
  }

  private attachScroll(): void {
    const area = document.querySelector('.content-area');
    if (area) {
      this.scrollContainer = area as HTMLElement;
      this.scrollContainer.addEventListener('scroll', this.onScroll, { passive: true });
    }
  }

  private onScroll(): void {
    if (!this.rafId) this.rafId = requestAnimationFrame(this.tick);
  }

  private tick(): void {
    this.rafId = 0;
    if (!this.scrollContainer) return;
    const scroll = this.scrollContainer.scrollTop;
    if (scroll === this.lastScroll) return;
    this.lastScroll = scroll;

    this.visible.forEach(el => {
      const rect = el.getBoundingClientRect();
      const viewCenter = window.innerHeight / 2;
      const elCenter = rect.top + rect.height / 2;
      const offset = (elCenter - viewCenter) * PARALLAX_FACTOR;

      el.style.transform = `translateY(${offset.toFixed(1)}px)`;
    });
  }

  destroy(): void {
    this.observer.disconnect();
    this.mutObserver.disconnect();
    if (this.scrollContainer) {
      this.scrollContainer.removeEventListener('scroll', this.onScroll);
    }
    cancelAnimationFrame(this.rafId);
  }
}
