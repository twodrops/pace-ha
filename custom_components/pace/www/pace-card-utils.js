// A monospace-driven, flat accent palette with distinct hues per metric that
// has been tuned separately for light and dark so metrics stay readable
// (and accessible) no matter which Home Assistant theme mode is active.
export const TERMINAL_FONT_MONO = "'JetBrains Mono', 'IBM Plex Mono', ui-monospace, 'SFMono-Regular', Menlo, Consolas, monospace";

const TERMINAL_PALETTE = {
  light: {
    accent: '#2b6fd9',
    'accent-hover': '#2055b8',
    upload: '#6250d6',
    ping: '#c97b1a',
    jitter: '#d04e85',
    success: '#2f9d6b',
    warning: '#c97b1a',
    danger: '#d24343',
    'border-hot': '#c0c8d4',
    panel: '#eef1f6'
  },
  dark: {
    accent: '#5aa6ff',
    'accent-hover': '#76b6ff',
    upload: '#9085e9',
    ping: '#ffb86c',
    jitter: '#ff8fb4',
    success: '#4ad19a',
    warning: '#ffb86c',
    danger: '#ff6b6b',
    'border-hot': '#3a4554',
    panel: '#10141b'
  }
};

/**
 * Semantic colors that fall back to Home Assistant's own theme variables
 * when a card's `terminal_style` option is set to false. 
 * Series-identity colors (upload/
 * ping/jitter) stay as our own fixed hues even in HA style mode
 */
const HA_STYLE_COLOR_MAP = {
  accent: 'var(--primary-color)',
  'accent-hover': 'var(--primary-color)',
  success: 'var(--success-color, #43a047)',
  warning: 'var(--warning-color, #ffa600)',
  danger: 'var(--error-color, #db4437)',
  panel: 'var(--ha-card-background, var(--card-background-color))'
};

/**
 * Sets --ls-* custom properties on the card root so CSS can pick
 * theme-appropriate metric colors via var(--ls-xxx, fallback) instead of
 * colors hardcoded for only one of light/dark mode. When
 * `config.terminal_style` is false, semantic colors (accent/success/
 * warning/danger/panel) resolve to Home Assistant's own theme variables
 * instead of the terminal palette.
 */
export function applyTerminalPalette(root, hass, config) {
  const card = root?.querySelector('.card');
  if (!card) return;
  const palette = hass?.themes?.darkMode ? TERMINAL_PALETTE.dark : TERMINAL_PALETTE.light;
  const useHaStyle = config?.terminal_style === false;
  Object.entries(palette).forEach(([key, value]) => {
    card.style.setProperty(`--ls-${key}`, (useHaStyle && HA_STYLE_COLOR_MAP[key]) || value);
  });
}

/** Looks up a single terminal palette color (e.g. for JS-driven gauge threshold colors). */
export function getTerminalColor(hass, key, fallback, config) {
  if (config?.terminal_style === false && HA_STYLE_COLOR_MAP[key]) return HA_STYLE_COLOR_MAP[key];
  const palette = hass?.themes?.darkMode ? TERMINAL_PALETTE.dark : TERMINAL_PALETTE.light;
  return palette[key] || fallback;
}

/**
 * Toggles the `ha` host attribute that activates each card's :host([ha])
 * CSS block. `terminal_style` defaults to true; set it to false to opt into 
 * looking like a native HA
 * card instead - there is no per-field appearance fine-tuning, just this
 * one binary choice.
 */
export function applyHaStyleAttribute(hostElement, config) {
  hostElement.toggleAttribute('ha', config?.terminal_style === false);
}

/**
 * True if any of the given entity_ids' state object changed between two
 * hass snapshots. Home Assistant gives an entity's state a new object
 * reference only when that entity actually updates, so this is a cheap,
 * accurate "did an update actually concern this card" check - Home
 * Assistant creates a new top-level hass object (and calls `set hass()`)
 * on literally ANY entity's state change system-wide, not just the ones a
 * given card displays, so without this a busy install can redraw a card's
 * DOM (chart SVGs, bar widths, etc.) many times a second for no reason.
  */
