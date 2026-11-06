# Advanced Usage Guide

## Automation Blueprints

### Daily Speed Test Report

Save this as `blueprints/automation/pace_daily_report.yaml`:

```yaml
blueprint:
  name: PACE Daily Report
  description: Send daily speed test report via notification
  domain: automation
  input:
    test_time:
      name: Test Time
      description: When to run the daily test
      selector:
        time:
      default: "03:00:00"
    notify_device:
      name: Notification Device
      description: Device to send the report to
      selector:
        device:
          integration: mobile_app
    speed_threshold:
      name: Minimum Download Speed
      description: Alert if speed is below this value (Mbps)
      selector:
        number:
          min: 1
          max: 1000
          unit_of_measurement: Mbps
      default: 50

trigger:
  - platform: time
    at: !input test_time

action:
  - service: button.press
    target:
      entity_id: button.pace_run_speed_test
  
  - wait_for_trigger:
      - platform: state
        entity_id: binary_sensor.pace_speed_test_running
        from: "on"
        to: "off"
    timeout: "00:05:00"
  
  - variables:
      download: "{{ states('sensor.pace_download_speed') | float }}"
      upload: "{{ states('sensor.pace_upload_speed') | float }}"
      ping: "{{ states('sensor.pace_ping') | float }}"
      threshold: !input speed_threshold
  
  - service: notify.mobile_app_{{ device_id(!input notify_device) }}
    data:
      title: "Daily Speed Test Report"
      message: >
        📊 Speed Test Results:
        Download: {{ download }} Mbps {{ '⚠️' if download < threshold else '✅' }}
        Upload: {{ upload }} Mbps
        Ping: {{ ping }} ms
        Server: {{ states('sensor.pace_server_name') }}
      data:
        tag: "speed_test_report"
        group: "speed_test"
```

### Low Speed Alert

Save this as `blueprints/automation/pace_low_speed_alert.yaml`:

```yaml
blueprint:
  name: PACE Low Speed Alert
  description: Alert when internet speed drops below threshold
  domain: automation
  input:
    download_threshold:
      name: Download Speed Threshold
      description: Alert when download speed is below (Mbps)
      selector:
        number:
          min: 1
          max: 1000
          unit_of_measurement: Mbps
      default: 50
    upload_threshold:
      name: Upload Speed Threshold
      description: Alert when upload speed is below (Mbps)
      selector:
        number:
          min: 1
          max: 500
          unit_of_measurement: Mbps
      default: 10
    notify_device:
      name: Notification Device
      selector:
        device:
          integration: mobile_app

trigger:
  - platform: numeric_state
    entity_id: sensor.pace_download_speed
    below: !input download_threshold
  - platform: numeric_state
    entity_id: sensor.pace_upload_speed
    below: !input upload_threshold

action:
  - service: notify.mobile_app_{{ device_id(!input notify_device) }}
    data:
      title: "⚠️ Slow Internet Speed Detected"
      message: >
        {% if trigger.entity_id == 'sensor.pace_download_speed' %}
        Download speed is {{ states('sensor.pace_download_speed') }} Mbps
        (below {{ download_threshold }} Mbps threshold)
        {% else %}
        Upload speed is {{ states('sensor.pace_upload_speed') }} Mbps
        (below {{ upload_threshold }} Mbps threshold)
        {% endif %}
      data:
        tag: "speed_alert"
        importance: high
        channel: alerts
```

## Custom Dashboards

### Network Quality Monitoring Dashboard

Create a comprehensive dashboard for monitoring network quality:

```yaml
type: vertical-stack
cards:
  - type: custom:mini-graph-card
    name: Internet Speed History
    entities:
      - entity: sensor.pace_download_speed
        name: Download
        color: blue
      - entity: sensor.pace_upload_speed
        name: Upload
        color: green
    hours_to_show: 24
    points_per_hour: 4
    line_width: 3
    font_size: 75
    
  - type: horizontal-stack
    cards:
      - type: gauge
        entity: sensor.pace_download_speed
        name: Download
        max: 1000
        severity:
          green: 100
          yellow: 50
          red: 0
          
      - type: gauge
        entity: sensor.pace_upload_speed
        name: Upload
        max: 500
        severity:
          green: 50
          yellow: 25
          red: 0
          
      - type: gauge
        entity: sensor.pace_ping
        name: Latency
        max: 100
        severity:
          green: 0
          yellow: 50
          red: 100
          
  - type: entities
    title: Test Details
    entities:
      - entity: sensor.pace_jitter
        name: Jitter
      - entity: sensor.pace_server_name
        name: Server
      - entity: sensor.pace_last_test_time
        name: Last Test
      - entity: binary_sensor.pace_speed_test_running
        name: Test Status
      - entity: button.pace_run_speed_test
        name: Run Test Now
```

