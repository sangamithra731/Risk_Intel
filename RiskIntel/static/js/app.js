/* ==========================================================================
   RISKintel - Core Frontend Application Controller
   Handles Maps, Charts, Simulation, Real-Time Prediction, and State Sync
   ========================================================================== */

document.addEventListener('DOMContentLoaded', () => {
    // Sidebar Toggle
    const sidebarToggleBtn = document.getElementById('sidebar-toggle');
    const sidebar = document.getElementById('sidebar');
    if (sidebarToggleBtn && sidebar) {
        sidebarToggleBtn.addEventListener('click', () => {
            sidebar.classList.toggle('open');
        });
    }

    // Auto-dismiss alerts after 5 seconds
    const alerts = document.querySelectorAll('.alert-dismissible');
    alerts.forEach(alert => {
        setTimeout(() => {
            const closeBtn = alert.querySelector('.btn-close');
            if (closeBtn) closeBtn.click();
        }, 6000);
    });
});

// Toast notification helper
function showToast(message, type = 'info') {
    const container = document.getElementById('toast-container');
    if (!container) return;

    const toast = document.createElement('div');
    toast.className = `alert alert-${type} shadow-lg mb-2 text-white border-0`;
    toast.style.background = type === 'danger' ? '#ef4444' : (type === 'success' ? '#10b981' : '#3b82f6');
    toast.style.borderRadius = '6px';
    toast.style.padding = '10px 16px';
    toast.style.fontSize = '0.85rem';
    toast.innerHTML = `<i class="fa-solid fa-circle-info me-2"></i> ${message}`;
    
    container.appendChild(toast);
    setTimeout(() => {
        toast.style.opacity = '0';
        toast.style.transition = 'opacity 0.5s';
        setTimeout(() => toast.remove(), 500);
    }, 4000);
}

// Marker Icon Factory for Leaflet
function getCustomMarkerIcon(colorHex, iconClass) {
    return L.divIcon({
        className: 'custom-map-marker',
        html: `<div style="
            background: ${colorHex};
            width: 28px;
            height: 28px;
            border-radius: 50%;
            border: 2px solid #ffffff;
            box-shadow: 0 0 10px ${colorHex}99;
            display: flex;
            align-items: center;
            justify-content: center;
            color: #ffffff;
            font-size: 11px;">
            <i class="${iconClass}"></i>
        </div>`,
        iconSize: [28, 28],
        iconAnchor: [14, 14],
        popupAnchor: [0, -14]
    });
}

// Helper: Risk Level to Color
function getRiskColor(level) {
    switch (level) {
        case 'CRITICAL': return '#ef4444';
        case 'HIGH': return '#f97316';
        case 'MODERATE': return '#f59e0b';
        case 'LOW': default: return '#10b981';
    }
}

