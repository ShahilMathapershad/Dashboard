// Premium Interactions for 2026 Fintech Dashboard
// Enhanced animations and smooth user experiences

document.addEventListener('DOMContentLoaded', function() {
    // Parallax effect for dashboard cards on hover
    const initCardParallax = () => {
        const cards = document.querySelectorAll('.dashboard-card');
        
        cards.forEach(card => {
            card.addEventListener('mousemove', (e) => {
                const rect = card.getBoundingClientRect();
                const x = ((e.clientX - rect.left) / rect.width) * 2 - 1;
                const y = ((e.clientY - rect.top) / rect.height) * 2 - 1;
                
                const tiltX = y * 2; // Max 2 degrees
                const tiltY = -x * 2;
                
                card.style.transform = `perspective(1000px) rotateX(${tiltX}deg) rotateY(${tiltY}deg) translateZ(10px)`;
            });
            
            card.addEventListener('mouseleave', () => {
                card.style.transform = 'perspective(1000px) rotateX(0) rotateY(0) translateZ(0)';
            });
        });
    };

    // Smooth number animations for data updates
    const animateNumber = (element, start, end, duration = 1000) => {
        const startTime = Date.now();
        const difference = end - start;
        
        const animate = () => {
            const elapsed = Date.now() - startTime;
            const progress = Math.min(elapsed / duration, 1);
            
            // Easing function for smooth animation
            const easeOutQuart = 1 - Math.pow(1 - progress, 4);
            const current = start + (difference * easeOutQuart);
            
            element.textContent = current.toFixed(4);
            
            if (progress < 1) {
                requestAnimationFrame(animate);
            }
        };
        
        animate();
    };

    // Enhanced dropdown interactions
    const enhanceDropdowns = () => {
        const dropdownControls = document.querySelectorAll('.custom-dropdown-control');
        
        dropdownControls.forEach(control => {
            // Add ripple effect on click
            control.addEventListener('click', function(e) {
                const ripple = document.createElement('span');
                ripple.className = 'dropdown-ripple';
                
                const rect = this.getBoundingClientRect();
                const size = Math.max(rect.width, rect.height);
                const x = e.clientX - rect.left - size / 2;
                const y = e.clientY - rect.top - size / 2;
                
                ripple.style.width = ripple.style.height = size + 'px';
                ripple.style.left = x + 'px';
                ripple.style.top = y + 'px';
                
                this.appendChild(ripple);
                
                setTimeout(() => ripple.remove(), 600);
            });
        });
    };

    // Smooth scroll with momentum
    const initSmoothScroll = () => {
        let isScrolling = false;
        let startY = 0;
        let currentY = 0;
        let touchY = 0;
        let momentum = 0;
        
        const scrollContainer = document.querySelector('.content-area');
        if (!scrollContainer) return;
        
        const updateScroll = () => {
            if (isScrolling) {
                const diff = touchY - currentY;
                currentY = touchY;
                momentum = diff * 0.9;
                scrollContainer.scrollTop -= diff;
                requestAnimationFrame(updateScroll);
            } else if (Math.abs(momentum) > 0.1) {
                momentum *= 0.95;
                scrollContainer.scrollTop -= momentum;
                requestAnimationFrame(updateScroll);
            }
        };
        
        scrollContainer.addEventListener('touchstart', (e) => {
            isScrolling = true;
            startY = currentY = touchY = e.touches[0].clientY;
            momentum = 0;
        });
        
        scrollContainer.addEventListener('touchmove', (e) => {
            if (isScrolling) {
                touchY = e.touches[0].clientY;
            }
        });
        
        scrollContainer.addEventListener('touchend', () => {
            isScrolling = false;
        });
        
        updateScroll();
    };

    // Loading state animations
    const enhanceLoadingStates = () => {
        // Observe when loading states appear
        const observer = new MutationObserver((mutations) => {
            mutations.forEach((mutation) => {
                if (mutation.type === 'childList') {
                    mutation.addedNodes.forEach((node) => {
                        if (node.nodeType === 1) { // Element node
                            // Check for progress containers
                            if (node.id === 'progress-container' || node.querySelector('#progress-container')) {
                                animateProgressBar();
                            }
                            // Check for shimmer cards
                            if (node.classList && node.classList.contains('shimmer-card')) {
                                addShimmerPulse(node);
                            }
                        }
                    });
                }
            });
        });
        
        observer.observe(document.body, {
            childList: true,
            subtree: true
        });
    };

    // Animate progress bar with spring physics
    const animateProgressBar = () => {
        const progressBar = document.querySelector('#fetch-progress-bar .progress-bar');
        if (progressBar) {
            progressBar.style.transition = 'width 0.6s cubic-bezier(0.34, 1.56, 0.64, 1)';
        }
    };

    // Add pulse effect to shimmer cards
    const addShimmerPulse = (element) => {
        element.style.animation = 'shimmerPulse 2s ease-in-out infinite';
    };

    // Chart hover effects
    const enhanceCharts = () => {
        // Add hover glow to plotly charts
        const observer = new MutationObserver((mutations) => {
            const charts = document.querySelectorAll('.js-plotly-plot');
            charts.forEach(chart => {
                if (!chart.dataset.enhanced) {
                    chart.dataset.enhanced = 'true';
                    
                    chart.addEventListener('mouseenter', () => {
                        chart.style.filter = 'drop-shadow(0 8px 32px rgba(91, 141, 239, 0.2))';
                        chart.style.transform = 'scale(1.01)';
                    });
                    
                    chart.addEventListener('mouseleave', () => {
                        chart.style.filter = '';
                        chart.style.transform = '';
                    });
                }
            });
        });
        
        observer.observe(document.body, {
            childList: true,
            subtree: true
        });
    };

    // Initialize all enhancements
    const init = () => {
        initCardParallax();
        enhanceDropdowns();
        initSmoothScroll();
        enhanceLoadingStates();
        enhanceCharts();
        
        // Re-initialize on page changes (for Dash SPA navigation)
        const pageObserver = new MutationObserver(() => {
            setTimeout(() => {
                initCardParallax();
                enhanceDropdowns();
            }, 100);
        });
        
        const contentArea = document.querySelector('#content-body');
        if (contentArea) {
            pageObserver.observe(contentArea, {
                childList: true,
                subtree: true
            });
        }
    };
    
    // Start when DOM is ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
});

// Add CSS for ripple effect
const style = document.createElement('style');
style.textContent = `
    .dropdown-ripple {
        position: absolute;
        border-radius: 50%;
        background: rgba(255, 255, 255, 0.1);
        transform: scale(0);
        animation: ripple 0.6s ease-out;
        pointer-events: none;
    }
    
    @keyframes ripple {
        to {
            transform: scale(4);
            opacity: 0;
        }
    }
    
    @keyframes shimmerPulse {
        0%, 100% { opacity: 1; }
        50% { opacity: 0.8; }
    }
    
    /* Chart transitions */
    .js-plotly-plot {
        transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
    }
`;
document.head.appendChild(style);
