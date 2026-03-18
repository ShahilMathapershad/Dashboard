// Minimal interactions for premium dashboard
// No gimmicky effects - just smooth, functional enhancements

document.addEventListener('DOMContentLoaded', function () {
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
        const resizePlot = () => {
            const plots = document.querySelectorAll('.js-plotly-plot');
            plots.forEach((plot) => {
                if (window.Plotly && typeof window.Plotly.Plots.resize === 'function') {
                    window.Plotly.Plots.resize(plot);
                }
            });
            window.dispatchEvent(new Event('resize'));
        };

        const observer = new MutationObserver(() => {
            const container = document.getElementById('visualization-container');
            if (!container) return;

            const isVisible = container.offsetParent !== null && getComputedStyle(container).display !== 'none';
            if (isVisible) {
                requestAnimationFrame(() => {
                    setTimeout(resizePlot, 80);
                });
            }
        });

        observer.observe(document.body, { childList: true, subtree: true, attributes: true, attributeFilter: ['style', 'class'] });
    };

    observeChips();
    observeChartVisibility();
});
