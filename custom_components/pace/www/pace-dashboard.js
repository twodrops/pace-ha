/**
 * Pace Card - Dashboard Version
 * Full-featured dashboard card with configurable gauges and charts
 *
 * Version: 1.0.0
 *
 * Layout Compatibility:
 * - Masonry: Returns card size for proper column distribution
 * - Sections: 6 columns wide, auto height grid by default
 * - Both layouts fully supported with proper height handling
 */

import { anyStateChanged, applyHaStyleAttribute, applyTerminalPalette, beginScrollAnchor, getTerminalColor, resolvePaceEntity, TERMINAL_FONT_MONO } from './pace-card-utils.js?v=1.0.0';

// Maps each config entity key to the fixed English entity_id suffix it should
// end with, used to find the right entity when the configured/stub id
// doesn't account for this install's instance slug (e.g. "automatic").
const ENTITY_SUFFIXES = {
  download: 'download_speed',
  upload: 'upload_speed',
  ping: 'ping',
  jitter: 'jitter',
  server: 'server_name',
  backend: 'backend',
  last_test: 'last_test_time',
  run_test: 'run_speed_test',
  dl_compliance: 'download_plan_compliance',
  ul_compliance: 'upload_plan_compliance',
  data_downloaded: 'test_data_downloaded',
  data_uploaded: 'test_data_uploaded',
  lifetime_download: 'lifetime_data_downloaded',
  lifetime_upload: 'lifetime_data_uploaded',
  running: 'speed_test_running',
  internet_connected: 'internet_connected',
  public_ip: 'public_ip_address'
};

// Maps each history key to the metric card it's drawn into as a background
// sparkline (see _drawSingleChart).
const METRIC_CARD_SELECTOR = {
  download: '.metric-dl',
  upload: '.metric-ul',
  ping: '.metric-ping',
  jitter: '.metric-jitter'
};

// Friendly display names for the backend sensor's raw enum state - kept in
// sync with _BACKEND_LABELS in config_flow.py.
const BACKEND_LABELS = {
  librespeed: 'LibreSpeed CLI',
  ookla: 'Ookla CLI',
  speedtest_go: 'speedtest-go CLI'
};

