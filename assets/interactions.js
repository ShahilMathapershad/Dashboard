// Minimal interactions for premium dashboard
// No gimmicky effects - just smooth, functional enhancements

document.addEventListener('DOMContentLoaded', function () {
    // Handle Enter key for login form
    const handleLoginEnterKey = () => {
        const addEnterKeyListeners = () => {
            const usernameInput = document.getElementById('username');
            const passwordInput = document.getElementById('password');
            const loginButton = document.getElementById('login-button');

            if (usernameInput && passwordInput && loginButton) {
                const handleEnter = (e) => {
                    if (e.key === 'Enter') {
                        e.preventDefault();
                        // Trigger login button click
                        loginButton.click();
                    }
                };

                // Remove existing listeners to avoid duplicates
                usernameInput.removeEventListener('keydown', handleEnter);
                passwordInput.removeEventListener('keydown', handleEnter);
                
                // Add new listeners
                usernameInput.addEventListener('keydown', handleEnter);
                passwordInput.addEventListener('keydown', handleEnter);
            }
        };

        // Initial check
        addEnterKeyListeners();

        // Watch for DOM changes (Dash is a SPA, elements may be added/removed)
        const observer = new MutationObserver(() => {
            addEnterKeyListeners();
        });

        observer.observe(document.body, { childList: true, subtree: true });
    };

    // Stagger fade-in for predictor chips when they appear
    const observeChips = () => {
        const observer = new MutationObserver(() => {
            const chips = document.querySelectorAll('.predictor-checkbox-item');
            chips.forEach((chip, i) => {
                if (!chip.dataset.revealed) {
                    chip.dataset.revealed = 'true';
                    chip.style.opacity = '0';
                    chip.style.transform = 'translateY(4px)';
                    setTimeout(() => {
                        chip.style.transition = 'opacity 0.2s ease, transform 0.2s ease';
                        chip.style.opacity = '1';
                        chip.style.transform = 'translateY(0)';
                    }, i * 30);
                }
            });
        });

        observer.observe(document.body, { childList: true, subtree: true });
    };

    const observeChartVisibility = () => {
        let resizeInProgress = false;
        let lastResizeTime = 0;
        const MIN_RESIZE_INTERVAL = 200; // Minimum time between resizes

        const resizePlot = () => {
            if (resizeInProgress) return;
            
            const now = Date.now();
            if (now - lastResizeTime < MIN_RESIZE_INTERVAL) return;
            
            resizeInProgress = true;
            lastResizeTime = now;
            
            try {
                const plots = document.querySelectorAll('.js-plotly-plot');
                plots.forEach((plot) => {
                    // Get the graph div (dcc.Graph component)
                    const graphDiv = plot.closest('.dash-graph');
                    if (!graphDiv) return;
                    
                    // Use the graph div's computed style height if available
                    const graphStyle = getComputedStyle(graphDiv);
                    const graphHeight = graphDiv.offsetHeight;
                    const graphWidth = graphDiv.offsetWidth;
                    
                    if (graphHeight > 0 && graphWidth > 0) {
                        // Use the container's actual dimensions
                        plot.style.width = '100%';
                        plot.style.height = '100%';
                        
                        // Update plotly layout to match container
                        if (window.Plotly && typeof window.Plotly.relayout === 'function') {
                            window.Plotly.relayout(plot, {
                                height: graphHeight,
                                width: graphWidth,
                                autosize: true
                            });
                        }
                    }
                    
                    // Always call resize to ensure proper rendering
                    if (window.Plotly && typeof window.Plotly.Plots.resize === 'function') {
                        window.Plotly.Plots.resize(plot);
                    }
                });
            } finally {
                resizeInProgress = false;
            }
        };

        const checkAndResize = () => {
            // Check for any visualization container or plotly plots
            const containers = document.querySelectorAll('#visualization-container, .model-chart, .js-plotly-plot');
            let hasVisibleContainer = false;
            
            containers.forEach(el => {
                const container = el.closest('#visualization-container') || el;
                const isVisible = container.offsetParent !== null && getComputedStyle(container).display !== 'none';
                if (isVisible) {
                    hasVisibleContainer = true;
                }
            });
            
            if (hasVisibleContainer) {
                requestAnimationFrame(() => {
                    setTimeout(resizePlot, 100);
                });
            }
        };

        // Debounced observer to prevent excessive calls
        let observerTimeout;
        const observer = new MutationObserver(() => {
            clearTimeout(observerTimeout);
            observerTimeout = setTimeout(checkAndResize, 50);
        });

        // More targeted observation - only watch for specific changes
        observer.observe(document.body, { 
            childList: true, 
            subtree: true,
            attributes: false  // Remove attribute watching to reduce frequency
        });
        
        // Initial check on load
        setTimeout(checkAndResize, 200);
        
        // Debounced window resize handler
        let resizeTimeout;
        window.addEventListener('resize', () => {
            clearTimeout(resizeTimeout);
            resizeTimeout = setTimeout(resizePlot, 150);
        });
    };

    // Scroll-based trendline drawing for landing page
    const handleTrendlineScroll = () => {
        const path = document.querySelector('.trendline-path');
        if (path) {
            const scrollY = window.scrollY;
            const maxScroll = Math.max(1, document.documentElement.scrollHeight - window.innerHeight);
            const scrollPercent = Math.min(1, scrollY / maxScroll);
            
            // Only use scroll-based drawing if the user has actually scrolled
            // Otherwise, let the CSS animation handle it or keep it at start
            if (scrollY > 10) {
                path.style.animation = 'none';
                const drawLength = 2000 * scrollPercent;
                path.style.strokeDashoffset = 2000 - drawLength;
                path.style.opacity = 0.15 + (scrollPercent * 0.1);
            }
        }
    };

    window.addEventListener('scroll', handleTrendlineScroll);
    
    // Mouse-aware parallax for particles
    const handleParticleParallax = (e) => {
        const particles = document.querySelectorAll('.particle-node');
        const mouseX = e.clientX / window.innerWidth;
        const mouseY = e.clientY / window.innerHeight;
        
        particles.forEach((p, i) => {
            const speed = (i + 1) * 20;
            const x = (mouseX - 0.5) * speed;
            const y = (mouseY - 0.5) * speed;
            // Combine with existing floating animation via CSS variable or direct transform
            // For simplicity, we'll just use a subtle translate
            p.style.margin = `${y}px 0 0 ${x}px`;
        });
    };

    window.addEventListener('mousemove', handleParticleParallax);

    // Inject background trendline SVG dynamically to avoid Dash 4.0.0 limitations with html.Svg
    const observeTrendline = () => {
        const injectSVG = () => {
            const container = document.getElementById('bg-trendline-container');
            if (container && !container.dataset.injected) {
                container.dataset.injected = 'true';
                container.innerHTML = `
                    <svg viewBox="0 0 1200 500" preserveAspectRatio="none" style="width: 100%; height: 100%; pointer-events: none;">
                        <defs>
                            <linearGradient id="tl-grad1" x1="0%" y1="0%" x2="100%" y2="0%">
                                <stop offset="0%" style="stop-color:#5b8def;stop-opacity:0"/>
                                <stop offset="40%" style="stop-color:#5b8def;stop-opacity:1"/>
                                <stop offset="100%" style="stop-color:#7c3aed;stop-opacity:0.6"/>
                            </linearGradient>
                            <linearGradient id="tl-grad2" x1="0%" y1="0%" x2="100%" y2="0%">
                                <stop offset="0%" style="stop-color:#7c3aed;stop-opacity:0"/>
                                <stop offset="50%" style="stop-color:#7c3aed;stop-opacity:0.7"/>
                                <stop offset="100%" style="stop-color:#5b8def;stop-opacity:0"/>
                            </linearGradient>
                        </defs>
                        <!-- Primary trend line -->
                        <path
                            class="trendline-path"
                            d="M0,380 C120,360 200,310 320,270 S500,240 620,260 S820,180 950,140 S1100,110 1200,90"
                            fill="none"
                            stroke="url(#tl-grad1)"
                            stroke-width="2"
                            stroke-linecap="round">
                        </path>
                        <!-- Secondary decorative line -->
                        <path
                            d="M0,420 C150,400 280,370 400,340 S560,310 680,330 S880,270 1000,220 S1150,190 1200,170"
                            fill="none"
                            stroke="url(#tl-grad2)"
                            stroke-width="1.5"
                            stroke-linecap="round"
                            stroke-dasharray="6 4"
                            opacity="0.5"
                            style="animation: drawPath 10s ease-in-out 2s infinite">
                        </path>
                        <!-- Subtle grid lines -->
                        <line x1="0" y1="150" x2="1200" y2="150" stroke="#5b8def" stroke-width="0.5" opacity="0.15"/>
                        <line x1="0" y1="300" x2="1200" y2="300" stroke="#5b8def" stroke-width="0.5" opacity="0.1"/>
                    </svg>
                `;
            }
        };

        // Initial check
        injectSVG();

        // Watch for DOM changes (Dash is a SPA)
        const observer = new MutationObserver(() => {
            injectSVG();
        });

        observer.observe(document.body, { childList: true, subtree: true });
    };

    // Force hide slider marks (white boxes)
    const hideSliderMarks = () => {
        const marks = document.querySelectorAll('.rc-slider-mark, .rc-slider-dot, .rc-slider-tooltip, .rc-slider-step');
        marks.forEach(mark => {
            mark.style.setProperty('display', 'none', 'important');
            mark.style.setProperty('visibility', 'hidden', 'important');
            mark.style.setProperty('height', '0', 'important');
            mark.style.setProperty('width', '0', 'important');
            mark.style.setProperty('opacity', '0', 'important');
            mark.style.setProperty('pointer-events', 'none', 'important');
        });
    };

    // Observer to continuously hide slider marks
    const observeSliders = () => {
        hideSliderMarks();
        
        const observer = new MutationObserver(() => {
            hideSliderMarks();
        });

        observer.observe(document.body, { childList: true, subtree: true });
    };

    // Scroll-triggered fade-in animations using IntersectionObserver
    const observeScrollAnimations = () => {
        const io = new IntersectionObserver((entries) => {
            entries.forEach(entry => {
                if (entry.isIntersecting) {
                    entry.target.classList.add('visible');
                    io.unobserve(entry.target);
                }
            });
        }, { threshold: 0.08, rootMargin: '0px 0px -30px 0px' });

        const attachObserver = () => {
            document.querySelectorAll('.fade-in-up:not(.visible)').forEach(el => {
                io.observe(el);
            });
        };

        attachObserver();

        const domWatcher = new MutationObserver(() => {
            attachObserver();
        });
        domWatcher.observe(document.body, { childList: true, subtree: true });
    };

    handleLoginEnterKey();
    observeChips();
    observeChartVisibility();
    observeTrendline();
    observeSliders();
    observeScrollAnimations();
    
    // Listen for custom plotly resize events from Dash callbacks
    window.addEventListener('plotlyResize', () => {
        const plots = document.querySelectorAll('.js-plotly-plot');
        plots.forEach((plot) => {
            if (window.Plotly && typeof window.Plotly.Plots.resize === 'function') {
                window.Plotly.Plots.resize(plot);
            }
        });
    });
    
    // Optimized navigation resize handler
    document.addEventListener('click', (e) => {
        if (e.target.closest('#nav-data') || e.target.closest('#nav-model') || e.target.closest('#nav-scenario')) {
            // Use a single delayed resize instead of multiple calls
            setTimeout(() => {
                window.dispatchEvent(new Event('plotlyResize'));
            }, 300); // Single delay for tab transition
        }
        
        // Also trigger resize when toggle table button is clicked
        if (e.target.closest('#toggle-table-btn')) {
            setTimeout(() => {
                window.dispatchEvent(new Event('plotlyResize'));
            }, 100); // Shorter delay for immediate feedback
        }
    });
});
