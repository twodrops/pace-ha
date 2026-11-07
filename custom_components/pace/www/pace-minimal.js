/**
 * Pace Card - Minimal Version
 * A clean, simple speedtest card with large typography
 *
 * Version: 1.2.2
 *
 * Layout Compatibility:
 * - Masonry: Returns card size for proper column distribution
 * - Sections: 12 columns wide, auto height grid by default
 * - Both layouts fully supported with proper height handling
 */

import { anyStateChanged, applyHaStyleAttribute, applyTerminalPalette, beginScrollAnchor, getTerminalColor, navigateToPaceIntegration, renderHeartbeatBars, resolvePaceEntity, TERMINAL_FONT_MONO } from './pace-card-utils.js?v=1.2.2';

// Maps each config entity key to the fixed English entity_id suffix it should
// end with, used to find the right entity when the configured/stub id
// doesn't account for this install's instance slug (e.g. "automatic").
const ENTITY_SUFFIXES = {
  download: 'download_speed',
  upload: 'upload_speed',
  ping: 'ping',
  run_test: 'run_speed_test',
  running: 'speed_test_running',
  internet_connected: 'internet_connected',
  public_ip: 'public_ip_address'
};

class PaceMinimal extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: 'open' });
    this._config = {};
    this._hass = null;
    this._pendingClick = false;
  }

  static getConfigElement() {
    return document.createElement("pace-minimal-editor");
  }

  static getStubConfig() {
    return {
      type: "custom:pace-minimal",
      entities: {
        download: "sensor.pace_download_speed",
        upload: "sensor.pace_upload_speed",
        ping: "sensor.pace_ping",
        run_test: "button.pace_run_speed_test",
        running: "binary_sensor.pace_speed_test_running",
        internet_connected: "binary_sensor.pace_internet_connected",
        public_ip: "sensor.pace_public_ip_address"
      },
      title: "PACE",
      labels: {
        download: "Download",
        upload: "Upload",
        ping: "Ping"
      },
      terminal_style: true
    };
  }

  setConfig(config) {
    this._config = { ...PaceMinimal.getStubConfig(), ...config };
    applyHaStyleAttribute(this, this._config);
    // Live-update the title if the card is already rendered (editor preview).
    const titleEl = this.shadowRoot?.querySelector('.isp-text');
    if (titleEl) titleEl.textContent = this._config.title;
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
      this._resolve('internet_connected', e.internet_connected, 'binary_sensor'),
      this._resolve('public_ip', e.public_ip, 'sensor')
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
    return 6; // ~300px height
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
    const download = this._getState(this._resolve('download', e.download));
    const upload = this._getState(this._resolve('upload', e.upload));
    const ping = this._getState(this._resolve('ping', e.ping));

    const dlEl = this.shadowRoot.querySelector('.speed-download');
    const ulEl = this.shadowRoot.querySelector('.speed-upload');
    const pingEl = this.shadowRoot.querySelector('.ping-value');

    const dlValid = typeof download === 'number' && !isNaN(download);
    const ulValid = typeof upload === 'number' && !isNaN(upload);
    const pingValid = typeof ping === 'number' && !isNaN(ping);

    if (dlEl) dlEl.textContent = dlValid ? `${Math.round(download)} Mbps` : '--';
    if (ulEl) ulEl.textContent = ulValid ? `${Math.round(upload)} Mbps` : '--';
    if (pingEl) pingEl.textContent = pingValid ? `${Math.round(ping)} ms` : '--';

    if (dlEl && dlValid) {
      dlEl.style.color = download > 100 ? getTerminalColor(this._hass, 'accent', '#38bdf8', this._config) : download > 50 ? getTerminalColor(this._hass, 'warning', '#fbbf24', this._config) : getTerminalColor(this._hass, 'danger', '#ef4444', this._config);
    }
    if (ulEl && ulValid) {
      ulEl.style.color = upload > 50 ? getTerminalColor(this._hass, 'upload', '#a78bfa', this._config) : upload > 20 ? getTerminalColor(this._hass, 'warning', '#fbbf24', this._config) : getTerminalColor(this._hass, 'danger', '#ef4444', this._config);
    }

    // Button reflects the real speed_test_running binary_sensor, with a
    // brief optimistic state right after a click to bridge the gap before
    // the sensor flips to "on".
    const runningState = this._getRawState(this._resolve('running', e.running, 'binary_sensor'));
    const isRunning = runningState === 'on' || this._pendingClick;
    const btn = this.shadowRoot.querySelector('.test-btn');
    if (btn) {
      btn.classList.toggle('running', isRunning);
      btn.textContent = isRunning ? 'Testing...' : 'Run Test';
    }

    const netState = this._getRawState(this._resolve('internet_connected', e.internet_connected, 'binary_sensor'));
    const netDot = this.shadowRoot.querySelector('.net-dot');
    if (netDot) {
      netDot.classList.toggle('online', netState === 'on');
      netDot.title = netState === 'on' ? 'Internet: Connected' : netState === 'off' ? 'Internet: Disconnected' : 'Internet: Unknown';
    }

    const netEntityId = this._resolve('internet_connected', e.internet_connected, 'binary_sensor');
    const heartbeatEl = this.shadowRoot.querySelector('.heartbeat-strip');
    if (heartbeatEl) {
      const recentChecks = this._hass.states[netEntityId]?.attributes?.recent_checks;
      heartbeatEl.innerHTML = renderHeartbeatBars(recentChecks, 12);
    }

    const ip = this._getRawState(this._resolve('public_ip', e.public_ip, 'sensor'));
    const ipEl = this.shadowRoot.querySelector('.ip-text');
    if (ipEl) {
      const ipValid = ip && ip !== 'unknown' && ip !== 'unavailable';
      ipEl.textContent = ipValid ? `IP: ${ip}` : 'Link';
    }

    restoreScroll();
  }

  _getState(entityId) {
    if (!this._hass || !entityId) return null;
    const state = this._hass.states[entityId];
    if (!state || state.state === 'unknown' || state.state === 'unavailable') return null;
    const num = parseFloat(state.state);
    return !isNaN(num) ? num : state.state;
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

        /* "Terminal Style" (terminal_style: false): fall back to HA's own
           fonts, card chrome, and typography instead of the terminal look. */
        :host([ha]) .card,
        :host([ha]) .link-row .ip-text,
        :host([ha]) .test-btn {
          font-family: var(--ha-font-family-body, var(--paper-font-body1_-_font-family, Roboto, sans-serif));
        }
        :host([ha]) .card {
          border-radius: var(--ha-card-border-radius, 12px);
          box-shadow: var(--ha-card-box-shadow, 0 2px 2px 0 rgba(0, 0, 0, 0.14), 0 1px 5px 0 rgba(0, 0, 0, 0.12), 0 3px 1px -2px rgba(0, 0, 0, 0.2));
        }
        :host([ha]) .isp-text::before { display: none; }
        :host([ha]) .isp-text,
        :host([ha]) .speed-label,
        :host([ha]) .test-btn {
          text-transform: none;
          letter-spacing: 0;
        }
        :host([ha]) .ping-row,
        :host([ha]) .link-row,
        :host([ha]) .test-btn {
          border-radius: 8px;
        }

        .card {
          background: var(--ls-card, #181f2b);
          border-radius: 0;
          padding: 20px;
          color: var(--primary-text-color, #f8fafc);
          font-family: ${TERMINAL_FONT_MONO};
          border: 1px solid var(--ha-card-border-color, var(--divider-color, #2a3142));
          box-shadow: var(--ha-card-box-shadow, none);
          width: 100%;
          height: 100%;
          min-height: 0;
          display: flex;
          flex-direction: column;
          justify-content: center;
          flex: 1;
          direction: ltr;
        }
        .isp-text {
          font-size: 11px;
          color: var(--secondary-text-color, #94a3b8);
          text-transform: uppercase;
          letter-spacing: 1.5px;
          margin-bottom: 20px;
          font-weight: 600;
          cursor: pointer;
          transition: opacity 0.15s ease;
        }
        .isp-text:hover { opacity: 0.8; }
        .isp-text:active { opacity: 0.6; }
        .isp-text::before {
          content: '┃ ';
          color: var(--pace-accent-color, var(--ls-accent, #2b6fd9));
        }
        .header-row {
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: 8px;
        }
        .net-dot {
          width: 8px;
          height: 8px;
          border-radius: 50%;
          flex-shrink: 0;
          background: var(--ls-danger, #e5484d);
          cursor: pointer;
          transition: transform 0.15s ease, filter 0.15s ease;
        }
        .net-dot:hover { filter: brightness(1.2); }
        .net-dot:active { transform: scale(0.85); }
        .net-dot.online {
          background: var(--ls-success, #2f9d6b);
        }
        .speeds {
          display: flex;
          gap: 20px;
          margin-bottom: 20px;
        }
        .speed-block {
          flex: 1;
          cursor: pointer;
          transition: transform 0.2s;
        }
        .speed-block:hover {
          transform: translateY(-2px);
        }
        .speed-block:active {
          transform: translateY(0) scale(0.97);
        }
        .speed-label {
          font-size: 10px;
          color: var(--secondary-text-color, #94a3b8);
          text-transform: uppercase;
          letter-spacing: 1px;
          margin-bottom: 8px;
          display: flex;
          align-items: center;
          gap: 6px;
          font-weight: 600;
        }
        .speed-value {
          font-size: 36px;
          font-weight: 700;
          line-height: 1;
          transition: color 0.3s;
          letter-spacing: -1px;
        }
        .arrow-down, .arrow-up {
          --mdc-icon-size: 14px;
          width: 14px;
          height: 14px;
          flex-shrink: 0;
        }
        .arrow-down { color: var(--pace-accent-color, var(--ls-accent, #2b6fd9)); }
        .arrow-up { color: var(--ls-upload, #6250d6); }
        .status-row {
          display: flex;
          gap: 8px;
          margin-bottom: 12px;
        }
        .ping-row,
        .link-row {
          position: relative;
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: 8px;
          font-size: 14px;
          color: var(--secondary-text-color, #94a3b8);
          background: var(--ls-panel, var(--secondary-background-color, #10141b));
          padding: 8px 16px;
          border-radius: 0;
          border: 1px solid var(--divider-color, #2a3142);
          flex: 1;
          min-width: 0;
        }
        .ping-row {
          cursor: pointer;
          transition: background-color 0.2s;
        }
        .ping-row:hover {
          background: var(--ls-panel, var(--secondary-background-color, #10141b));
          filter: brightness(1.15);
        }
        .ping-row:active {
          filter: brightness(1.3);
        }
        .ping-value {
          color: var(--ls-ping, #c97b1a);
          font-weight: 700;
        }
        .link-row .ip-text {
          font-size: 11px;
          font-family: ${TERMINAL_FONT_MONO};
          color: var(--secondary-text-color, #64748b);
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
          cursor: pointer;
          transition: opacity 0.15s ease;
        }
        .link-row .ip-text:hover { opacity: 0.8; }
        .link-row .ip-text:active { opacity: 0.6; }
        .heartbeat-strip { display: flex; gap: 1px; flex-shrink: 0; cursor: pointer; transition: opacity 0.15s ease; }
        .heartbeat-strip:hover { opacity: 0.8; }
        .heartbeat-strip:active { opacity: 0.6; }
        .hb-bar { width: 2px; height: 8px; background: var(--divider-color, #2a3142); }
        .hb-bar.hb-ok { background: var(--ls-success, #16a34a); }
        .hb-bar.hb-fail { background: var(--ls-danger, #dc2626); }
        .test-btn {
          width: 100%;
          padding: 12px;
          border: 1px solid var(--pace-accent-color, var(--ls-accent, #2b6fd9));
          border-radius: 0;
          background: transparent;
          color: var(--pace-accent-color, var(--ls-accent, #2b6fd9));
          font-family: ${TERMINAL_FONT_MONO};
          font-size: 14px;
          font-weight: 700;
          letter-spacing: 0.4px;
          text-transform: uppercase;
          cursor: pointer;
          transition: background-color 0.15s ease, color 0.15s ease;
        }
        .test-btn:hover {
          background: var(--pace-accent-color, var(--ls-accent, #2b6fd9));
          color: #fff;
        }
        .test-btn:active {
          filter: brightness(0.9);
        }
        .test-btn.running {
          background: var(--ls-success, #16a34a);
          border-color: var(--ls-success, #16a34a);
          color: #fff;
          animation: pulse 1.5s infinite;
        }
        @keyframes pulse { 0% { opacity: 1; } 50% { opacity: 0.7; } 100% { opacity: 1; } }

        /* On narrow cards (phone portrait), the IP address was competing
           with the heartbeat strip for the same line and getting truncated
           with an ellipsis. Stacking them gives the IP text the box's full
           width instead. */
        @container (max-width: 380px) {
          .link-row {
            flex-direction: column;
            align-items: flex-start;
            gap: 4px;
          }
          .link-row .ip-text {
            max-width: 100%;
          }
        }
      </style>

      <div class="card">
        <div class="header-row">
          <div class="isp-text">${this._config.title || 'PACE'}</div>
          <span class="net-dot" title="Internet"></span>
        </div>

        <div class="speeds">
          <div class="speed-block speed-block-dl">
            <div class="speed-label">
              <ha-icon class="arrow-down" icon="mdi:download-network"></ha-icon> ${labels.download}
            </div>
            <div class="speed-value speed-download">--</div>
          </div>
          <div class="speed-block speed-block-ul">
            <div class="speed-label">
              <ha-icon class="arrow-up" icon="mdi:upload-network"></ha-icon> ${labels.upload}
            </div>
            <div class="speed-value speed-upload">--</div>
          </div>
        </div>

        <div class="status-row">
          <div class="ping-row">
            ${labels.ping}: <span class="ping-value">--</span>
          </div>
          <div class="link-row">
            <span class="ip-text">Link</span>
            <span class="heartbeat-strip"></span>
          </div>
        </div>

        <button class="test-btn">Run Test</button>
      </div>
    `;

    applyTerminalPalette(this.shadowRoot, this._hass);

    this.shadowRoot.querySelector('.test-btn')?.addEventListener('click', () => this._runTest());
    this.shadowRoot.querySelector('.isp-text')?.addEventListener('click', () => navigateToPaceIntegration());

    const e = this._config.entities;
    this.shadowRoot.querySelector('.speed-block-dl')?.addEventListener('click', () => this._showMoreInfo(this._resolve('download', e.download)));
    this.shadowRoot.querySelector('.speed-block-ul')?.addEventListener('click', () => this._showMoreInfo(this._resolve('upload', e.upload)));
    this.shadowRoot.querySelector('.ping-row')?.addEventListener('click', () => this._showMoreInfo(this._resolve('ping', e.ping)));
    this.shadowRoot.querySelector('.link-row .ip-text')?.addEventListener('click', (ev) => { ev.stopPropagation(); this._showMoreInfo(this._resolve('public_ip', e.public_ip, 'sensor')); });
    this.shadowRoot.querySelector('.heartbeat-strip')?.addEventListener('click', (ev) => { ev.stopPropagation(); this._showMoreInfo(this._resolve('internet_connected', e.internet_connected, 'binary_sensor')); });
    this.shadowRoot.querySelector('.net-dot')?.addEventListener('click', (ev) => { ev.stopPropagation(); this._showMoreInfo(this._resolve('internet_connected', e.internet_connected, 'binary_sensor')); });
  }
}

customElements.define("pace-minimal", PaceMinimal);

class PaceMinimalEditor extends HTMLElement {
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
    const event = new CustomEvent("config-changed", {
      detail: { config: newConfig },
      bubbles: true,
      composed: true,
    });
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

    const titleOption = document.createElement('div');
    titleOption.style.cssText = "display: flex; align-items: center; justify-content: space-between; margin-bottom: 10px;";
    titleOption.innerHTML = `<label style="font-size: 13px; color: var(--primary-text-color);">Title</label>`;
    const titleInput = document.createElement('input');
    titleInput.type = "text";
    titleInput.value = this._config.title ?? "PACE";
    titleInput.placeholder = "PACE";
    titleInput.style.cssText = "padding: 6px; border-radius: 4px; border: 1px solid var(--divider-color, #888); background: var(--card-background-color, #fff); color: var(--primary-text-color, #000); width: 100px;";
    titleInput.addEventListener('change', (e) => this.configChanged({ ...this._config, title: e.target.value || 'PACE' }));
    titleOption.appendChild(titleInput);
    displayDiv.appendChild(titleOption);

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
    labelsDiv.innerHTML = `<div style="font-weight: 500; margin-bottom: 10px; color: var(--primary-text-color); font-size: 14px;">Labels</div>`;

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

    const entitiesDiv = document.createElement('div');
    entitiesDiv.style.cssText = "border: 1px solid var(--divider-color, #e0e0e0); border-radius: 8px; padding: 10px; background: var(--card-background-color, rgba(0,0,0,0.2));";
    entitiesDiv.innerHTML = `<div style="font-weight: 500; margin-bottom: 10px; color: var(--primary-text-color); font-size: 14px;">Entities</div>`;

    const createPicker = (key, label, domains) => {
      const div = document.createElement('div');
      div.style.marginBottom = "12px";

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

    entitiesDiv.appendChild(createPicker('download', 'Download Entity'));
    entitiesDiv.appendChild(createPicker('upload', 'Upload Entity'));
    entitiesDiv.appendChild(createPicker('ping', 'Ping Entity'));
    entitiesDiv.appendChild(createPicker('run_test', 'Run Test Button', ['button']));
    entitiesDiv.appendChild(createPicker('running', 'Speed Test Running', ['binary_sensor']));
    entitiesDiv.appendChild(createPicker('internet_connected', 'Internet Connected', ['binary_sensor']));
    entitiesDiv.appendChild(createPicker('public_ip', 'Public IP Address'));

    container.appendChild(entitiesDiv);
    this.appendChild(container);
  }
}
customElements.define("pace-minimal-editor", PaceMinimalEditor);

window.customCards = window.customCards || [];
window.customCards.push({
  type: "pace-minimal",
  name: "PACE - Minimal",
  description: "Clean minimal speedtest card with large typography",
  preview: true
});

console.info("%c PACE MINIMAL %c v1.2.2 ", "background: #00d2ff; color: #fff; font-weight: bold;", "background: #1e293b; color: #fff;");
