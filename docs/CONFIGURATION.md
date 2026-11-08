# Configuration Guide

## Configuration Parameters

### Installation Parameters

During initial setup, you'll configure these parameters:

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| **Backend** | Select | Yes | LibreSpeed CLI | Which CLI speed test tool to use:<br>• **LibreSpeed CLI**: self-hostable, supports custom servers<br>• **Ookla CLI**: official Ookla binary, requires accepting Ookla's license/GDPR terms, no custom-server support<br>• **speedtest-go**: open-source, hits the same server network as Ookla, supports custom servers |
| **Server Selection** | Select | Yes | Automatic | How to select the test server:<br>• **Automatic**: Auto-detect best server based on latency<br>• **Select Server**: Choose from list of available servers<br>• **Custom Server**: Use your own server (LibreSpeed/speedtest-go backends only) |
| **Server ID** | Dropdown | If "Select Server" | None | Choose from list of available LibreSpeed servers worldwide |
| **Custom Server URL** | URL | If "Custom Server" | None | Full URL to your self-hosted server (e.g., `https://speedtest.example.com`) |
| **Enable Automatic Updates** | Boolean | Yes | True | Run tests automatically on schedule |
| **Update Interval** | Number | If auto enabled | 60 | Minutes between automatic tests (30-1440) |
| **Test Timeout** | Number | No | 240 | Maximum time allowed for a single speed test (60-600 seconds) |
| **Internet Check Interval** | Number | No | 30 | How often to check internet reachability and public IP, independent of speed tests (10-300 seconds) |
| **Skip Certificate Verification** | Boolean | No | False | Skip SSL verification for self-signed certificates (LibreSpeed backend's custom-server mode only) ⚠️ |
| **ISP Rated Download Speed** | Number | No | 0 (disabled) | Your ISP's advertised download speed in Mbit/s. When set above 0, enables the Download Plan Compliance sensor |
| **ISP Rated Upload Speed** | Number | No | 0 (disabled) | Your ISP's advertised upload speed in Mbit/s. When set above 0, enables the Upload Plan Compliance sensor |

### Modifiable Options

After initial setup, you can modify these parameters through the integration options:

| Parameter | Type | Modifiable | Range/Options | Description |
|-----------|------|------------|---------------|-------------|
| **Backend** | Select | Yes | LibreSpeed CLI / Ookla CLI / speedtest-go | Switch backends without reinstalling - entities stay the same regardless of backend |
| **Server Selection Mode** | Select | Yes | Automatic / Select / Custom | Change server selection method |
| **Server ID** | Dropdown | Yes | Server list | Pick different server from list |
| **Custom Server URL** | URL | Yes | Valid URL | Update custom server address (LibreSpeed/speedtest-go only) |
| **Enable Automatic Updates** | Toggle | Yes | On/Off | Enable or disable scheduled tests |
| **Update Interval** | Slider | Yes | 30-1440 minutes | Adjust test frequency:<br>• 30-60 min: Frequent monitoring<br>• 60 min: Hourly (default)<br>• 180-360 min: Regular checks<br>• 720-1440 min: Daily monitoring |
| **Test Timeout** | Number | Yes | 60-600 seconds | Maximum time allowed for a single speed test |
| **Internet Check Interval** | Slider | Yes | 10-300 seconds | Adjust how often the lightweight connectivity/public-IP check runs, independent of speed tests |
| **Skip Certificate Verification** | Toggle | Yes | On/Off | Toggle SSL verification (LibreSpeed custom-server mode only) |
| **ISP Rated Download Speed** | Number | Yes | 0-100000 Mbit/s | Adjust or disable (0) the Download Plan Compliance sensor |
| **ISP Rated Upload Speed** | Number | Yes | 0-100000 Mbit/s | Adjust or disable (0) the Upload Plan Compliance sensor |

## Modifying Configuration

1. Go to **Settings** → **Devices & Services**
2. Find the PACE integration
3. Click **Configure**
4. Modify desired parameters
5. Click **Submit** to save changes

**Note**: Changes take effect on the next speed test. Running tests are not interrupted.

## Plan Compliance Sensors

Set **ISP Rated Download Speed** and/or **ISP Rated Upload Speed** (in Mbit/s) during setup or in options to enable the `download_compliance` / `upload_compliance` sensors. Each reports `(measured speed / rated speed) * 100`, so you can see at a glance whether your connection is meeting the speed your ISP advertises. Leaving either value at `0` (the default) disables the corresponding sensor.

These sensors work identically regardless of which backend you use, since the calculation only depends on the already-measured download/upload speed.

## Internet Connectivity & Heartbeat

Independent of speed tests, PACE periodically checks basic internet reachability and your public IP (see **Internet Check Interval** above). This powers `binary_sensor.pace_internet_connected` and `sensor.pace_public_ip_address`, plus a rolling pass/fail history exposed as the `recent_checks` attribute on the connectivity sensor.

The Dashboard and Minimal Lovelace cards visualize that history as a small "LINK" bar strip - green bars for successful checks, red for failures - giving an at-a-glance trend instead of a single online/offline flag. It's a lightweight health signal (not a precise packet-loss measurement), since it's based on one check per interval rather than a burst of pings.

## Dashboard Card Options

These are set in the card's visual editor (or directly in its YAML), not through the integration's Settings dialog:

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| **Title** | Text | `PACE` | Header text shown top-left; clicking it opens the integration's settings page |
| **Terminal Style** | Toggle | On | Off reverts the card to a native HA card's look (colors, font, rounded corners) |
| **Show Gauges** | Toggle | On | Show/hide the download/upload radial gauges |
| **Average Gauges** | Toggle | Off | Show the gauges' mean over History (hours) instead of the live current reading; the gauge label shows the averaging window, e.g. "Download (7D AVG)" |
| **Show Charts** | Toggle | On | Show/hide the Throughput/Latency history charts |
| **Show Plan & Usage** | Toggle | On | Show/hide the whole Plan Compliance + Data Usage section |
| **Max Download/Upload (Mbps)** | Number | Auto | Overrides the gauges' scale; auto uses the ISP rated speed (+20%) if set, else 1000/500 |
| **History (hours)** | Number | 168 (7 days) | How far back the charts' history query looks |

## Backend Selection Guide

PACE supports three interchangeable CLI backends. All expose the exact same entities (download, upload, ping, jitter, server name, lifetime data, plan compliance, etc.) - only the underlying test engine and binary differ.

### LibreSpeed CLI (default)

**Advantages:**
- LGPL-3.0 open source
- Supports self-hosted/custom servers
- No license acceptance required

**Limitations:**
- Requires binary download (~5MB)
- Only `amd64`/`arm64` Linux builds available

### Ookla CLI

**Advantages:**
- Official Ookla implementation, widest server network
- Broader architecture support (`x86_64`/`aarch64`/`armhf`/`armel`/`i386`)

**Limitations:**
- Proprietary binary - using it means accepting Ookla's license and GDPR terms (done automatically via `--accept-license --accept-gdpr` on every run, same as the binary's own first-run prompt)
- No self-hosted/custom server support

