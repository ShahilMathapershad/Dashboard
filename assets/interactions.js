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
                    // Calculate size based on container
                    const container = plot.closest('.model-card, .viz-container');
                    if (container) {
                        const containerRect = container.getBoundingClientRect();
                        
                        // Dynamic padding calculation based on visible elements
                        let padding = 130; // Base padding for headers/padding/selector
                        
                        // Add extra space if table is visible in the same container
                        const tableCard = container.querySelector('.table-card');
                        if (tableCard && getComputedStyle(tableCard).display !== 'none') {
                            const tableRect = tableCard.getBoundingClientRect();
                            // Add table height plus gap between elements
                            padding += tableRect.height + 20; // 20px for gap
                        }
                        
                        const plotHeight = Math.max(300, containerRect.height - padding);
                        const plotWidth = Math.max(400, containerRect.width - 40);
                        
                        plot.style.width = '100%';
                        plot.style.height = plotHeight + 'px';
                        
                        // Also update the plotly layout if possible
                        if (window.Plotly && typeof window.Plotly.relayout === 'function') {
                            window.Plotly.relayout(plot, {
                                height: plotHeight,
                                width: plotWidth,
                                autosize: true
                            });
                        }
                    }
                    if (window.Plotly && typeof window.Plotly.Plots.resize === 'function') {
                        window.Plotly.Plots.resize(plot);
                    }
                });
                // Don't trigger window resize event to avoid loops
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
                    <svg viewBox="0 0 1000 400" style="width: 100%; height: 100%; pointer-events: none;">
                        <path 
                            class="trendline-path" 
                            d="M0,350 Q100,340 200,300 T400,250 T600,280 T800,150 T1000,100" 
                            fill="none" 
                            stroke="#5b8def" 
                            stroke-width="2">
                        </path>
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

    handleLoginEnterKey();
    observeChips();
    observeChartVisibility();
    observeTrendline();
    
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
        if (e.target.closest('#nav-data') || e.target.closest('#nav-model')) {
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