export function anyStateChanged(prevHass, nextHass, entityIds) {
  if (!prevHass) return true;
  return entityIds.some(id => id && prevHass.states[id] !== nextHass.states[id]);
}

/**
 * Safari/WebKit has no CSS scroll-anchoring support (unlike Chromium), so
 * when a card's live-updating content changes the page's height while it's
 * scrolled to the very bottom, the browser clamps scroll position down and
 * never restores it - visible on iOS as the page "jumping up"/looking like
 * it auto-refreshed, with no equivalent on Chrome (desktop or Android)
 * since scroll anchoring silently compensates for it there.
 *
 * Call at the start of an update, before any DOM mutation; call the
 * returned function again afterwards to re-pin to the bottom if the page's
 * height actually changed while the user was anchored there.
 */
export function beginScrollAnchor() {
  const scroller = document.scrollingElement;
  if (!scroller) return () => {};
  // Require actual overflow, otherwise a page that merely fits the
  // viewport (e.g. mid-initial-render, before cards below have expanded)
  // reads as "at bottom" too, and later growth then yanks the page down
  // from the top on load instead of leaving it alone.
  const hasOverflow = scroller.scrollHeight > scroller.clientHeight + 2;
  const wasAtBottom = hasOverflow && scroller.scrollTop + scroller.clientHeight >= scroller.scrollHeight - 2;
  const prevScrollHeight = scroller.scrollHeight;
  return () => {
    if (!wasAtBottom) return;
    requestAnimationFrame(() => {
      if (scroller.scrollHeight !== prevScrollHeight) {
        scroller.scrollTop = scroller.scrollHeight - scroller.clientHeight;
      }
    });
  };
}

/**
 * Builds the inner HTML for a "heartbeat strip": one bar per recent
 * connectivity-check result (oldest first, newest last/rightmost), colored
 * ok/fail/unknown. `checks` is the internet_connected binary_sensor's
 * `recent_checks` attribute (an array of booleans); `size` is the number of
 * bars to render, left-padded with "unknown" bars if fewer samples exist
 * yet (e.g. right after Home Assistant restarts).
 *
 * Deliberately a row of discrete pass/fail bars, not a numeric "packet
 * loss %" - the underlying check only samples once per interval, so a
 * percentage would read as far more precise than it actually is.
 */
export function renderHeartbeatBars(checks, size) {
  const bars = (checks || []).slice(-size);
  while (bars.length < size) bars.unshift(null);
  return bars.map((ok) => {
    const cls = ok === true ? 'hb-ok' : ok === false ? 'hb-fail' : 'hb-unknown';
    const title = ok === true ? 'OK' : ok === false ? 'Failed' : 'No data yet';
    return `<span class="hb-bar ${cls}" title="${title}"></span>`;
  }).join('');
}

/**
 * Resolve a Pace entity_id, falling back to a suffix-based search
 * across hass.states when the configured/stub id doesn't exist.
 *
 * Pace supports multiple instances, so the real entity_id is
 * "<domain>.pace_<instance_slug>_<suffix>" where <instance_slug>
 * varies per install (e.g. "automatic", "custom", a server name...). Card
 * stub configs can only guess the no-instance form
 * "<domain>.pace_<suffix>", so when that exact guess doesn't exist
 * we search for any entity ending in the same domain + suffix instead.
 *
 * fallbackDomain lets callers still search when configuredId itself is
 * missing entirely (e.g. an older saved card config predates a field).
 */
export function resolvePaceEntity(hass, configuredId, suffix, fallbackDomain) {
  if (!hass) return configuredId;
  if (configuredId && hass.states[configuredId]) return configuredId;

  const rawDomain = configuredId ? configuredId.split('.')[0] : fallbackDomain;
  if (!rawDomain) return configuredId;

  const domain = rawDomain.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  // The optional leading (?:[a-z0-9]+_)? segment tolerates an area name HA
  // may prepend to the object_id (e.g. "buro_pace_automatic_download_speed"
  // when the device/entity is assigned to an area called "Büro").
  const pattern = new RegExp(`^${domain}\\.(?:[a-z0-9]+_)?pace(?:_[a-z0-9]+)*_${suffix}$`);
  const found = Object.keys(hass.states).find((id) => pattern.test(id));
  return found || configuredId;
}