class PaceDashboard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: 'open' });
    this._config = {};
    this._hass = null;
    this._history = { download: [], upload: [], ping: [], jitter: [] };
    this._pendingClick = false;
  }

  static getConfigElement() {
    return document.createElement("pace-dashboard-editor");
  }

  static getStubConfig() {
    return {
      type: "custom:pace-dashboard",
      entities: {
        // Default sensors
        download: "sensor.pace_download_speed",
        upload: "sensor.pace_upload_speed",
        ping: "sensor.pace_ping",
        jitter: "sensor.pace_jitter",
        server: "sensor.pace_server_name",
        backend: "sensor.pace_backend",
        last_test: "sensor.pace_last_test_time",
        run_test: "button.pace_run_speed_test",
        running: "binary_sensor.pace_speed_test_running",
        internet_connected: "binary_sensor.pace_internet_connected",
        public_ip: "sensor.pace_public_ip_address",
        // Plan compliance (Optional)
        dl_compliance: "sensor.pace_download_plan_compliance",
        ul_compliance: "sensor.pace_upload_plan_compliance",
        // Data usage (Optional)
        data_downloaded: "sensor.pace_test_data_downloaded",
        data_uploaded: "sensor.pace_test_data_uploaded",
        lifetime_download: "sensor.pace_lifetime_data_downloaded",
        lifetime_upload: "sensor.pace_lifetime_data_uploaded"
      },
      labels: {
        download: "Download",
        upload: "Upload",
        ping: "Ping",
        jitter: "Jitter"
      },
      show_gauges: true,
      show_charts: true,
      history_hours: 168,  // 7 days (24 * 7)
      terminal_style: true
    };
  }

  setConfig(config) {
    // Merge config but don't force stub defaults for entities
    const stubConfig = PaceDashboard.getStubConfig();
    this._config = {
      ...stubConfig,
      ...config
    };

    // Only use stub entities if user hasn't provided any entities at all
    if (!config.entities) {
      this._config.entities = stubConfig.entities;
    } else {
      // Use only the entities the user explicitly configured
      this._config.entities = config.entities;
    }
    applyHaStyleAttribute(this, this._config);
  }

  set hass(hass) {
    const oldHass = this._hass;
    this._hass = hass;
    applyTerminalPalette(this.shadowRoot, hass, this._config);

    if (hass && oldHass !== hass) {
      // Only touch the DOM (chart redraws, bar widths, etc.) when one of
      // our own entities actually changed - see anyStateChanged().
      if (anyStateChanged(oldHass, hass, this._relevantEntityIds())) {
        this.updateCard();
      }
      // Fetch history data periodically (every 5 minutes)
      if (!this._historyUpdateInterval) {
        this._fetchHistory();
        this._historyUpdateInterval = setInterval(() => this._fetchHistory(), 5 * 60 * 1000);
      }
    }
  }

  _relevantEntityIds() {
    const e = this._config.entities || {};
    return [
      this._resolve('download', e.download), this._resolve('upload', e.upload),
      this._resolve('ping', e.ping), this._resolve('jitter', e.jitter),
      this._resolve('server', e.server), this._resolve('last_test', e.last_test),
      this._resolve('backend', e.backend),
      this._resolve('running', e.running, 'binary_sensor'),
      this._resolve('dl_compliance', e.dl_compliance), this._resolve('ul_compliance', e.ul_compliance),
      this._resolve('data_downloaded', e.data_downloaded), this._resolve('data_uploaded', e.data_uploaded),
      this._resolve('lifetime_download', e.lifetime_download), this._resolve('lifetime_upload', e.lifetime_upload),
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
    // Fetch history immediately if hass is already available
    if (this._hass && this._config.show_charts) {
      this._fetchHistory();
    }
  }

  /**
   * Card size for Masonry view (1 = 50px)
   * Adjust size based on enabled features
   */
  getCardSize() {
    let size = 10; // Base size for metric cards and footer
    if (this._config.show_gauges) size += 3;
    if (this._config.show_charts) size += 8; // two live TRAFFIC.LIVE-style chart cards
    return size;
  }

  static getGridOptions() {
    return { columns: 6, rows: "auto" };
  }

  getGridOptions() {
    return { columns: 6, rows: "auto" };
  }

  async _fetchHistory() {
    if (!this._hass || !this._config.show_charts) return;

    const e = this._config.entities;
    const download = this._resolve('download', e.download);
    const upload = this._resolve('upload', e.upload);
    const ping = this._resolve('ping', e.ping);
    const jitter = this._resolve('jitter', e.jitter);
    const entities = [download, upload, ping, jitter].filter(id => id);

    if (entities.length === 0) return;

    const hours = this._config.history_hours || 168; // Default 7 days
    const endTime = new Date();
    const startTime = new Date(endTime.getTime() - hours * 60 * 60 * 1000);

    try {
      const history = await this._hass.callWS({
        type: 'history/history_during_period',
        start_time: startTime.toISOString(),
        end_time: endTime.toISOString(),
        entity_ids: entities,
        minimal_response: true,
        significant_changes_only: false
      });

      // Process history data. Each point keeps its timestamp (not just the
      // value) so charts can show an x-axis range and a hover tooltip.
      this._history = { download: [], upload: [], ping: [], jitter: [] };

      if (history) {
        // History is an object with entity_id as keys
        entities.forEach((entityId) => {
          const entityHistory = history[entityId];
          let key = null;

          if (entityId === download) key = 'download';
          else if (entityId === upload) key = 'upload';
          else if (entityId === ping) key = 'ping';
          else if (entityId === jitter) key = 'jitter';

          if (key && entityHistory && Array.isArray(entityHistory)) {
            entityHistory.forEach(state => {
              const value = parseFloat(state.s || state.state);
              const t = state.lu ? state.lu * 1000 : (state.last_updated ? Date.parse(state.last_updated) : NaN);
              if (!isNaN(value) && value >= 0 && !isNaN(t)) {
                this._history[key].push({ t, v: value });
              }
            });
          }
        });

        // Sample recorder history down to a density sensible for these
        // small/medium charts (fixed, not user-configurable).
        const maxPoints = 60;
        Object.keys(this._history).forEach(key => {
          const data = this._history[key];
          if (data.length > maxPoints) {
            const step = Math.ceil(data.length / maxPoints);
            this._history[key] = data.filter((_, i) => i % step === 0);
          }
        });
      }

      if (this._config.show_charts) {
        this._drawCharts();
      }
    } catch (error) {
      console.error('Failed to fetch history:', error);
      // Fallback to current values if history fetch fails
      const now = Date.now();
      this._history = {
        download: [{ t: now, v: parseFloat(this._getState(download)) || 0 }],
        upload: [{ t: now, v: parseFloat(this._getState(upload)) || 0 }],
        ping: [{ t: now, v: parseFloat(this._getState(ping)) || 0 }],
        jitter: [{ t: now, v: parseFloat(this._getState(jitter)) || 0 }]
      };
      if (this._config.show_charts) {
        this._drawCharts();
      }
    }
  }

  disconnectedCallback() {
    if (this._historyUpdateInterval) {
      clearInterval(this._historyUpdateInterval);
      this._historyUpdateInterval = null;
    }
  }

  updateCard() {
    if (!this._hass) return;

    const restoreScroll = beginScrollAnchor();
    const e = this._config.entities;

    // Main Metrics
    this._updateMetricValue('.metric-dl', this._resolve('download', e.download), true);
    this._updateMetricValue('.metric-ul', this._resolve('upload', e.upload), true);
    this._updateMetricValue('.metric-ping', this._resolve('ping', e.ping));
    this._updateMetricValue('.metric-jitter', this._resolve('jitter', e.jitter));

    // Update gauges if enabled. Scale defaults to the configured ISP rated
    // speed (with headroom) when max_download/max_upload aren't explicitly
    // set, so the ring reads near-full at your plan's actual speed.
    if (this._config.show_gauges) {
      const download = parseFloat(this._getState(this._resolve('download', e.download))) || 0;
      const upload = parseFloat(this._getState(this._resolve('upload', e.upload))) || 0;
      const maxDownload = this._config.max_download || this._autoGaugeMax('download', 1000);
      const maxUpload = this._config.max_upload || this._autoGaugeMax('upload', 500);
      this._updateGauge('download', download, maxDownload);
      this._updateGauge('upload', upload, maxUpload);
    }

    // Optional Metrics. Units are static markup (see render()); JS only
    // ever sets the bare numeric value.
    const optionalFields = [
      { key: 'dl_compliance', bar: true },
      { key: 'ul_compliance', bar: true },
      { key: 'data_downloaded' },
      { key: 'data_uploaded' },
      { key: 'lifetime_download' },
      { key: 'lifetime_upload' }
    ];

    optionalFields.forEach(field => {
      const entityId = this._resolve(field.key, e[field.key]);
      const el = this.shadowRoot.querySelector(`.metric-${field.key.replace(/_/g, '-')}`);
      if (el) {
        const state = this._getState(entityId);
        const valueEl = el.querySelector('.value');
        if (valueEl) valueEl.setAttribute('data-val', state !== null ? state : '--');
        if (field.bar) {
          const percent = Math.min(Math.max(parseFloat(state) || 0, 0), 100);
          const fill = el.querySelector('.bar-fill');
          if (fill) {
            fill.style.width = `${percent}%`;
            let color = getTerminalColor(this._hass, 'danger', '#dc2626', this._config);
            if (percent >= 70) color = getTerminalColor(this._hass, 'warning', '#c97b1a', this._config);
            if (percent >= 95) color = getTerminalColor(this._hass, 'success', '#16a34a', this._config);
            fill.style.background = color;
          }
          const rated = parseFloat(this._hass.states[entityId]?.attributes?.isp_rated_speed);
          const subtitleEl = el.querySelector('.subtitle');
          if (subtitleEl) subtitleEl.textContent = rated > 0 ? `rated ${rated} Mbps` : '';
        }
        el.style.display = (entityId && this._hass.states[entityId]) ? 'flex' : 'none';
      }
    });

    // Server
    this.shadowRoot.querySelector('.server-name')?.setAttribute('data-text', this._getState(this._resolve('server', e.server)) || 'Unknown Server');

    // Internet connectivity status + public IP, independent of speed test data.
    const netState = this._getState(this._resolve('internet_connected', e.internet_connected, 'binary_sensor'));
    const netStateEl = this.shadowRoot.querySelector('.net-state');
    if (netStateEl) {
      const isOnline = netState === 'on';
      netStateEl.classList.toggle('online', isOnline);
      netStateEl.textContent = netState === null ? 'Unknown' : (isOnline ? 'Online' : 'Offline');
    }
    const ip = this._getState(this._resolve('public_ip', e.public_ip, 'sensor'));
    const netIpEl = this.shadowRoot.querySelector('.net-ip');
    if (netIpEl) netIpEl.textContent = ip || '';

    // Last test
    const lastTestEl = this.shadowRoot.querySelector('.last-test');
    if (lastTestEl) {
      const backendState = this._getState(this._resolve('backend', e.backend));
      const backendLabel = backendState ? (BACKEND_LABELS[backendState] || backendState) : '';
      const testTime = this._formatTime(this._getState(this._resolve('last_test', e.last_test)));
      lastTestEl.textContent = backendLabel ? `${testTime} \u00b7 ${backendLabel}` : testTime;
    }

    // Run button reflects the real speed_test_running binary_sensor, with a
    // brief optimistic state right after a click to bridge the gap before
    // the sensor flips to "on".
    const runningState = this._getRawState(this._resolve('running', e.running, 'binary_sensor'));
    const isRunning = runningState === 'on' || this._pendingClick;
    const runBtn = this.shadowRoot.querySelector('#run');
    if (runBtn) {
      runBtn.classList.toggle('running', isRunning);
    }

    if (this._config.show_charts) {
      this._drawCharts();
    }

    restoreScroll();
  }

  _resolve(key, entityId, fallbackDomain) {
    return resolvePaceEntity(this._hass, entityId, ENTITY_SUFFIXES[key], fallbackDomain);
  }

  _autoGaugeMax(direction, fallback) {
    const suffix = direction === 'download' ? 'download_plan_compliance' : 'upload_plan_compliance';
    const entityId = resolvePaceEntity(this._hass, undefined, suffix, 'sensor');
    const rated = parseFloat(this._hass.states[entityId]?.attributes?.isp_rated_speed);
    return rated > 0 ? Math.ceil(rated * 1.2) : fallback;
  }

  _updateMetricValue(selector, entityId, round = false) {
    const el = this.shadowRoot.querySelector(selector + ' .value');
    if (!el) return;
    let val = this._getState(entityId);
    if (val !== null) {
      if (round) {
        const num = parseFloat(val);
        val = !isNaN(num) ? Math.round(num) : val;
      }
      el.setAttribute('data-val', val);
    } else {
      el.setAttribute('data-val', '--');
    }
  }

  _updateGauge(type, value, max) {
    const gauge = this.shadowRoot.querySelector(`.gauge-${type} .gauge-fill`);
    const valueEl = this.shadowRoot.querySelector(`.gauge-${type} .gauge-value`);

    if (!gauge || !valueEl) return;

    const numValue = parseFloat(value) || 0;
    const percentage = Math.min((numValue / max) * 100, 100);

    const maxArc = 424;
    const offset = maxArc * (1 - percentage / 100);

    gauge.style.strokeDashoffset = offset;

    let color = getTerminalColor(this._hass, 'danger', '#dc2626', this._config);
    if (percentage >= 50) color = getTerminalColor(this._hass, 'accent', '#2563eb', this._config);
    if (percentage >= 80) color = getTerminalColor(this._hass, 'success', '#16a34a', this._config);

    gauge.style.stroke = color;
    valueEl.textContent = Math.round(numValue);
    valueEl.style.color = color;
  }

  _drawCharts() {
    if (!this._config.show_charts) return;
    this._drawSparklines();
    this._drawLiveChart('traffic', [
      { key: 'download', label: this._config.labels?.download || 'Download', unit: 'Mbps' },
      { key: 'upload', label: this._config.labels?.upload || 'Upload', unit: 'Mbps' }
    ], this._trafficFooterLeft());
    this._drawLiveChart('latency', [
      { key: 'ping', label: this._config.labels?.ping || 'Ping', unit: 'ms' },
      { key: 'jitter', label: this._config.labels?.jitter || 'Jitter', unit: 'ms' }
    ], null);
  }

  // Lifetime download/upload totals (if configured) shown in the traffic
  // chart's footer, standing in for FRITZ!Portal's TRAFFIC.LIVE month total.
  _trafficFooterLeft() {
    const e = this._config.entities;
    const dl = this._getState(this._resolve('lifetime_download', e.lifetime_download));
    const ul = this._getState(this._resolve('lifetime_upload', e.lifetime_upload));
    if (dl === null && ul === null) return null;
    return `TOTAL ↓ ${dl ?? '--'} GB — ↑ ${ul ?? '--'} GB`;
  }

  // Builds a smooth (Catmull-Rom) SVG path through a set of points, giving
  // charts the same gently-curved look as FRITZ!Portal's TRAFFIC.LIVE graph
  // instead of a straight-segment polyline.
  _smoothPath(points) {
    let d = `M${points[0][0]},${points[0][1]}`;
    for (let i = 0; i < points.length - 1; i++) {
      const p0 = points[i - 1] || points[i];
      const p1 = points[i];
      const p2 = points[i + 1];
      const p3 = points[i + 2] || p2;
      const c1x = p1[0] + (p2[0] - p0[0]) / 6;
      const c1y = p1[1] + (p2[1] - p0[1]) / 6;
      const c2x = p2[0] - (p3[0] - p1[0]) / 6;
      const c2y = p2[1] - (p3[1] - p1[1]) / 6;
      d += ` C${c1x},${c1y} ${c2x},${c2y} ${p2[0]},${p2[1]}`;
    }
    return d;
  }

  _gridLinesSvg(width, height, fractions = [0.25, 0.5, 0.75]) {
    return fractions.map(fraction => {
      const y = (height * fraction).toFixed(1);
      return `<line x1="0" y1="${y}" x2="${width}" y2="${y}" stroke="var(--divider-color, #2a3142)" stroke-width="0.5" stroke-dasharray="2 5" vector-effect="non-scaling-stroke" />`;
    }).join('');
  }

  // Fixed look-and-feel for every chart (not user-configurable), matching
  // FRITZ!Portal's documented TRAFFIC.LIVE recharts spec: 1.6px strokes,
  // gradient fills 18% -> 0%, dashed grid lines (see _gridLinesSvg).
  _renderSeriesShapes(type, points, width, height, gradientId) {
    const path = this._smoothPath(points);
    const color = this._chartColor(type);
    const area = `<path d="${path} L${width},${height} L0,${height} Z" fill="url(#${gradientId})" stroke="none" />`;

    return `
      <defs>
        <linearGradient id="${gradientId}" x1="0%" y1="0%" x2="0%" y2="100%">
          <stop offset="0%" style="stop-color:${color};stop-opacity:0.18" />
          <stop offset="100%" style="stop-color:${color};stop-opacity:0" />
        </linearGradient>
      </defs>
      ${area}
      <path d="${path}" fill="none" stroke="${color}" stroke-width="1.6" vector-effect="non-scaling-stroke" stroke-linecap="round" stroke-linejoin="round"/>
    `;
  }

  _scaledPoints(data, min, range, width, height) {
    const chartData = data.length === 1 ? [data[0], data[0]] : data;
    return chartData.map((val, i) => [(i / (chartData.length - 1)) * width, height - ((val - min) / range) * height]);
  }

  // Small trend-only indicator line inside each of the 4 main stat cards
  // (no axis/grid, just a quick glance at the recent trend).
  _drawSparklines() {
    ['download', 'upload', 'ping', 'jitter'].forEach(type => {
      const svg = this.shadowRoot.querySelector(`${METRIC_CARD_SELECTOR[type]} .indicator-chart svg`);
      if (!svg) return;

      const data = (this._history[type] || []).map(p => p.v);
      if (data.length === 0) {
        svg.innerHTML = '';
        return;
      }

      const width = 100;
      const height = 24;
      const max = Math.max(...data, 1);
      const min = Math.min(...data);
      const range = max - min || 1;

      const points = this._scaledPoints(data, min, range, width, height);
      svg.innerHTML = this._renderSeriesShapes(type, points, width, height, `grad-spark-${type}`);
    });
  }

  // Rounds up to a "nice" axis maximum (1/2/5 * 10^n) so gridline labels
  // read as clean numbers instead of arbitrary decimals.
  _niceAxisMax(value) {
    if (!(value > 0)) return 1;
    const exp = Math.floor(Math.log10(value));
    const base = Math.pow(10, exp);
    const n = value / base;
    const niceN = n <= 1 ? 1 : n <= 2 ? 2 : n <= 5 ? 5 : 10;
    return niceN * base;
  }

  _formatClock(ts) {
    if (!ts) return '--:--';
    return new Date(ts).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  }

  _formatAxisValue(value) {
    return value < 10 ? value.toFixed(1) : Math.round(value).toString();
  }

  // Renders one of the big FRITZ!Portal TRAFFIC.LIVE-style chart cards:
  // shared 0..niceMax y-axis across all series, start/end x-axis time
  // labels, a live legend, and (via _attachChartHover) a value tooltip.
  _drawLiveChart(chartKey, series, footerLeft) {
    const root = this.shadowRoot.querySelector(`.chart-card-${chartKey}`);
    if (!root) return;

    const svg = root.querySelector('.chart-plot svg');
    const seriesData = series.map(s => (this._history[s.key] || []));
    const allValues = seriesData.flat().map(p => p.v);
    const hasData = allValues.length > 0;

    const width = 300;
    const height = 120;
    const niceMax = this._niceAxisMax(Math.max(...allValues, 0));

    if (hasData && svg) {
      const shapes = series.map((s, i) => {
        const values = seriesData[i].map(p => p.v);
        if (values.length === 0) return '';
        const points = this._scaledPoints(values, 0, niceMax, width, height);
        return this._renderSeriesShapes(s.key, points, width, height, `grad-${chartKey}-${s.key}`);
      }).join('');
      svg.innerHTML = `${this._gridLinesSvg(width, height, [0, 0.25, 0.5, 0.75, 1])}${shapes}`;
    } else if (svg) {
      svg.innerHTML = '';
    }

    // Y axis labels, top (niceMax) to bottom (0)
    root.querySelectorAll('.chart-yaxis span').forEach((el, i) => {
      el.textContent = this._formatAxisValue(niceMax * (1 - i / 4));
    });

    // X axis: first/last timestamp across all series
    const allPoints = seriesData.flat().sort((a, b) => a.t - b.t);
    const xStart = root.querySelector('.chart-xaxis .x-start');
    const xEnd = root.querySelector('.chart-xaxis .x-end');
    if (xStart) xStart.textContent = allPoints.length ? this._formatClock(allPoints[0].t) : '--:--';
    if (xEnd) xEnd.textContent = allPoints.length ? this._formatClock(allPoints[allPoints.length - 1].t) : '--:--';

    // Legend current values
    series.forEach(s => {
      const el = root.querySelector(`.legend-${s.key} b`);
      if (!el) return;
      const current = parseFloat(this._getState(this._resolve(s.key, this._config.entities[s.key])));
      el.textContent = !isNaN(current) ? current.toFixed(1) : '--';
    });

    const footerEl = root.querySelector('.chart-foot-left');
    if (footerEl) footerEl.textContent = footerLeft || '';

    const footerRight = root.querySelector('.chart-foot-right');
    if (footerRight) footerRight.textContent = `${this._config.history_hours || 168}H RANGE — ${allPoints.length} PTS`;
  }

  // Shared pointer/touch hover handler wired once per chart in render():
  // shows a crosshair + tooltip with each series' nearest value and time.
  // Shared pointer/touch hover handler wired once per chart in render():
  // shows a crosshair + tooltip, and (matching FRITZ!Portal) a small white
  // dot marking each series' exact point on the line under the cursor.
  _attachChartHover(plotEl, series) {
    const tooltip = plotEl.querySelector('.chart-tooltip');
    const crosshair = plotEl.querySelector('.chart-crosshair');
    if (!tooltip || !crosshair) return;

    const dots = series.map(() => {
      const dot = document.createElement('div');
      dot.className = 'chart-dot';
      dot.hidden = true;
      plotEl.appendChild(dot);
      return dot;
    });

    const move = (clientX) => {
      const rect = plotEl.getBoundingClientRect();
      const fraction = Math.min(Math.max((clientX - rect.left) / rect.width, 0), 1);

      // Same 0..niceMax scale _drawLiveChart used, so the dot lands exactly
      // on the rendered line instead of an approximate position.
      const allValues = series.flatMap(s => (this._history[s.key] || []).map(p => p.v));
      const niceMax = this._niceAxisMax(Math.max(...allValues, 0));

      let time = null;
      const rows = [];
      series.forEach((s, i) => {
        const data = this._history[s.key] || [];
        if (data.length === 0) {
          dots[i].hidden = true;
          return;
        }
        const idx = Math.round(fraction * (data.length - 1));
        const point = data[idx];
        if (time === null) time = point.t;
        rows.push({ ...s, value: point.v });

        const topPercent = Math.min(Math.max(1 - point.v / niceMax, 0), 1) * 100;
        dots[i].style.left = `${fraction * 100}%`;
        dots[i].style.top = `${topPercent}%`;
        dots[i].style.borderColor = this._chartColor(s.key);
        dots[i].hidden = false;
      });

      if (rows.length === 0) return;

      crosshair.style.left = `${fraction * 100}%`;
      crosshair.hidden = false;

      tooltip.innerHTML = `<div class="tooltip-time">${this._formatClock(time)}</div>` + rows.map(r =>
        `<div class="tooltip-row"><i style="background:${this._chartColor(r.key)}"></i>${r.label} <b>${r.value.toFixed(1)}</b> ${r.unit}</div>`
      ).join('');
      tooltip.hidden = false;

      // Position in real pixels and clamp against the tooltip's actual
      // rendered width (not an assumed 100%) so it never spills past
      // either edge of the chart.
      const margin = 8;
      const cursorX = fraction * rect.width;
      const tooltipWidth = tooltip.offsetWidth;
      let left = cursorX + margin;
      if (left + tooltipWidth > rect.width) left = cursorX - tooltipWidth - margin;
      left = Math.min(Math.max(left, 0), Math.max(rect.width - tooltipWidth, 0));
      tooltip.style.left = `${left}px`;
    };

    const hide = () => {
      tooltip.hidden = true;
      crosshair.hidden = true;
      dots.forEach(dot => { dot.hidden = true; });
    };

    plotEl.addEventListener('pointermove', (ev) => move(ev.clientX));
    plotEl.addEventListener('pointerdown', (ev) => move(ev.clientX));
    plotEl.addEventListener('pointerleave', hide);
    // On touch devices, a tap-then-drag gesture that the browser recognizes
    // as a page scroll (allowed by touch-action: pan-y) cancels the pointer
    // instead of firing pointerleave/pointerup, so without this the tooltip
    // stayed stuck on screen after scrolling away.
    plotEl.addEventListener('pointercancel', hide);
    plotEl.addEventListener('pointerup', hide);
  }

  _chartColor(type) {
    const defaults = {
      download: getTerminalColor(this._hass, 'accent', '#2563eb', this._config),
      upload: getTerminalColor(this._hass, 'upload', '#7c3aed', this._config),
      ping: getTerminalColor(this._hass, 'ping', '#d97706', this._config),
      jitter: getTerminalColor(this._hass, 'jitter', '#db2777', this._config)
    };
    return defaults[type];
  }

  _getState(entityId) {
    if (!this._hass || !entityId) return null;
    const state = this._hass.states[entityId];
    if (!state || state.state === 'unknown' || state.state === 'unavailable') return null;
    return state.state;
  }

  _getRawState(entityId) {
    if (!this._hass || !entityId) return null;
    return this._hass.states[entityId]?.state ?? null;
  }

  _formatTime(dateStr) {
    if (!dateStr || dateStr === 'unknown' || dateStr === 'unavailable') return 'Never tested';
    try {
      const date = new Date(dateStr);
      const now = new Date();
      const diff = Math.floor((now - date) / 1000);
      if (diff < 60) return 'Just now';
      if (diff < 3600) return `${Math.floor(diff / 60)} min ago`;
      if (diff < 86400) return `${Math.floor(diff / 3600)} hours ago`;
      return date.toLocaleDateString();
    } catch { return dateStr; }
  }

  _showMoreInfo(entityId) {
    if (!entityId) return;
    const event = new CustomEvent('hass-more-info', { bubbles: true, composed: true, detail: { entityId } });
    this.dispatchEvent(event);
  }

    render() {
      if (this.shadowRoot.innerHTML !== '') return; // Prevent re-rendering loop if already rendered

      const e = this._config.entities;
      const labels = this._config.labels || { download: 'Download', upload: 'Upload', ping: 'Ping', jitter: 'Jitter' };
      // Literal corner-bracket glyphs (fritz-portal-card.js's .tile technique).
      const cornerGlyphs = '<span class="tk tl">┌</span><span class="tk tr">┐</span><span class="tk bl">└</span><span class="tk br">┘</span>';

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
             fonts, card chrome, and typography instead of the terminal/
             FRITZ!Portal look (mirrors fritz-portal-card.js's :host([ha])). */
          :host([ha]) .card,
          :host([ha]) .server-name,
          :host([ha]) .run-btn {
            font-family: var(--ha-font-family-body, var(--paper-font-body1_-_font-family, Roboto, sans-serif));
          }
          :host([ha]) .card {
            border-radius: var(--ha-card-border-radius, 12px);
            box-shadow: var(--ha-card-box-shadow, 0 2px 2px 0 rgba(0, 0, 0, 0.14), 0 1px 5px 0 rgba(0, 0, 0, 0.12), 0 3px 1px -2px rgba(0, 0, 0, 0.2));
          }
          :host([ha]) .isp-name::before,
          :host([ha]) .chart-title::before,
          :host([ha]) .metric .tk {
            display: none;
          }
          :host([ha]) .isp-name { font-size: 20px; font-weight: 400; letter-spacing: 0; }
          :host([ha]) .metric,
          :host([ha]) .chart-card,
          :host([ha]) .run-btn {
            border-radius: 8px;
          }
          :host([ha]) .bar-track,
          :host([ha]) .bar-fill {
            border-radius: 2px;
          }
          :host([ha]) .metric .label,
          :host([ha]) .server-name,
          :host([ha]) .chart-xaxis,
          :host([ha]) .chart-foot,
          :host([ha]) .chart-legend,
          :host([ha]) .gauge-label,
          :host([ha]) .chart-title {
            text-transform: none;
            letter-spacing: 0;
          }

          .card {
            background: var(--ha-card-background, var(--card-background-color, #1b2130));
            border-radius: var(--ha-card-border-radius, 0px);
            padding: 12px;
            padding-left: max(12px, env(safe-area-inset-left));
            padding-right: max(12px, env(safe-area-inset-right));
            border: 1px solid var(--ha-card-border-color, var(--divider-color, #2a3142));
            box-shadow: var(--ha-card-box-shadow, none);
            color: var(--primary-text-color, #f8fafc);
            font-family: ${TERMINAL_FONT_MONO};
            width: 100%;
            height: 100%;
            min-height: 0;
            display: flex;
            flex-direction: column;
            overflow: auto;
            flex: 1;
            direction: ltr;
          }
          .header { margin-bottom: 10px; display: flex; justify-content: space-between; align-items: flex-start; flex-shrink: 0; }
          .isp-name { font-size: 16px; font-weight: 600; letter-spacing: 0.4px; margin-bottom: 4px; color: var(--primary-text-color, #f8fafc); }
          .isp-name::before { content: '┃ '; color: var(--pace-accent-color, var(--ls-accent, #2b6fd9)); font-weight: 500; }
          .server-name { font-size: 11px; font-family: ${TERMINAL_FONT_MONO}; color: var(--secondary-text-color, #94a3b8); letter-spacing: 0.3px; display: flex; align-items: center; gap: 6px; min-width: 0; }
          .server-name::before { content: attr(data-text); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
          .net-status { text-align: right; flex-shrink: 0; }
          .net-state { font-size: 12px; font-weight: 700; letter-spacing: 1px; text-transform: uppercase; color: var(--ls-danger, #ff6b6b); }
          .net-state.online { color: var(--ls-success, #4ad19a); }
          .net-ip { font-size: 10px; font-family: ${TERMINAL_FONT_MONO}; color: var(--secondary-text-color, #64748b); margin-top: 2px; }

          .metrics-grid {
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 8px;
            margin-bottom: 10px;
            flex-shrink: 0;
          }
          /* FRITZ!Portal-style stat card: label, big value + unit, optional
             muted subtitle, optional trend sparkline or capacity bar. */
          .metric {
            position: relative;
            background: var(--ls-panel, var(--secondary-background-color, #10141b));
            border-radius: 0;
            padding: 10px 12px;
            border: 1px solid var(--divider-color, #2a3142);
            cursor: pointer;
            transition: background-color 0.15s ease;
            touch-action: manipulation;
            -webkit-tap-highlight-color: transparent;
            display: flex;
            flex-direction: column;
            gap: 4px;
          }
          .metric:hover { background: var(--ls-panel, #171d27); filter: brightness(1.15); }
          .metric:active { background: var(--ls-panel, #171d27); filter: brightness(1.3); }
          /* FRITZ!Portal corner-bracket frame: literal Unicode box-drawing
             glyphs sitting right on the border corners (not CSS-drawn
             rectangles), exactly as fritz-portal-card.js's .tile does it.
             Only on the 4 stat cards that actually carry a sparkline,
             colored to match that card's own graph line. */
          .metric-dl { --metric-accent: var(--pace-accent-color, var(--ls-accent, #2563eb)); }
          .metric-ul { --metric-accent: var(--ls-upload, #7c3aed); }
          .metric-ping { --metric-accent: var(--ls-ping, #d97706); }
          .metric-jitter { --metric-accent: var(--ls-jitter, #db2777); }
          .metric .tk { position: absolute; font-size: 10px; line-height: 1; color: var(--metric-accent); pointer-events: none; }
          .metric .tk.tl { top: -2px; left: -1px; }
          .metric .tk.tr { top: -2px; right: -1px; }
          .metric .tk.bl { bottom: -3px; left: -1px; }
          .metric .tk.br { bottom: -3px; right: -1px; }
          .metric .label { font-size: 9px; color: var(--secondary-text-color, #94a3b8); text-transform: uppercase; letter-spacing: 0.8px; font-weight: 600; }
          .metric .value-row { display: flex; align-items: baseline; gap: 3px; }
          .metric .value { font-size: 22px; font-weight: 800; line-height: 1; letter-spacing: -0.3px; color: var(--primary-text-color, #f8fafc); }
          .metric .value::before { content: attr(data-val); }
          .metric .unit { font-size: 11px; font-weight: 600; color: var(--secondary-text-color, #94a3b8); }
          .metric .subtitle { font-size: 9px; color: var(--secondary-text-color, #64748b); min-height: 11px; }
          .metric .subtitle:not(:empty)::before { content: '— '; }
          .metric .indicator { margin-top: 2px; }
          .metric .indicator-chart svg { width: 100%; height: 24px; display: block; overflow: visible; }
          .metric .bar-track { width: 100%; height: 4px; border-radius: 0; background: var(--divider-color, #2a3142); overflow: hidden; }
          .metric .bar-fill { height: 100%; width: 0%; border-radius: 0; transition: width 0.4s ease, background-color 0.3s ease; }

          .optional-grid {
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 6px;
            margin-bottom: 10px;
            border-top: 1px solid var(--divider-color, rgba(255,255,255,0.05));
            padding-top: 10px;
            flex-shrink: 0;
          }
          .optional-grid .metric { padding: 8px 10px; gap: 3px; }
          .optional-grid .metric .value { font-size: 15px; }

          .metric-dl .value { color: var(--pace-accent-color, var(--ls-accent, #2563eb)); }
          .metric-ul .value { color: var(--ls-upload, #7c3aed); }
          .metric-ping .value { color: var(--ls-ping, #d97706); }
          .metric-jitter .value { color: var(--ls-jitter, #db2777); }

          /* Gauge Styles */
          .gauges-container {
            display: flex;
            justify-content: center;
            gap: 16px;
            margin: 10px 0;
            flex-shrink: 0;
          }

          .gauge {
            position: relative;
            width: 110px;
            height: 110px;
            flex-shrink: 0;
          }

          .gauge-svg {
            transform: rotate(135deg);
            width: 100%;
            height: 100%;
          }

          .gauge-bg {
            fill: none;
            stroke: var(--divider-color, #2a3142);
            stroke-width: 10;
            stroke-linecap: round;
            stroke-dasharray: 424 566;
            stroke-dashoffset: 0;
          }

          .gauge-fill {
            fill: none;
            stroke-width: 10;
            stroke-linecap: round;
            stroke-dasharray: 424 566;
            stroke-dashoffset: 424;
            transition: stroke-dashoffset 1s cubic-bezier(0.4, 0, 0.2, 1), stroke 0.3s ease;
          }

          .gauge-content {
            position: absolute;
            top: 50%;
            left: 50%;
            transform: translate(-50%, -50%);
            text-align: center;
            display: flex;
            flex-direction: column;
            align-items: center;
          }

          .gauge-label {
            font-size: 9px;
            color: var(--secondary-text-color, #94a3b8);
            text-transform: uppercase;
            letter-spacing: 1px;
            margin-bottom: 4px;
            font-weight: 600;
          }

          .gauge-value {
            font-size: 24px;
            font-weight: 800;
            color: var(--primary-text-color, #fff);
            line-height: 1;
            letter-spacing: -0.5px;
          }

          .gauge-unit {
            font-size: 9px;
            color: var(--secondary-text-color, #64748b);
            margin-top: 2px;
            font-weight: 500;
          }

          /* FRITZ!Portal TRAFFIC.LIVE-style live chart cards (traffic +
             latency): title/legend header, y-axis labels beside the plot,
             x-axis start/end time, and a hover tooltip + crosshair. */
          .chart-card {
            position: relative;
            background: var(--ls-panel, var(--secondary-background-color, #10141b));
            border-radius: 0;
            padding: 10px 12px;
            border: 1px solid var(--divider-color, #2a3142);
            margin-bottom: 10px;
            flex-shrink: 0;
          }
          .chart-head { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 6px; margin-bottom: 8px; }
          .chart-title { font-size: 11px; font-weight: 600; letter-spacing: 0.3px; color: var(--primary-text-color, #f8fafc); }
          .chart-title::before { content: '┃ '; color: var(--pace-accent-color, var(--ls-accent, #2b6fd9)); }
          .chart-legend { display: flex; gap: 14px; font-size: 10px; color: var(--secondary-text-color, #94a3b8); }
          .chart-legend span { display: flex; align-items: center; gap: 5px; white-space: nowrap; }
          .chart-legend i { width: 8px; height: 8px; border-radius: 0; display: inline-block; flex-shrink: 0; }
          .chart-legend b { color: var(--primary-text-color, #f8fafc); font-weight: 700; display: inline-block; min-width: 3ch; text-align: right; }
          .chart-body { display: flex; gap: 6px; }
          .chart-yaxis { display: flex; flex-direction: column; justify-content: space-between; font-size: 8px; color: var(--secondary-text-color, #64748b); text-align: right; padding: 2px 0; }
          .chart-plot { position: relative; flex: 1; min-width: 0; touch-action: pan-y; }
          .chart-plot svg { width: 100%; height: 110px; display: block; overflow: visible; }
          .chart-crosshair { position: absolute; top: 0; bottom: 0; width: 1px; background: var(--divider-color, #3a4554); pointer-events: none; transition: left 0.12s cubic-bezier(0.34, 1.56, 0.64, 1); }
          /* FRITZ!Portal-style hover marker: a small white dot on each
             series' line, sitting right on the crosshair. */
          .chart-dot {
            position: absolute;
            top: 0;
            left: 0;
            width: 7px;
            height: 7px;
            border-radius: 50%;
            background: #fff;
            border: 2px solid var(--ls-accent, #2563eb);
            box-shadow: 0 0 3px rgba(0, 0, 0, 0.5);
            transform: translate(-50%, -50%);
            transition: left 0.12s cubic-bezier(0.34, 1.56, 0.64, 1), top 0.12s cubic-bezier(0.34, 1.56, 0.64, 1);
            pointer-events: none;
            z-index: 3;
          }
          .chart-tooltip {
            position: absolute;
            top: 4px;
            min-width: 90px;
            background: var(--card-background-color, #10141d);
            border: 1px solid var(--divider-color, #2a3142);
            border-radius: 0;
            transition: left 0.12s cubic-bezier(0.34, 1.56, 0.64, 1);
            padding: 5px 8px;
            font-size: 9px;
            line-height: 1.5;
            pointer-events: none;
            white-space: nowrap;
            z-index: 2;
          }
          .chart-tooltip .tooltip-time { color: var(--secondary-text-color, #64748b); margin-bottom: 2px; }
          .chart-tooltip .tooltip-row { display: flex; align-items: center; gap: 5px; color: var(--secondary-text-color, #94a3b8); }
          .chart-tooltip .tooltip-row i { width: 6px; height: 6px; border-radius: 50%; display: inline-block; }
          .chart-tooltip .tooltip-row b { color: var(--primary-text-color, #f8fafc); }
          .chart-xaxis { display: flex; justify-content: space-between; font-size: 8px; color: var(--secondary-text-color, #64748b); margin: 4px 0 8px 0; padding-left: 22px; }
          .chart-foot { display: flex; justify-content: space-between; gap: 8px; font-size: 9px; color: var(--secondary-text-color, #64748b); padding-top: 8px; border-top: 1px solid var(--divider-color, rgba(255,255,255,0.05)); }
          .chart-foot span { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; min-width: 0; }

          .footer {
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding-top: 10px;
            border-top: 1px solid var(--divider-color, rgba(255,255,255,0.05));
            flex-shrink: 0;
          }
          .last-test { font-size: 11px; color: var(--secondary-text-color, #64748b); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; min-width: 0; }
          .run-btn {
            padding: 6px 15px; border: 1px solid var(--pace-accent-color, var(--ls-accent, #2563eb)); border-radius: 0;
            background: transparent;
            color: var(--pace-accent-color, var(--ls-accent, #2563eb));
            font-family: ${TERMINAL_FONT_MONO};
            font-size: 12px; font-weight: 600; letter-spacing: 0.4px; cursor: pointer; transition: background-color 0.15s ease, color 0.15s ease;
            min-height: 32px;
            min-width: 80px;
            touch-action: manipulation;
            -webkit-tap-highlight-color: transparent;
          }
          .run-btn:hover { background: var(--pace-accent-color, var(--ls-accent, #2563eb)); color: #fff; }
          .run-btn:active { filter: brightness(0.9); }
          .run-btn.running { background: var(--ls-success, #16a34a); border-color: var(--ls-success, #16a34a); color: #fff; animation: pulse 1.5s infinite; }
          @keyframes pulse { 0% { opacity: 1; } 50% { opacity: 0.7; } 100% { opacity: 1; } }

          /* Container query responsive adjustments */
          @container (max-width: 500px) {
            .card { padding: 14px; }
            .isp-name { font-size: 16px; }
            .server-name { font-size: 11px; }
            .metrics-grid { grid-template-columns: repeat(2, 1fr); gap: 8px; }
            .metric .label { font-size: 8px; }
            .metric .value { font-size: 19px; }
            .optional-grid { grid-template-columns: repeat(2, 1fr); gap: 6px; }
            .optional-grid .metric .value { font-size: 13px; }
            .optional-grid .metric .label { font-size: 7px; }
            .gauge { width: 110px; height: 110px; }
            .gauge-value { font-size: 22px; }
            .gauge-label { font-size: 8px; }
            .gauge-unit { font-size: 8px; }
            .chart-legend { gap: 10px; }
            .chart-xaxis { padding-left: 18px; }
          }

          @container (max-width: 400px) {
            .card { padding: 12px; }
            .header { margin-bottom: 10px; }
            .isp-name { font-size: 15px; }
            .server-name { font-size: 10px; }
            .metrics-grid { grid-template-columns: repeat(2, 1fr); gap: 6px; margin-bottom: 10px; }
            .metric { padding: 8px 10px; }
            .metric .label { font-size: 7px; letter-spacing: 0.3px; }
            .metric .value { font-size: 17px; }
            .optional-grid { grid-template-columns: repeat(2, 1fr); gap: 5px; padding-top: 10px; margin-bottom: 10px; }
            .optional-grid .metric { padding: 6px 8px; }
            .optional-grid .metric .value { font-size: 12px; }
            .optional-grid .metric .label { font-size: 7px; }
            .gauges-container { gap: 10px; margin: 12px 0; }
            .gauge { width: 100px; height: 100px; }
            .gauge-value { font-size: 20px; }
            .gauge-label { font-size: 7px; letter-spacing: 0.5px; }
            .gauge-unit { font-size: 7px; }
            .gauge-bg, .gauge-fill { stroke-width: 9; }
            .chart-card { padding: 8px 10px; }
            .chart-head { flex-direction: column; align-items: flex-start; gap: 4px; }
            .chart-legend { gap: 10px; font-size: 9px; }
            .chart-plot svg { height: 90px; }
            .chart-yaxis { font-size: 7px; }
            .chart-xaxis { font-size: 7px; padding-left: 18px; }
            .footer { padding-top: 10px; flex-direction: column; gap: 8px; align-items: flex-start; }
            .last-test { font-size: 10px; }
            .run-btn { font-size: 11px; padding: 5px 12px; align-self: stretch; text-align: center; }
          }

          @container (max-width: 320px) {
            .card { padding: 10px; }
            .isp-name { font-size: 14px; }
            .server-name { font-size: 9px; }
            .metrics-grid { grid-template-columns: repeat(2, 1fr); gap: 5px; }
            .metric { padding: 6px 8px; }
            .metric .label { font-size: 7px; }
            .metric .value { font-size: 15px; }
            .optional-grid { grid-template-columns: repeat(2, 1fr); gap: 4px; }
            .optional-grid .metric { padding: 5px 6px; }
            .optional-grid .metric .value { font-size: 10px; }
            .optional-grid .metric .label { font-size: 6px; }
            .gauges-container { flex-direction: column; gap: 8px; margin: 10px 0; }
            .gauge { width: 90px; height: 90px; }
            .gauge-value { font-size: 18px; }
            .gauge-label { font-size: 7px; }
            .gauge-unit { font-size: 7px; }
            .gauge-bg, .gauge-fill { stroke-width: 8; }
            .chart-plot svg { height: 70px; }
            .chart-tooltip { font-size: 8px; min-width: 70px; }
            .footer { gap: 6px; }
            .last-test { font-size: 9px; }
            .run-btn { font-size: 10px; padding: 4px 10px; border-radius: 16px; }
          }

          @container (max-width: 280px) {
            .card { padding: 8px; }
            .header { margin-bottom: 8px; }
            .metrics-grid { gap: 4px; margin-bottom: 8px; }
            .optional-grid { gap: 3px; margin-bottom: 8px; padding-top: 8px; }
            .gauges-container { margin: 8px 0; }
            .gauge { width: 80px; height: 80px; }
            .gauge-value { font-size: 16px; }
            .gauge-label { font-size: 6px; }
            .gauge-unit { font-size: 6px; }
            .chart-yaxis { display: none; }
            .chart-xaxis { padding-left: 0; }
            .footer { padding-top: 8px; }
          }
  </style>

        <div class="card">
          <div class="header">
            <div class="isp-info">
              <div class="isp-name">Pace</div>
              <div class="server-name" data-text="-"></div>
            </div>
            <div class="net-status">
              <div class="net-state">OFFLINE</div>
              <div class="net-ip"></div>
            </div>
          </div>

          <div class="metrics-grid">
            <div class="metric metric-dl${this._config.show_charts ? ' has-graph' : ''}" id="m-dl">
              ${this._config.show_charts ? cornerGlyphs : ''}
              <div class="label">${labels.download}</div>
              <div class="value-row"><span class="value"></span><span class="unit">Mbps</span></div>
              ${this._config.show_charts ? '<div class="indicator indicator-chart"><svg viewBox="0 0 100 24" preserveAspectRatio="none"></svg></div>' : ''}
            </div>
            <div class="metric metric-ul${this._config.show_charts ? ' has-graph' : ''}" id="m-ul">
              ${this._config.show_charts ? cornerGlyphs : ''}
              <div class="label">${labels.upload}</div>
              <div class="value-row"><span class="value"></span><span class="unit">Mbps</span></div>
              ${this._config.show_charts ? '<div class="indicator indicator-chart"><svg viewBox="0 0 100 24" preserveAspectRatio="none"></svg></div>' : ''}
            </div>
            <div class="metric metric-ping${this._config.show_charts ? ' has-graph' : ''}" id="m-ping">
              ${this._config.show_charts ? cornerGlyphs : ''}
              <div class="label">${labels.ping}</div>
              <div class="value-row"><span class="value"></span><span class="unit">ms</span></div>
              ${this._config.show_charts ? '<div class="indicator indicator-chart"><svg viewBox="0 0 100 24" preserveAspectRatio="none"></svg></div>' : ''}
            </div>
            <div class="metric metric-jitter${this._config.show_charts ? ' has-graph' : ''}" id="m-jitter">
              ${this._config.show_charts ? cornerGlyphs : ''}
              <div class="label">${labels.jitter}</div>
              <div class="value-row"><span class="value"></span><span class="unit">ms</span></div>
              ${this._config.show_charts ? '<div class="indicator indicator-chart"><svg viewBox="0 0 100 24" preserveAspectRatio="none"></svg></div>' : ''}
            </div>
          </div>
        <div class="optional-grid" id="opt-grid">
          <div class="metric metric-dl-compliance" id="m-dlc">
            <div class="label">DL Plan</div>
            <div class="value-row"><span class="value"></span><span class="unit">%</span></div>
            <div class="subtitle"></div>
            <div class="indicator indicator-bar"><div class="bar-track"><div class="bar-fill"></div></div></div>
          </div>
          <div class="metric metric-ul-compliance" id="m-ulc">
            <div class="label">UL Plan</div>
            <div class="value-row"><span class="value"></span><span class="unit">%</span></div>
            <div class="subtitle"></div>
            <div class="indicator indicator-bar"><div class="bar-track"><div class="bar-fill"></div></div></div>
          </div>
          <div class="metric metric-data-downloaded" id="m-datadl"><div class="label">Data Down</div><div class="value-row"><span class="value"></span><span class="unit">MB</span></div></div>
          <div class="metric metric-data-uploaded" id="m-dataul"><div class="label">Data Up</div><div class="value-row"><span class="value"></span><span class="unit">MB</span></div></div>
          <div class="metric metric-lifetime-download" id="m-lifedl"><div class="label">Lifetime Down</div><div class="value-row"><span class="value"></span><span class="unit">GB</span></div></div>
          <div class="metric metric-lifetime-upload" id="m-lifeul"><div class="label">Lifetime Up</div><div class="value-row"><span class="value"></span><span class="unit">GB</span></div></div>
        </div>

        ${this._config.show_gauges ? `
        <div class="gauges-container">
          <div class="gauge gauge-download">
            <svg class="gauge-svg" viewBox="0 0 200 200">
              <circle class="gauge-bg" cx="100" cy="100" r="90"></circle>
              <circle class="gauge-fill" cx="100" cy="100" r="90"></circle>
            </svg>
            <div class="gauge-content">
              <div class="gauge-label">${labels.download}</div>
              <div class="gauge-value">0</div>
              <div class="gauge-unit">Mbps</div>
            </div>
          </div>

          <div class="gauge gauge-upload">
            <svg class="gauge-svg" viewBox="0 0 200 200">
              <circle class="gauge-bg" cx="100" cy="100" r="90"></circle>
              <circle class="gauge-fill" cx="100" cy="100" r="90"></circle>
            </svg>
            <div class="gauge-content">
              <div class="gauge-label">${labels.upload}</div>
              <div class="gauge-value">0</div>
              <div class="gauge-unit">Mbps</div>
            </div>
          </div>
        </div>
        ` : ''}

        ${this._config.show_charts ? `
        <div class="chart-card chart-card-traffic">
          <div class="chart-head">
            <div class="chart-title">THROUGHPUT</div>
            <div class="chart-legend">
              <span class="legend-download"><i style="background:${this._chartColor('download')}"></i>${labels.download} <b>0</b> Mbps</span>
              <span class="legend-upload"><i style="background:${this._chartColor('upload')}"></i>${labels.upload} <b>0</b> Mbps</span>
            </div>
          </div>
          <div class="chart-body">
            <div class="chart-yaxis"><span></span><span></span><span></span><span></span><span></span></div>
            <div class="chart-plot">
              <svg viewBox="0 0 300 120" preserveAspectRatio="none"></svg>
              <div class="chart-crosshair" hidden></div>
              <div class="chart-tooltip" hidden></div>
            </div>
          </div>
          <div class="chart-xaxis"><span class="x-start">--:--</span><span class="x-end">--:--</span></div>
          <div class="chart-foot"><span class="chart-foot-left"></span><span class="chart-foot-right"></span></div>
        </div>

        <div class="chart-card chart-card-latency">
          <div class="chart-head">
            <div class="chart-title">LATENCY</div>
            <div class="chart-legend">
              <span class="legend-ping"><i style="background:${this._chartColor('ping')}"></i>${labels.ping} <b>0</b> ms</span>
              <span class="legend-jitter"><i style="background:${this._chartColor('jitter')}"></i>${labels.jitter} <b>0</b> ms</span>
            </div>
          </div>
          <div class="chart-body">
            <div class="chart-yaxis"><span></span><span></span><span></span><span></span><span></span></div>
            <div class="chart-plot">
              <svg viewBox="0 0 300 120" preserveAspectRatio="none"></svg>
              <div class="chart-crosshair" hidden></div>
              <div class="chart-tooltip" hidden></div>
            </div>
          </div>
          <div class="chart-xaxis"><span class="x-start">--:--</span><span class="x-end">--:--</span></div>
          <div class="chart-foot"><span class="chart-foot-left"></span><span class="chart-foot-right"></span></div>
        </div>
        ` : ''}

        <div class="footer">
          <span class="last-test">Never tested</span>
          <button class="run-btn" id="run">▶ Run Test</button>
        </div>
      </div>
    `;

    applyTerminalPalette(this.shadowRoot, this._hass);

    if (this._config.show_charts) {
      const trafficPlot = this.shadowRoot.querySelector('.chart-card-traffic .chart-plot');
      if (trafficPlot) this._attachChartHover(trafficPlot, [
        { key: 'download', label: labels.download, unit: 'Mbps' },
        { key: 'upload', label: labels.upload, unit: 'Mbps' }
      ]);
      const latencyPlot = this.shadowRoot.querySelector('.chart-card-latency .chart-plot');
      if (latencyPlot) this._attachChartHover(latencyPlot, [
        { key: 'ping', label: labels.ping, unit: 'ms' },
        { key: 'jitter', label: labels.jitter, unit: 'ms' }
      ]);
      this._drawCharts();
    }

    // Event Listeners
    const clickMap = {
      '#m-dl': this._resolve('download', e.download), '#m-ul': this._resolve('upload', e.upload), '#m-ping': this._resolve('ping', e.ping), '#m-jitter': this._resolve('jitter', e.jitter),
      '#m-dlc': this._resolve('dl_compliance', e.dl_compliance), '#m-ulc': this._resolve('ul_compliance', e.ul_compliance),
      '#m-datadl': this._resolve('data_downloaded', e.data_downloaded), '#m-dataul': this._resolve('data_uploaded', e.data_uploaded),
      '#m-lifedl': this._resolve('lifetime_download', e.lifetime_download), '#m-lifeul': this._resolve('lifetime_upload', e.lifetime_upload),
      '#run': null
    };

    Object.entries(clickMap).forEach(([id, ent]) => {
      const el = this.shadowRoot.querySelector(id);
      if (!el) return;
      if (id === '#run') el.onclick = () => {
        if (this._pendingClick) return;

        const runEntityId = this._resolve('run_test', e.run_test);
        if (!runEntityId) return;

        // Optimistic feedback until the real speed_test_running sensor
        // confirms; the safety-net timeout only clears this flag, it never
        // forces the button back while the sensor still reports running.
        this._pendingClick = true;
        this.updateCard();

        this._hass.callService('button', 'press', { entity_id: runEntityId }).finally(() => {
          setTimeout(() => {
            this._pendingClick = false;
            this.updateCard();
          }, 5000);
        });
      };
      else el.onclick = () => this._showMoreInfo(ent);
    });
  }
}

customElements.define("pace-dashboard", PaceDashboard);

class PaceDashboardEditor extends HTMLElement {
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
    this.dispatchEvent(new CustomEvent("config-changed", { detail: { config: newConfig }, bubbles: true, composed: true }));
  }

  render() {
    if (this._elements) return;

    this.innerHTML = '';
    this._elements = [];

    const container = document.createElement('div');
    container.style.cssText = "display: flex; flex-direction: column; gap: 12px; padding: 10px; font-family: sans-serif;";

    // General Section
    const genDiv = document.createElement('div');
    genDiv.style.cssText = "border: 1px solid var(--divider-color, #444); border-radius: 8px; padding: 10px; background: var(--card-background-color, #222);";
    genDiv.innerHTML = `<div style="font-weight: bold; margin-bottom: 10px; color: var(--primary-color, #0ea5e9); font-size: 13px; text-transform: uppercase;">General Settings</div>`;

    const styleToggle = document.createElement('div');
    styleToggle.style.cssText = "display: flex; align-items: center; justify-content: space-between; margin-bottom: 10px;";
    styleToggle.innerHTML = `<label style="font-size: 12px; color: var(--secondary-text-color, #ccc);">Terminal Style</label>`;
    const terminalStyleCheckbox = document.createElement('input');
    terminalStyleCheckbox.type = "checkbox";
    terminalStyleCheckbox.checked = this._config.terminal_style !== false;
    terminalStyleCheckbox.style.cssText = "width: 20px; height: 20px; cursor: pointer;";
    terminalStyleCheckbox.addEventListener('change', (e) => this.configChanged({ ...this._config, terminal_style: e.target.checked }));
    styleToggle.appendChild(terminalStyleCheckbox);
    genDiv.appendChild(styleToggle);

    const gaugesToggle = document.createElement('div');
    gaugesToggle.style.cssText = "display: flex; align-items: center; justify-content: space-between; margin-bottom: 10px;";
    gaugesToggle.innerHTML = `<label style="font-size: 12px; color: var(--secondary-text-color, #ccc);">Show Gauges</label>`;
    const gaugesCheckbox = document.createElement('input');
    gaugesCheckbox.type = "checkbox";
    gaugesCheckbox.checked = this._config.show_gauges !== false;
    gaugesCheckbox.style.cssText = "width: 20px; height: 20px; cursor: pointer;";
    gaugesCheckbox.addEventListener('change', (e) => this.configChanged({ ...this._config, show_gauges: e.target.checked }));
    gaugesToggle.appendChild(gaugesCheckbox);
    genDiv.appendChild(gaugesToggle);

    const chartsToggle = document.createElement('div');
    chartsToggle.style.cssText = "display: flex; align-items: center; justify-content: space-between; margin-bottom: 10px;";
    chartsToggle.innerHTML = `<label style="font-size: 12px; color: var(--secondary-text-color, #ccc);">Show Charts</label>`;
    const chartsCheckbox = document.createElement('input');
    chartsCheckbox.type = "checkbox";
    chartsCheckbox.checked = this._config.show_charts !== false;
    chartsCheckbox.style.cssText = "width: 20px; height: 20px; cursor: pointer;";
    chartsCheckbox.addEventListener('change', (e) => this.configChanged({ ...this._config, show_charts: e.target.checked }));
    chartsToggle.appendChild(chartsCheckbox);
    genDiv.appendChild(chartsToggle);

    const maxDlOption = document.createElement('div');
    maxDlOption.style.cssText = "display: flex; align-items: center; justify-content: space-between; margin-bottom: 10px;";
    maxDlOption.innerHTML = `<label style="font-size: 12px; color: var(--secondary-text-color, #ccc);">Max Download (Mbps)</label>`;
    const maxDlInput = document.createElement('input');
    maxDlInput.type = "number";
    maxDlInput.value = this._config.max_download ?? '';
    maxDlInput.placeholder = "Auto (ISP rated speed, else 1000)";
    maxDlInput.style.cssText = "padding: 6px; border-radius: 4px; border: 1px solid var(--divider-color, #444); background: var(--card-background-color, #111); color: var(--primary-text-color, #fff); width: 80px;";
    maxDlInput.addEventListener('change', (e) => this.configChanged({ ...this._config, max_download: e.target.value === '' ? null : Number(e.target.value) }));
    maxDlOption.appendChild(maxDlInput);
    genDiv.appendChild(maxDlOption);

    const maxUlOption = document.createElement('div');
    maxUlOption.style.cssText = "display: flex; align-items: center; justify-content: space-between; margin-bottom: 10px;";
    maxUlOption.innerHTML = `<label style="font-size: 12px; color: var(--secondary-text-color, #ccc);">Max Upload (Mbps)</label>`;
    const maxUlInput = document.createElement('input');
    maxUlInput.type = "number";
    maxUlInput.value = this._config.max_upload ?? '';
    maxUlInput.placeholder = "Auto (ISP rated speed, else 500)";
    maxUlInput.style.cssText = "padding: 6px; border-radius: 4px; border: 1px solid var(--divider-color, #444); background: var(--card-background-color, #111); color: var(--primary-text-color, #fff); width: 80px;";
    maxUlInput.addEventListener('change', (e) => this.configChanged({ ...this._config, max_upload: e.target.value === '' ? null : Number(e.target.value) }));
    maxUlOption.appendChild(maxUlInput);
    genDiv.appendChild(maxUlOption);

    const historyOption = document.createElement('div');
    historyOption.style.cssText = "display: flex; align-items: center; justify-content: space-between;";
    historyOption.innerHTML = `<label style="font-size: 12px; color: var(--secondary-text-color, #ccc);">History (hours)</label>`;
    const historyInput = document.createElement('input');
    historyInput.type = "number";
    historyInput.value = this._config.history_hours || 168;
    historyInput.min = "24";
    historyInput.max = "720";
    historyInput.step = "24";
    historyInput.style.cssText = "padding: 6px; border-radius: 4px; border: 1px solid var(--divider-color, #444); background: var(--card-background-color, #111); color: var(--primary-text-color, #fff); width: 60px;";
    historyInput.addEventListener('change', (e) => this.configChanged({ ...this._config, history_hours: Number(e.target.value) }));
    historyOption.appendChild(historyInput);
    genDiv.appendChild(historyOption);
    container.appendChild(genDiv);

    // Labels Section
    const labelsDiv = document.createElement('div');
    labelsDiv.style.cssText = "border: 1px solid var(--divider-color, #444); border-radius: 8px; padding: 10px; background: var(--card-background-color, #222); margin-top: 10px;";
    labelsDiv.innerHTML = `<div style="font-weight: bold; margin-bottom: 10px; color: var(--primary-color, #0ea5e9); font-size: 13px; text-transform: uppercase;">Labels</div>`;

    const createLabelInput = (key, label, defaultValue) => {
      const div = document.createElement('div');
      div.style.cssText = "display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px;";

      const lbl = document.createElement('label');
      lbl.innerText = label;
      lbl.style.cssText = "font-size: 12px; color: var(--secondary-text-color, #ccc);";
      div.appendChild(lbl);

      const input = document.createElement('input');
      input.type = "text";
      input.value = (this._config.labels && this._config.labels[key]) || defaultValue;
      input.style.cssText = "padding: 6px; border-radius: 4px; border: 1px solid var(--divider-color, #444); background: var(--card-background-color, #111); color: var(--primary-text-color, #fff); width: 100px;";
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
    labelsDiv.appendChild(createLabelInput('jitter', 'Jitter', 'Jitter'));
    container.appendChild(labelsDiv);

    // Helpers
    const createSection = (title, items) => {
      const secDiv = document.createElement('div');
      secDiv.style.cssText = "border: 1px solid var(--divider-color, #444); border-radius: 8px; padding: 10px; background: var(--card-background-color, #222); margin-top: 10px;";
      secDiv.innerHTML = `<div style="font-weight: bold; margin-bottom: 10px; color: var(--primary-color, #0ea5e9); font-size: 13px; text-transform: uppercase;">${title}</div>`;

      items.forEach(item => {
        const option = document.createElement('div');
        option.style.marginBottom = "12px";
        const label = document.createElement('label');
        label.innerText = item.label;
        label.style.cssText = "font-size: 12px; color: var(--secondary-text-color, #ccc); margin-bottom: 4px; display: block;";
        option.appendChild(label);

        const picker = document.createElement('ha-entity-picker');
        if (this._hass) picker.hass = this._hass;
        picker.value = (this._config.entities && this._config.entities[item.key]) || '';
        picker.includeDomains = item.domains || ['sensor'];
        picker.allowCustomEntity = true;
        picker.addEventListener('value-changed', (e) => {
          const entities = { ...(this._config.entities || {}) };
          entities[item.key] = e.detail.value;
          this.configChanged({ ...this._config, entities });
        });

        this._elements.push(picker);
        option.appendChild(picker);
        secDiv.appendChild(option);
      });
      return secDiv;
    };

    container.appendChild(createSection("Core Entities", [
      { key: 'download', label: 'Download' },
      { key: 'upload', label: 'Upload' },
      { key: 'ping', label: 'Ping' },
      { key: 'jitter', label: 'Jitter' },
      { key: 'server', label: 'Server' },
      { key: 'backend', label: 'Backend' },
      { key: 'last_test', label: 'Last Test' },
      { key: 'run_test', label: 'Run Test Button', domains: ['button'] },
      { key: 'running', label: 'Speed Test Running', domains: ['binary_sensor'] },
      { key: 'internet_connected', label: 'Internet Connected', domains: ['binary_sensor'] },
      { key: 'public_ip', label: 'Public IP Address' }
    ]));

    container.appendChild(createSection("Plan Compliance", [
      { key: 'dl_compliance', label: 'Download Plan %' },
      { key: 'ul_compliance', label: 'Upload Plan %' }
    ]));

    container.appendChild(createSection("Data Usage", [
      { key: 'data_downloaded', label: 'Test Data Downloaded' },
      { key: 'data_uploaded', label: 'Test Data Uploaded' },
      { key: 'lifetime_download', label: 'Lifetime Data Downloaded' },
      { key: 'lifetime_upload', label: 'Lifetime Data Uploaded' }
    ]));

    this.appendChild(container);
  }
}
customElements.define("pace-dashboard-editor", PaceDashboardEditor);

window.customCards = window.customCards || [];
window.customCards.push({
  type: "pace-dashboard",
  name: "Pace - Dashboard",
  description: "Fully configurable dashboard with gauges, charts, and plan compliance",
  preview: true
});

console.info("%c PACE DASHBOARD %c v1.0.0 ", "background: #00d2ff; color: #fff; font-weight: bold;", "background: #1e293b; color: #fff;");
