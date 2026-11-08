/**
 * Pace Card - Compact Version (Bubble Style)
 * Minimalist pill-shaped card inspired by Bubble Card design
 *
 * Version: 1.4.0
 *
 * Layout Compatibility:
 * - Masonry: Returns card size for proper column distribution
 * - Sections: 12 columns wide, auto height grid by default
 * - Both layouts fully supported with proper height handling
 * - Mobile-first, minimalist design
 */

import { anyStateChanged, applyHaStyleAttribute, applyTerminalPalette, beginScrollAnchor, resolvePaceEntity, TERMINAL_FONT_MONO } from './pace-card-utils.js?v=1.4.0';

// Maps each config entity key to the fixed English entity_id suffix it should
// end with, used to find the right entity when the configured/stub id
// doesn't account for this install's instance slug (e.g. "automatic").
const ENTITY_SUFFIXES = {
  download: 'download_speed',
  upload: 'upload_speed',
  ping: 'ping',
  run_test: 'run_speed_test',
  running: 'speed_test_running',
  internet_connected: 'internet_connected'
};

class PaceCompact extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: 'open' });
    this._config = {};
    this._hass = null;
    this._pendingClick = false;
  }

  static getConfigElement() {
    return document.createElement("pace-compact-editor");
  }

  static getStubConfig() {
    return {
      type: "custom:pace-compact",
      entities: {
        download: "sensor.pace_download_speed",
        upload: "sensor.pace_upload_speed",
        ping: "sensor.pace_ping",
        run_test: "button.pace_run_speed_test",
        running: "binary_sensor.pace_speed_test_running",
        internet_connected: "binary_sensor.pace_internet_connected"
      },
      labels: {
        download: "Download",
        upload: "Upload",
        ping: "Ping"
      },
      terminal_style: true
    };
  }

  setConfig(config) {
    this._config = { ...PaceCompact.getStubConfig(), ...config };
    applyHaStyleAttribute(this, this._config);
  }

  set hass(hass) {
    const oldHass = this._hass;
    this._hass = hass;
    applyTerminalPalette(this.shadowRoot, hass, this._config);
    // Only touch the DOM when one of our own entities actually changed -
    // Home Assistant calls this setter on EVERY entity's state change
    // system-wide, not just the ones this card displays.
    if (!oldHass || anyStateChanged(oldHass, hass, this._relevantEntityIds())) {
      this.updateCard();
    }
  }

  _relevantEntityIds() {
    const e = this._config.entities || {};
    return [
      this._resolve('download', e.download), this._resolve('upload', e.upload),
      this._resolve('ping', e.ping), this._resolve('running', e.running, 'binary_sensor'),
      this._resolve('internet_connected', e.internet_connected, 'binary_sensor')
    ];
  }

  connectedCallback() {
    this.render();
    // set hass() may have already fired before the DOM existed (and the
    // anyStateChanged gating skips a no-op update), so force one real pass
    // now that there's something to populate.
    if (this._hass) this.updateCard();
  }

  /**
   * Card size for Masonry view (1 = 50px)
   */
  getCardSize() {
    return 2; // ~100px height (compact but readable)
  }

  static getGridOptions() {
    return { columns: 12, rows: "auto" };
  }

  getGridOptions() {
    return { columns: 12, rows: "auto" };
  }

  updateCard() {
    if (!this._hass) return;

    const restoreScroll = beginScrollAnchor();
    const e = this._config.entities;
    const dl = this._getState(this._resolve('download', e.download));
    const ul = this._getState(this._resolve('upload', e.upload));
    const ping = this._getState(this._resolve('ping', e.ping));

    const dlEl = this.shadowRoot.querySelector('.dl-value');
    const ulEl = this.shadowRoot.querySelector('.ul-value');
    const pingEl = this.shadowRoot.querySelector('.ping-value');

    if (dlEl) dlEl.textContent = (typeof dl === 'number' && !isNaN(dl)) ? Math.round(dl) : '--';
    if (ulEl) ulEl.textContent = (typeof ul === 'number' && !isNaN(ul)) ? Math.round(ul) : '--';
    if (pingEl) pingEl.textContent = (typeof ping === 'number' && !isNaN(ping)) ? Math.round(ping) : '--';

    // Button reflects the real speed_test_running binary_sensor, with a
    // brief optimistic state right after a click to bridge the gap before
    // the sensor flips to "on".
    const runningState = this._getRawState(this._resolve('running', e.running, 'binary_sensor'));
    const isRunning = runningState === 'on' || this._pendingClick;
    const actionBtn = this.shadowRoot.querySelector('.action-button');
    if (actionBtn) {
      actionBtn.classList.toggle('running', isRunning);
      actionBtn.textContent = isRunning ? '...' : 'GO';
    }

    const netEntityId = this._resolve('internet_connected', e.internet_connected, 'binary_sensor');
    const netState = this._getRawState(netEntityId);
    const netDot = this.shadowRoot.querySelector('.net-dot');
    if (netDot) {
      // Recent failures while currently online read as "degraded" (amber,
      // pulsing) instead of the binary healthy/down the dot used to show -
      // see recent_checks on the internet_connected binary_sensor.
      const recentChecks = this._hass.states[netEntityId]?.attributes?.recent_checks || [];
      const isOnline = netState === 'on';
      const isDegraded = isOnline && recentChecks.slice(-5).some((ok) => ok === false);
      netDot.classList.toggle('online', isOnline && !isDegraded);
      netDot.classList.toggle('degraded', isDegraded);
      const statusText = netState === 'on' ? (isDegraded ? 'Internet: Connected (recent instability)' : 'Internet: Connected') : netState === 'off' ? 'Internet: Disconnected' : 'Internet: Unknown';
      netDot.title = statusText;
    }

    restoreScroll();
  }

  _getState(entityId) {
    if (!this._hass || !entityId) return null;
    const state = this._hass.states[entityId];
    if (!state || state.state === 'unknown' || state.state === 'unavailable') return null;
    const val = parseFloat(state.state);
    return isNaN(val) ? null : val;
  }

  _getRawState(entityId) {
    if (!this._hass || !entityId) return null;
    return this._hass.states[entityId]?.state ?? null;
  }

  _resolve(key, entityId, fallbackDomain) {
    return resolvePaceEntity(this._hass, entityId, ENTITY_SUFFIXES[key], fallbackDomain);
  }

  _showMoreInfo(entityId) {
    if (!entityId) return;
    const event = new CustomEvent('hass-more-info', {
      bubbles: true,
      composed: true,
      detail: { entityId }
    });
    this.dispatchEvent(event);
  }

  _runTest() {
    if (this._pendingClick) return;

    const entityId = this._resolve('run_test', this._config?.entities?.run_test);
    if (!this._hass || !entityId) return;

    this._pendingClick = true;
    this.updateCard();

    this._hass.callService('button', 'press', { entity_id: entityId }).finally(() => {
      setTimeout(() => {
        this._pendingClick = false;
        this.updateCard();
      }, 5000);
    });
  }

  render() {
    if (this.shadowRoot.innerHTML !== '') return; // Prevent re-rendering loop if already rendered

    const labels = this._config.labels || { download: 'Download', upload: 'Upload', ping: 'Ping' };

    this.shadowRoot.innerHTML = `
      <style>
        :host {
          display: block;
          width: 100%;
          height: 100%;
          box-sizing: border-box;
          container-type: inline-size;
        }

        * {
          box-sizing: border-box;
        }

        /* "Terminal Style" (terminal_style: false) drops the monospace
           value font and uses HA's own card chrome; the flat/square look
           below is the default (terminal_style: true), matching the other
           cards. */
        :host([ha]) .stat-value,
        :host([ha]) .action-button {
          font-family: var(--primary-font-family, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif);
        }
        :host([ha]) .card {
          border-radius: var(--ha-card-border-radius, 12px);
          border-width: var(--ha-card-border-width, 1px);
          box-shadow: var(--ha-card-box-shadow, 0 2px 2px 0 rgba(0, 0, 0, 0.14), 0 1px 5px 0 rgba(0, 0, 0, 0.12), 0 3px 1px -2px rgba(0, 0, 0, 0.2));
        }
        :host([ha]) .action-button {
          border-radius: 8px;
        }

        .card {
          background: var(--ls-card, #181f2b);
          border-radius: 0;
          padding: 4px 8px 4px 4px;
          color: var(--primary-text-color, #f8fafc);
          font-family: var(--primary-font-family, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif);
          display: flex;
          flex-direction: row;
          flex-wrap: nowrap;
          align-items: center;
          justify-content: flex-start;
          border: 1px solid var(--ls-border, #2a3142);
          box-shadow: var(--ha-card-box-shadow, none);
          width: 100%;
          height: 100%;
          min-height: 50px;
          max-height: 80px;
          gap: 8px;
          transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
          cursor: pointer;
          position: relative;
          overflow: hidden;
          flex: 1;
          direction: ltr;
        }

        .card::before {
          content: '';
          position: absolute;
          top: 0;
          left: 0;
          right: 0;
          bottom: 0;
          background: linear-gradient(135deg, rgba(14, 165, 233, 0.05) 0%, rgba(167, 139, 250, 0.05) 100%);
          opacity: 0;
          transition: opacity 0.3s ease;
          pointer-events: none;
        }

        .card:hover {
          box-shadow: 0 4px 16px 0 rgba(0, 0, 0, 0.24);
          transform: translateY(-1px);
        }

        .card:hover::before {
          opacity: 1;
        }

        .card:active {
          transform: scale(0.98);
        }

        .stats-container {
          display: flex;
          flex-direction: row;
          align-items: center;
          flex: 1;
          min-width: 0;
          overflow: hidden;
        }

        .stats {
          display: flex;
          justify-content: space-between;
          align-items: center;
          width: 100%;
          gap: 4px;
          min-width: 0;
          overflow: hidden;
        }

        .stat {
          display: flex;
          flex-direction: row;
          align-items: baseline;
          justify-content: center;
          gap: 2px;
          white-space: nowrap;
          flex: 1;
          min-width: 0;
          overflow: hidden;
          cursor: pointer;
          transition: opacity 0.2s;
        }

        .stat:hover {
          opacity: 0.8;
        }
        .stat:active {
          opacity: 0.6;
        }

        .stat-icon {
          --mdc-icon-size: 14px;
          width: 14px;
          height: 14px;
          opacity: 0.75;
          margin: 0;
          flex-shrink: 0;
        }

        .stat-dl .stat-icon { color: var(--pace-accent-color, var(--ls-accent, #2b6fd9)); }
        .stat-ul .stat-icon { color: var(--ls-upload, #6250d6); }
        .stat-ping .stat-icon { color: var(--ls-ping, #c97b1a); }

        .stat-value {
          font-size: 16px;
          font-weight: 700;
          font-family: ${TERMINAL_FONT_MONO};
          letter-spacing: -0.02em;
        }

        .stat-unit {
          font-size: 10.5px;
          font-weight: 500;
          opacity: 0.5;
          margin: 0;
        }

        .stat-dl .stat-value { color: var(--pace-accent-color, var(--ls-accent, #2b6fd9)); }
        .stat-ul .stat-value { color: var(--ls-upload, #6250d6); }
        .stat-ping .stat-value { color: var(--ls-ping, #c97b1a); }

        .action-button {
          width: 38px;
          height: 38px;
          border-radius: 0;
          border: 1px solid var(--pace-accent-color, var(--ls-accent, #2b6fd9));
          background: transparent;
          color: var(--pace-accent-color, var(--ls-accent, #2b6fd9));
          font-family: ${TERMINAL_FONT_MONO};
          display: flex;
          align-items: center;
          justify-content: center;
          font-size: 11px;
          font-weight: 800;
          cursor: pointer;
          transition: background-color 0.15s ease, color 0.15s ease;
          flex: 0 0 auto;
          letter-spacing: 0.5px;
          white-space: nowrap;
          padding: 0;
        }

        .action-button:hover {
          background: var(--pace-accent-color, var(--ls-accent, #2b6fd9));
          color: #fff;
        }

        .action-button:active {
          filter: brightness(0.9);
        }

        .action-button.running {
          background: var(--ls-success, #16a34a);
          border-color: var(--ls-success, #16a34a);
          color: #fff;
          animation: pulse-glow 1.5s cubic-bezier(0.4, 0, 0.2, 1) infinite;
        }

        @keyframes pulse-glow {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.8; }
        }

        .net-dot {
          width: 7px;
          height: 7px;
          border-radius: 50%;
          flex-shrink: 0;
          background: var(--ls-danger, #e5484d);
          cursor: pointer;
          transition: transform 0.15s ease, filter 0.15s ease;
        }

        .net-dot:hover {
          filter: brightness(1.2);
        }

        .net-dot:active {
          transform: scale(0.85);
        }

        .net-dot.online {
          background: var(--ls-success, #2f9d6b);
        }

        .net-dot.degraded {
          background: var(--ls-warning, #c97b1a);
          animation: pulse-glow 1.5s cubic-bezier(0.4, 0, 0.2, 1) infinite;
        }

        /* Container query responsive adjustments - simplified to prevent wrapping */
        @container (max-width: 320px) {
          .stat-icon { display: none; }
          .stats { gap: 4px; }
          .stat-value { font-size: 13px; }
          .stat-unit { font-size: 9px; }
          .card { padding: 4px 8px; }
        }
      </style>

      <div class="card">
        <button class="action-button">GO</button>
        <div class="stats-container">
          <div class="stats">
            <div class="stat stat-dl" title="${labels.download}">
              <ha-icon class="stat-icon" icon="mdi:download-network"></ha-icon>
              <span class="stat-value dl-value">--</span>
              <span class="stat-unit">Mbps</span>
            </div>
            <div class="stat stat-ul" title="${labels.upload}">
              <ha-icon class="stat-icon" icon="mdi:upload-network"></ha-icon>
              <span class="stat-value ul-value">--</span>
              <span class="stat-unit">Mbps</span>
            </div>
            <div class="stat stat-ping" title="${labels.ping}">
              <ha-icon class="stat-icon" icon="mdi:speedometer"></ha-icon>
              <span class="stat-value ping-value">--</span>
              <span class="stat-unit">ms</span>
            </div>
          </div>
        </div>
        <span class="net-dot" title="Internet"></span>
      </div>
    `;

    applyTerminalPalette(this.shadowRoot, this._hass, this._config);

    this.shadowRoot.querySelector('.action-button')?.addEventListener('click', (e) => {
      e.stopPropagation();
      this._runTest();
    });

    const e = this._config.entities;
    this.shadowRoot.querySelector('.stat-dl')?.addEventListener('click', (ev) => { ev.stopPropagation(); this._showMoreInfo(this._resolve('download', e.download)); });
    this.shadowRoot.querySelector('.stat-ul')?.addEventListener('click', (ev) => { ev.stopPropagation(); this._showMoreInfo(this._resolve('upload', e.upload)); });
    this.shadowRoot.querySelector('.stat-ping')?.addEventListener('click', (ev) => { ev.stopPropagation(); this._showMoreInfo(this._resolve('ping', e.ping)); });
    this.shadowRoot.querySelector('.net-dot')?.addEventListener('click', (ev) => { ev.stopPropagation(); this._showMoreInfo(this._resolve('internet_connected', e.internet_connected, 'binary_sensor')); });
  }
}