## ISP Performance Tracking

The integration has built-in **Download Plan Compliance** and **Upload Plan Compliance** sensors (`sensor.pace_download_plan_compliance` / `sensor.pace_upload_plan_compliance`). Set your ISP's rated speeds in the integration's options (see [Configuration Guide](CONFIGURATION.md#plan-compliance-sensors)) and these sensors automatically report `(measured / rated) * 100` after every test - no templates required.

If you need a rolling average or custom thresholds beyond the raw compliance percentage, you can still layer a `statistics` sensor on top of the built-in one:

```yaml
sensor:
  - platform: statistics
    name: "Average Download Compliance"
    entity_id: sensor.pace_download_plan_compliance
    state_characteristic: mean
    max_age:
      days: 7
```

## Integration with Other Services

### Discord Notification

```yaml
automation:
  - alias: "Speed Test Discord Report"
    trigger:
      - platform: state
        entity_id: binary_sensor.pace_speed_test_running
        from: "on"
        to: "off"
    action:
      - service: notify.discord
        data:
          message: |
            **Speed Test Results**
            :arrow_down: Download: {{ states('sensor.pace_download_speed') }} Mbps
            :arrow_up: Upload: {{ states('sensor.pace_upload_speed') }} Mbps
            :stopwatch: Ping: {{ states('sensor.pace_ping') }} ms
            :satellite: Server: {{ states('sensor.pace_server_name') }}
```

### Telegram Bot Integration

```yaml
automation:
  - alias: "Speed Test Telegram Report"
    trigger:
      - platform: state
        entity_id: binary_sensor.pace_speed_test_running
        from: "on"
        to: "off"
    action:
      - service: telegram_bot.send_message
        data:
          message: |
            *Speed Test Complete*
            ⬇️ Download: {{ states('sensor.pace_download_speed') }} Mbps
            ⬆️ Upload: {{ states('sensor.pace_upload_speed') }} Mbps
            ⏱ Ping: {{ states('sensor.pace_ping') }} ms
          parse_mode: markdown
```

## Advanced Automations

### Adaptive Testing Frequency

Run tests more frequently when performance is poor:

```yaml
automation:
  - alias: "Adaptive Speed Test Frequency"
    trigger:
      - platform: numeric_state
        entity_id: sensor.pace_download_speed
        below: 50
        for: "00:10:00"
    action:
      - service: button.press
        target:
          entity_id: button.pace_run_speed_test
      - delay: "00:30:00"
      - service: button.press
        target:
          entity_id: button.pace_run_speed_test
```

### Network Issue Detection

Detect and respond to network issues:

```yaml
automation:
  - alias: "Network Issue Detection"
    trigger:
      - platform: numeric_state
        entity_id: sensor.pace_ping
        above: 100
        for: "00:05:00"
    action:
      - service: notify.persistent_notification
        data:
          title: "Network Latency Warning"
          message: >
            High network latency detected: {{ states('sensor.pace_ping') }} ms
            This may affect streaming and gaming performance.
      - service: script.restart_network_equipment
```

## Data Export and Analysis

### Export to InfluxDB

```yaml
influxdb:
  host: localhost
  port: 8086
  database: home_assistant
  include:
    entities:
      - sensor.pace_download_speed
      - sensor.pace_upload_speed
      - sensor.pace_ping
      - sensor.pace_jitter
```

### Long-term Statistics

```yaml
recorder:
  purge_keep_days: 365
  include:
    entities:
      - sensor.pace_download_speed
      - sensor.pace_upload_speed
      - sensor.pace_ping
```
