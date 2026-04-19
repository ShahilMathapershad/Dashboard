'use strict';

/**
 * ZAR Dashboard — Interactions & Animations
 *
 * Philosophy: every visible state change is GPU-composited (opacity + transform only).
 * Apple-calibrated timing: cubic-bezier(0.16, 1, 0.3, 1)  — expo-out, silky landing.
 * Heavy UI logic runs here on the client; zero server round-trips for pure UI state.
 */

/* ─── Timing constants ─────────────────────────────────────────────────── */
const SPRING  = 'cubic-bezier(0.16, 1, 0.3, 1)';   // Expo-out — snappy, smooth landing
const SMOOTH  = 'cubic-bezier(0.25, 0.46, 0.45, 0.94)'; // Ease-out sine
const MIN_RESIZE_MS = 180;

document.addEventListener('DOMContentLoaded', () => {

    /* ── Three.js: only load on desktop (never parse 3800-line bundle on mobile) ── */
    const loadThreeIfDesktop = () => {
        const isDesktop = window.innerWidth > 1024 &&
                          !('ontouchstart' in window && window.innerWidth <= 1280);
        if (!isDesktop) {
            // Hide 3D container + particles on mobile — CSS gradient fallback
            const c = document.getElementById('three-canvas-landing');
            if (c) c.style.display = 'none';
            const p = document.querySelector('.particles-container');
            if (p && window.innerWidth <= 768) p.style.display = 'none';
            return;
        }
        // Desktop only: dynamically inject Three.js (non-render-blocking)
        if (!document.querySelector('script[src*="three-scenes"]')) {
            const s = document.createElement('script');
            s.src = '/assets/three-scenes.js';
            s.defer = true;
            document.head.appendChild(s);
        }
    };
    loadThreeIfDesktop();

    /* ── Login: Enter key + prevent native form submit ───────────────────── */
    const handleLoginEnterKey = () => {
        const bind = () => {
            // Prevent native form submission on all Dash forms (would reload the page)
            document.querySelectorAll('#login-form, #register-form').forEach((form) => {
                if (form.dataset.bound) return;
                form.dataset.bound = 'true';
                form.addEventListener('submit', (e) => {
                    e.preventDefault();
                    // Click the submit button inside this form
                    const btn = form.querySelector('button');
                    if (btn) btn.click();
                });
            });

            const user = document.getElementById('username');
            const pass = document.getElementById('password');
            const btn  = document.getElementById('login-button');
            if (!user || !pass || !btn) return;
            const onEnter = (e) => { if (e.key === 'Enter') { e.preventDefault(); btn.click(); } };
            // Replace listeners idempotently
            user.replaceEventListener?.('keydown', onEnter)
                ?? (user.removeEventListener('keydown', user._loginEnter),
                   user.addEventListener('keydown', user._loginEnter = onEnter));
            pass.replaceEventListener?.('keydown', onEnter)
                ?? (pass.removeEventListener('keydown', pass._loginEnter),
                   pass.addEventListener('keydown', pass._loginEnter = onEnter));
        };
        bind();
        new MutationObserver(bind).observe(document.body, { childList: true, subtree: true });
    };

    /* ── Plot: fade-in on first render — eliminates white-axes flash ────── */
    const managePlotFadeIn = () => {
        /**
         * Strategy:
         *  1. Mark every new .js-plotly-plot as .plot-loading (opacity: 0).
         *  2. Attach a plotly_afterplot listener. When Plotly finishes drawing
         *     and the figure has traces, remove .plot-loading → fade in.
         *  3. Fallback: poll for 2 s in case the event never fires (cached figures).
         */
        function setup(plot) {
            if (plot.dataset.fadeReady) return;
            plot.dataset.fadeReady = 'true';
            plot.classList.add('plot-loading');

            const reveal = () => {
                if (plot._fullData && plot._fullData.length > 0) {
                    requestAnimationFrame(() => plot.classList.remove('plot-loading'));
                    return true;
                }
                return false;
            };

            // Plotly event
            try { plot.on('plotly_afterplot', reveal); } catch (_) {}

            // Fallback poll (clears itself once revealed or timeout)
            let ticks = 0;
            const poll = setInterval(() => {
                if (reveal() || ++ticks > 20) clearInterval(poll);
            }, 100);
        }

        const scan = () => document.querySelectorAll('.js-plotly-plot').forEach(setup);
        scan();
        new MutationObserver(scan).observe(document.body, { childList: true, subtree: true });

        // Also re-reveal after every external plotlyResize (figure may have changed)
        window.addEventListener('plotlyResize', () => {
            document.querySelectorAll('.js-plotly-plot').forEach(plot => {
                if (plot._fullData && plot._fullData.length > 0) {
                    plot.classList.remove('plot-loading');
                }
            });
        });
    };

    /* ── Plotly resize — throttled, rAF-scheduled ───────────────────────── */
    const setupPlotResize = () => {
        let lastResize = 0;
        let rafHandle = null;

        const doResize = () => {
            rafHandle = null;
            const now = Date.now();
            if (now - lastResize < MIN_RESIZE_MS) return;
            lastResize = now;
            if (!window.Plotly) return;
            document.querySelectorAll('.js-plotly-plot').forEach(plot => {
                try { window.Plotly.Plots.resize(plot); } catch (_) {}
            });
        };

        const schedule = (delay = 0) => {
            if (delay) {
                setTimeout(() => {
                    if (!rafHandle) rafHandle = requestAnimationFrame(doResize);
                }, delay);
            } else {
                if (!rafHandle) rafHandle = requestAnimationFrame(doResize);
            }
        };

        // Window resize — debounced
        let resizeTimer;
        window.addEventListener('resize', () => {
            clearTimeout(resizeTimer);
            resizeTimer = setTimeout(() => schedule(), 120);
        }, { passive: true });

        // Custom event from Dash callbacks
        window.addEventListener('plotlyResize', () => schedule(50));

        // Tab navigation clicks
        document.addEventListener('click', (e) => {
            if (e.target.closest('#nav-data, #nav-model, #nav-scenario')) {
                schedule(300);  // After tab transition
            }
            if (e.target.closest('#toggle-table-btn')) {
                schedule(80);
            }
        });

        // Initial render
        schedule(300);
    };

    /* ── Predictor chips: staggered spring entrance ─────────────────────── */
    const observeChips = () => {
        new MutationObserver(() => {
            document.querySelectorAll('.predictor-checkbox-item:not([data-revealed])').forEach((chip, i) => {
                chip.dataset.revealed = 'true';
                chip.style.opacity = '0';
                chip.style.transform = 'translateY(8px) scale(0.96)';
                chip.style.willChange = 'opacity, transform';
                setTimeout(() => {
                    chip.style.transition = `opacity 0.25s ${SPRING}, transform 0.25s ${SPRING}`;
                    chip.style.opacity = '1';
                    chip.style.transform = 'translateY(0) scale(1)';
                    setTimeout(() => { chip.style.willChange = ''; }, 400);
                }, i * 30);
            });
        }).observe(document.body, { childList: true, subtree: true });
    };

    /* ── Landing page: SVG trendline injection ──────────────────────────── */
    const observeTrendline = () => {
        const inject = () => {
            const container = document.getElementById('bg-trendline-container');
            if (!container || container.dataset.injected) return;
            container.dataset.injected = 'true';
            container.innerHTML = `
                <svg viewBox="0 0 1200 500" preserveAspectRatio="none"
                     style="width:100%;height:100%;pointer-events:none;">
                    <defs>
                        <linearGradient id="tl-grad1" x1="0%" y1="0%" x2="100%" y2="0%">
                            <stop offset="0%"   style="stop-color:#5b8def;stop-opacity:0"/>
                            <stop offset="40%"  style="stop-color:#5b8def;stop-opacity:1"/>
                            <stop offset="100%" style="stop-color:#7c3aed;stop-opacity:0.6"/>
                        </linearGradient>
                        <linearGradient id="tl-grad2" x1="0%" y1="0%" x2="100%" y2="0%">
                            <stop offset="0%"   style="stop-color:#7c3aed;stop-opacity:0"/>
                            <stop offset="50%"  style="stop-color:#7c3aed;stop-opacity:0.7"/>
                            <stop offset="100%" style="stop-color:#5b8def;stop-opacity:0"/>
                        </linearGradient>
                    </defs>
                    <path class="trendline-path"
                          d="M0,380 C120,360 200,310 320,270 S500,240 620,260 S820,180 950,140 S1100,110 1200,90"
                          fill="none" stroke="url(#tl-grad1)" stroke-width="2" stroke-linecap="round"/>
                    <path d="M0,420 C150,400 280,370 400,340 S560,310 680,330 S880,270 1000,220 S1150,190 1200,170"
                          fill="none" stroke="url(#tl-grad2)" stroke-width="1.5" stroke-linecap="round"
                          stroke-dasharray="6 4" opacity="0.45"
                          style="animation:drawPath 10s ease-in-out 2s infinite"/>
                    <line x1="0" y1="150" x2="1200" y2="150" stroke="#5b8def" stroke-width="0.5" opacity="0.10"/>
                    <line x1="0" y1="300" x2="1200" y2="300" stroke="#5b8def" stroke-width="0.5" opacity="0.06"/>
                </svg>`;
        };
        inject();
        new MutationObserver(inject).observe(document.body, { childList: true, subtree: true });
    };

    /* ── Landing: scroll trendline + mouse parallax ─────────────────────── */
    window.addEventListener('scroll', () => {
        const path = document.querySelector('.trendline-path');
        if (!path) return;
        const scrollY = window.scrollY;
        if (scrollY > 10) {
            const maxScroll = Math.max(1, document.documentElement.scrollHeight - window.innerHeight);
            const pct = Math.min(1, scrollY / maxScroll);
            path.style.animation = 'none';
            path.style.strokeDashoffset = 2000 - (2000 * pct);
            path.style.opacity = String(0.15 + pct * 0.08);
        }
    }, { passive: true });

    window.addEventListener('mousemove', (e) => {
        const particles = document.querySelectorAll('.particle-node');
        if (!particles.length) return;
        const mx = e.clientX / window.innerWidth - 0.5;
        const my = e.clientY / window.innerHeight - 0.5;
        particles.forEach((p, i) => {
            const s = (i + 1) * 16;
            p.style.margin = `${my * s}px 0 0 ${mx * s}px`;
        });
    }, { passive: true });

    /* ── Stage: spring entrance on page load ────────────────────────────── */
    const initStageEntrance = () => {
        const run = () => {
            const landing = document.getElementById('landing-stage');
            if (!landing || landing.dataset.entered) return true; // done or already ran

            // Only animate if the stage is actually visible (has stage-active or no class yet)
            const isActive = landing.classList.contains('stage-active') ||
                             (!landing.classList.contains('stage-hidden'));
            if (!isActive) return true; // wrong state, don't retry

            landing.dataset.entered = 'true';
            landing.style.opacity = '0';
            landing.style.transform = 'translateY(16px)';
            landing.style.willChange = 'opacity, transform';

            // Double-rAF ensures paint is committed before transition starts
            requestAnimationFrame(() => {
                requestAnimationFrame(() => {
                    landing.style.transition = `opacity 0.8s ${SPRING}, transform 0.8s ${SPRING}`;
                    landing.style.opacity = '1';
                    landing.style.transform = 'translateY(0)';
                    setTimeout(() => { landing.style.willChange = ''; }, 1000);
                });
            });
            return true;
        };

        // Try immediately, then retry via observer if Dash hasn't rendered yet
        if (run()) return;
        let attempts = 0;
        const obs = new MutationObserver(() => {
            if (run() || ++attempts > 50) obs.disconnect();
        });
        obs.observe(document.body, { childList: true, subtree: true });
        // Hard fallback: force after 3s no matter what
        setTimeout(() => { obs.disconnect(); run(); }, 3000);
    };

    /* ── Slider marks: force-hide white boxes ───────────────────────────── */
    const hideSliderMarks = () => {
        const kill = (el) => {
            el.style.setProperty('display',        'none',   'important');
            el.style.setProperty('visibility',     'hidden', 'important');
            el.style.setProperty('height',         '0',      'important');
            el.style.setProperty('width',          '0',      'important');
            el.style.setProperty('opacity',        '0',      'important');
            el.style.setProperty('pointer-events', 'none',   'important');
        };
        const scan = () => document.querySelectorAll(
            '.rc-slider-mark, .rc-slider-dot, .rc-slider-tooltip, .rc-slider-step'
        ).forEach(kill);
        scan();
        new MutationObserver(scan).observe(document.body, { childList: true, subtree: true });
    };

    /* ── Scroll-triggered fade-in (IntersectionObserver) ───────────────── */
    const observeScrollAnimations = () => {
        const io = new IntersectionObserver((entries) => {
            entries.forEach(entry => {
                if (entry.isIntersecting) {
                    entry.target.classList.add('visible');
                    io.unobserve(entry.target);
                }
            });
        }, { threshold: 0.06, rootMargin: '0px 0px -24px 0px' });

        const attach = () =>
            document.querySelectorAll('.fade-in-up:not(.visible)').forEach(el => io.observe(el));
        attach();
        new MutationObserver(attach).observe(document.body, { childList: true, subtree: true });
    };

    /* ── Chart mode crossfade — smooth transition between plot modes ────── */
    const setupModeCrossfade = () => {
        document.addEventListener('click', (e) => {
            const btn = e.target.closest('.plot-mode-btn');
            if (!btn || btn.classList.contains('plot-mode-active')) return;

            const chart = document.querySelector('.hero-chart');
            if (!chart) return;

            // Phase 1: fade out
            chart.classList.remove('chart-fading-in');
            chart.classList.add('chart-fading');

            // Phase 2: after Dash updates the figure, fade back in
            // Listen for the next plotly_afterplot on the graph
            const plot = chart.querySelector('.js-plotly-plot');
            let revealed = false;

            const reveal = () => {
                if (revealed) return;
                revealed = true;
                chart.classList.remove('chart-fading');
                chart.classList.add('chart-fading-in');
                setTimeout(() => chart.classList.remove('chart-fading-in'), 600);
            };

            if (plot) {
                try { plot.once('plotly_afterplot', reveal); } catch (_) {}
            }

            // Fallback: if figure update takes too long or event doesn't fire
            setTimeout(reveal, 900);
        });
    };

    /* ── Mobile sidebar hamburger menu ──────────────────────────────────── */
    const setupMobileSidebar = () => {
        const openSidebar = () => {
            const sidebar = document.getElementById('sidebar');
            const overlay = document.getElementById('sidebar-overlay');
            if (sidebar) sidebar.classList.add('sidebar-mobile-open');
            if (overlay) overlay.classList.add('active');
            document.body.style.overflow = 'hidden';
        };
        const closeSidebar = () => {
            const sidebar = document.getElementById('sidebar');
            const overlay = document.getElementById('sidebar-overlay');
            if (sidebar) sidebar.classList.remove('sidebar-mobile-open');
            if (overlay) overlay.classList.remove('active');
            document.body.style.overflow = '';
        };

        document.addEventListener('click', (e) => {
            // Hamburger button opens sidebar
            if (e.target.closest('#mobile-menu-btn')) {
                e.stopPropagation();
                const sidebar = document.getElementById('sidebar');
                if (sidebar && sidebar.classList.contains('sidebar-mobile-open')) {
                    closeSidebar();
                } else {
                    openSidebar();
                }
                return;
            }
            // Overlay tap closes sidebar
            if (e.target.closest('#sidebar-overlay')) {
                closeSidebar();
                return;
            }
            // Clicking a nav link inside sidebar on mobile — close after a short delay
            if (e.target.closest('.nav-link-custom, .nav-link-profile') &&
                window.innerWidth <= 1024) {
                setTimeout(closeSidebar, 200);
            }
        });

        // Close mobile sidebar on window resize if going above breakpoint
        window.addEventListener('resize', () => {
            if (window.innerWidth > 1024) closeSidebar();
        }, { passive: true });
    };

    /* ── Init ────────────────────────────────────────────────────────────── */
    handleLoginEnterKey();
    managePlotFadeIn();
    setupPlotResize();
    observeChips();
    observeTrendline();
    hideSliderMarks();
    observeScrollAnimations();
    setupModeCrossfade();
    setupMobileSidebar();
    // Deferred — uses MutationObserver internally to wait for Dash render
    initStageEntrance();
});