customElements.define("pace-compact", PaceCompact);

// Editor class remains in Light DOM (standard practice for editors)
class PaceCompactEditor extends HTMLElement {
  setConfig(config) {
    this._config = config;
    this.render();
  }

  set hass(hass) {
    this._hass = hass;
    if (this._elements) {
      this._elements.forEach(el => el.hass = hass);
    }
  }

  configChanged(newConfig) {
    const event = new CustomEvent("config-changed", { detail: { config: newConfig }, bubbles: true, composed: true });
    this.dispatchEvent(event);
  }

  render() {
    if (this._elements) return;

    this.innerHTML = '';
    this._elements = [];

    const container = document.createElement('div');
    container.style.cssText = "display: flex; flex-direction: column; gap: 12px; padding: 10px;";

    // Display Settings Section
    const displayDiv = document.createElement('div');
    displayDiv.style.cssText = "border: 1px solid var(--divider-color, #e0e0e0); border-radius: 8px; padding: 10px; background: var(--card-background-color, rgba(0,0,0,0.2));";
    displayDiv.innerHTML = `<div style="font-weight: 500; margin-bottom: 10px; color: var(--primary-text-color); font-size: 14px;">Display Settings</div>`;

    const styleToggle = document.createElement('div');
    styleToggle.style.cssText = "display: flex; align-items: center; justify-content: space-between;";
    styleToggle.innerHTML = `<label style="font-size: 13px; color: var(--primary-text-color);">Terminal Style</label>`;
    const terminalStyleCheckbox = document.createElement('input');
    terminalStyleCheckbox.type = "checkbox";
    terminalStyleCheckbox.checked = this._config.terminal_style !== false;
    terminalStyleCheckbox.style.cssText = "width: 20px; height: 20px; cursor: pointer;";
    terminalStyleCheckbox.addEventListener('change', (e) => this.configChanged({ ...this._config, terminal_style: e.target.checked }));
    styleToggle.appendChild(terminalStyleCheckbox);
    displayDiv.appendChild(styleToggle);
    container.appendChild(displayDiv);

    // Labels Section
    const labelsDiv = document.createElement('div');
    labelsDiv.style.cssText = "border: 1px solid var(--divider-color, #e0e0e0); border-radius: 8px; padding: 10px; background: var(--card-background-color, rgba(0,0,0,0.2));";
    labelsDiv.innerHTML = `<div style="font-weight: 500; margin-bottom: 10px; color: var(--primary-text-color); font-size: 14px;">Labels (Tooltips)</div>`;

    const createLabelInput = (key, label, defaultValue) => {
      const div = document.createElement('div');
      div.style.cssText = "display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px;";

      const lbl = document.createElement('label');
      lbl.innerText = label;
      lbl.style.cssText = "font-size: 13px; color: var(--primary-text-color);";
      div.appendChild(lbl);

      const input = document.createElement('input');
      input.type = "text";
      input.value = (this._config.labels && this._config.labels[key]) || defaultValue;
      input.style.cssText = "padding: 6px; border-radius: 4px; border: 1px solid var(--divider-color, #888); background: var(--card-background-color, #fff); color: var(--primary-text-color, #000); width: 100px;";
      input.addEventListener('change', (e) => {
        const labels = { ...(this._config.labels || {}) };
        labels[key] = e.target.value;
        this.configChanged({ ...this._config, labels });
      });

      div.appendChild(input);
      return div;
    };

    labelsDiv.appendChild(createLabelInput('download', 'Download', 'Download'));
    labelsDiv.appendChild(createLabelInput('upload', 'Upload', 'Upload'));
    labelsDiv.appendChild(createLabelInput('ping', 'Ping', 'Ping'));
    container.appendChild(labelsDiv);

    const createPicker = (key, label, domains) => {
        const div = document.createElement('div');
        const lbl = document.createElement('label');
        lbl.innerText = label;
        lbl.style.cssText = "font-size: 12px; color: var(--secondary-text-color); margin-bottom: 4px; display: block;";
        div.appendChild(lbl);

        const picker = document.createElement('ha-entity-picker');
        if (this._hass) picker.hass = this._hass;
        picker.value = (this._config.entities && this._config.entities[key]) || '';
        picker.includeDomains = domains || ['sensor'];
        picker.allowCustomEntity = true;
        picker.addEventListener('value-changed', (e) => {
            const entities = { ...(this._config.entities || {}) };
            entities[key] = e.detail.value;
            this.configChanged({ ...this._config, entities });
        });

        this._elements.push(picker);
        div.appendChild(picker);
        return div;
    };

    container.appendChild(createPicker('download', 'Download Entity'));
    container.appendChild(createPicker('upload', 'Upload Entity'));
    container.appendChild(createPicker('ping', 'Ping Entity'));
    container.appendChild(createPicker('run_test', 'Run Test Button', ['button']));
    container.appendChild(createPicker('running', 'Speed Test Running', ['binary_sensor']));
    container.appendChild(createPicker('internet_connected', 'Internet Connected', ['binary_sensor']));

    this.appendChild(container);
  }
}
customElements.define("pace-compact-editor", PaceCompactEditor);

window.customCards = window.customCards || [];
window.customCards.push({
  type: "pace-compact",
  name: "PACE - Compact (Bubble Style)",
  description: "Minimalist pill-shaped card inspired by Bubble Card design - perfect for side panels",
  preview: true
});

console.info("%c PACE COMPACT (BUBBLE) %c v1.4.0 ", "background: #0ea5e9; color: #fff; font-weight: bold;", "background: #1e293b; color: #fff;");