// Global Alert Action AJAX
async function handleAlertDecision(alertId, action) {
    try {
        const res = await fetch(`/api/alerts/${alertId}/${action}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' }
        });
        const data = await res.json();
        if (data.success) {
            showToast(`Alert ${data.alert.alert_id} marked as ${data.alert.status}`, 'success');
            setTimeout(() => window.location.reload(), 800);
        } else {
            showToast(data.error || 'Failed to update alert', 'danger');
        }
    } catch (e) {
        showToast('Network error during alert action', 'danger');
    }
}

// Interactive AI Risk Calculation
async function calculateRiskFromForm(event) {
    if (event) event.preventDefault();

    const form = document.getElementById('risk-calc-form');
    if (!form) return;

    const payload = {
        lake_id: form.lake_id ? form.lake_id.value : null,
        water_level: parseFloat(form.water_level.value),
        water_level_change: parseFloat(form.water_level_change.value),
        rainfall: parseFloat(form.rainfall.value),
        temperature: parseFloat(form.temperature.value),
        ice_melt: parseFloat(form.ice_melt.value),
        glacier_stability: parseFloat(form.glacier_stability.value),
        terrain_movement: parseFloat(form.terrain_movement.value),
        seismic_activity: parseFloat(form.seismic_activity.value)
    };

    const calcBtn = document.getElementById('btn-calculate-risk');
    if (calcBtn) {
        calcBtn.innerHTML = `<i class="fa-solid fa-spinner fa-spin me-2"></i> EVALUATING...`;
        calcBtn.disabled = true;
    }

    try {
        const res = await fetch('/api/risk/predict', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        const data = await res.json();

        // Update score display
        const scoreEl = document.getElementById('result-risk-score');
        const levelBadge = document.getElementById('result-risk-level');
        const confEl = document.getElementById('result-confidence');

        if (scoreEl) scoreEl.innerText = data.risk_score.toFixed(1);
        if (confEl) confEl.innerText = `${data.confidence}%`;

        if (levelBadge) {
            levelBadge.innerText = data.risk_level;
            levelBadge.className = `badge-risk badge-risk-${data.risk_level.toLowerCase()}`;
        }

        // Update feature importance bars if chart or container exists
        if (window.importanceChart && data.feature_importance) {
            window.importanceChart.data.labels = Object.keys(data.feature_importance).map(k => k.replace(/_/g, ' ').toUpperCase());
            window.importanceChart.data.datasets[0].data = Object.values(data.feature_importance);
            window.importanceChart.update();
        }

        showToast(`AI Risk assessment generated: ${data.risk_level} (${data.risk_score})`, 'success');
    } catch (e) {
        showToast('Error calculating risk prediction', 'danger');
    } finally {
        if (calcBtn) {
            calcBtn.innerHTML = `<i class="fa-solid fa-calculator me-2"></i> CALCULATE RISK`;
            calcBtn.disabled = false;
        }
    }
}

// Emergency Simulation Controller Object
window.RiskSimulation = {
    timer: null,
    isRunning: false,

    async fetchStatus() {
        try {
            const res = await fetch('/api/simulation/status');
            const data = await res.json();
            this.updateUI(data);
            return data;
        } catch (e) {
            console.error("Simulation status check error", e);
        }
    },

    updateUI(state) {
        const stepNum = document.getElementById('sim-current-step-num');
        const stepTitle = document.getElementById('sim-current-step-title');
        const stepDesc = document.getElementById('sim-current-step-desc');
        const progressBar = document.getElementById('sim-progress-bar');

        if (stepNum) stepNum.innerText = `STEP ${state.current_step} / ${state.total_steps}`;
        if (progressBar) {
            const pct = (state.current_step / state.total_steps) * 100;
            progressBar.style.width = `${pct}%`;
        }

        if (state.step_details) {
            if (stepTitle) stepTitle.innerText = state.step_details.title;
            if (stepDesc) stepDesc.innerText = state.step_details.desc;
        } else if (state.current_step === 0) {
            if (stepTitle) stepTitle.innerText = "Baseline Monitoring (Standby)";
            if (stepDesc) stepDesc.innerText = "System in standard monitoring mode. Press 'Start Emergency Simulation' to initiate rapid environmental deterioration scenario.";
        }

        // Update vertical timeline items
        const timelineItems = document.querySelectorAll('.sim-timeline-item');
        timelineItems.forEach((el, index) => {
            const s = index + 1;
            el.classList.remove('completed', 'active');
            if (s < state.current_step) {
                el.classList.add('completed');
            } else if (s === state.current_step) {
                el.classList.add('active');
            }
        });

        // Add log entry to terminal
        const logBox = document.getElementById('sim-log-terminal');
        if (logBox && state.step_details && state.current_step > 0) {
            const timeStr = new Date().toLocaleTimeString();
            const logLine = document.createElement('div');
            logLine.className = 'terminal-line mb-1';
            logLine.innerHTML = `<span class="text-secondary">[${timeStr}]</span> <span class="text-warning">[STEP ${state.current_step}]</span> <span class="text-white">${state.step_details.title}</span> — <span class="text-muted">${state.step_details.desc}</span>`;
            logBox.appendChild(logLine);
            logBox.scrollTop = logBox.scrollHeight;
        }
    },

    async start() {
        try {
            const res = await fetch('/api/simulation/start', { method: 'POST' });
            const data = await res.json();
            if (data.success) {
                showToast("Simulation initialized. Scenario running.", "warning");
                await this.fetchStatus();
                this.autoRun();
            }
        } catch (e) {
            showToast("Failed to start simulation", "danger");
        }
    },

    async nextStep() {
        try {
            const res = await fetch('/api/simulation/step', { method: 'POST' });
            const data = await res.json();
            if (data.success) {
                await this.fetchStatus();
                if (data.current_step >= 23) {
                    this.pause();
                    showToast("Simulation scenario complete (Step 23 - Recovery Initiated)", "success");
                }
            }
        } catch (e) {
            showToast("Failed to step simulation", "danger");
        }
    },

    autoRun() {
        if (this.isRunning) return;
        this.isRunning = true;
        const autoBtn = document.getElementById('btn-sim-autorun');
        if (autoBtn) {
            autoBtn.innerHTML = `<i class="fa-solid fa-pause me-2"></i> Pause Auto`;
            autoBtn.classList.replace('btn-risk-outline', 'btn-risk-danger');
        }

        this.timer = setInterval(async () => {
            const res = await fetch('/api/simulation/status');
            const data = await res.json();
            if (data.current_step >= 23) {
                this.pause();
            } else {
                await this.nextStep();
            }
        }, 2600);
    },

    pause() {
        this.isRunning = false;
        if (this.timer) {
            clearInterval(this.timer);
            this.timer = null;
        }
        const autoBtn = document.getElementById('btn-sim-autorun');
        if (autoBtn) {
            autoBtn.innerHTML = `<i class="fa-solid fa-forward-fast me-2"></i> Auto Run`;
            autoBtn.classList.replace('btn-risk-danger', 'btn-risk-outline');
        }
        showToast("Simulation auto-run paused", "info");
    },

    async reset() {
        this.pause();
        try {
            const res = await fetch('/api/simulation/reset', { method: 'POST' });
            const data = await res.json();
            if (data.success) {
                showToast("Simulation reset to baseline state", "info");
                const logBox = document.getElementById('sim-log-terminal');
                if (logBox) logBox.innerHTML = '<div class="text-secondary">[SYSTEM] Baseline monitoring restored. Scenario memory flushed.</div>';
                await this.fetchStatus();
            }
        } catch (e) {
            showToast("Failed to reset simulation", "danger");
        }
    }
};