### speedtest-go

**Advantages:**
- MIT licensed, fully open source
- Hits the same server network as Ookla, without the proprietary binary or telemetry
- Supports self-hosted/custom servers via `--custom-url`

**Limitations:**
- Smaller community than LibreSpeed/Ookla
- Requires binary download (~5MB)

## Custom Server Configuration

Only the LibreSpeed and speedtest-go backends support pointing at your own self-hosted server - Ookla has no equivalent (it only talks to Ookla's global server network).

### Setting Up a Custom Server

1. **Deploy a LibreSpeed server**:
   - Use Docker: `docker run -d -p 80:80 adolfintel/speedtest`
   - Or follow [manual installation](https://github.com/librespeed/speedtest)

2. **Configure in Home Assistant**:
   - Select "Custom Server" during setup
   - Enter full URL (e.g., `https://speedtest.yourdomain.com`)
   - Enable "Skip Certificate Verification" if using self-signed SSL (LibreSpeed backend only)

### Server Requirements
- LibreSpeed PHP backend (standard)
- LibreSpeed Rust backend (high-performance)
- Sufficient bandwidth for your connection speed

### Troubleshooting Custom Servers
- Verify URL is accessible from Home Assistant
- Check firewall rules allow HTTPS (port 443) if required
- Test in browser first
- Review server logs for errors

## Scheduling Strategies

### Conservative (Low Data Usage)
- Update Interval: 720-1440 minutes (12-24 hours)
- Best for: Metered connections, stable networks
- Data usage: ~50-100 MB/day

### Balanced (Default)
- Update Interval: 60-180 minutes
- Best for: Most users, regular monitoring
- Data usage: ~200-500 MB/day

### Aggressive (Frequent Monitoring)
- Update Interval: 30-60 minutes
- Best for: Troubleshooting, SLA monitoring
- Data usage: ~500-1000 MB/day

### Custom Scheduling with Automations

Disable automatic updates and use automations for precise control:

```yaml
automation:
  - alias: "Speed Test Schedule"
    trigger:
      - platform: time
        at: 
          - "06:00:00"
          - "12:00:00"
          - "18:00:00"
          - "22:00:00"
    action:
      - service: button.press
        entity_id: button.pace_run_speed_test
```

## Performance Tuning

### For Slow Systems
- Increase timeout to 300-600 seconds
- Reduce update interval to 180-360 minutes
- Disable automatic updates during peak hours

### For Fast Connections
- Keep default timeout (240 seconds)
- Select nearby servers manually
- Monitor CPU usage during tests

### Network Optimization
- Run tests when network is idle
- Avoid concurrent bandwidth-heavy tasks
- Use wired connection for consistency
