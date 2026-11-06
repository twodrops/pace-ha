# Troubleshooting Guide

## Common Issues

### Speed test button is disabled
**Symptom**: The "Manual Speed Test" button appears grayed out or unavailable.

**Cause**: A speed test is currently running. The integration prevents concurrent tests to ensure accurate results.

**Solution**: 
- Wait for the current test to complete (check `binary_sensor.pace_speed_test_running`)
- Check logs for any errors if the test seems stuck
- Restart the integration if the test has been running for more than 5 minutes

### Low speed results
**Symptom**: Speed test results are significantly lower than expected (e.g., 50-100 Mbps when expecting 500+ Mbps).

**Solutions**:
1. **Switch backends** (Ookla CLI is often more accurate on very fast connections):
   - Navigate to Settings → Devices & Services → PACE → Configure
   - Change **Backend** to "Ookla CLI" (or "speedtest-go")
   - Save and wait for automatic restart
   
2. **Select a different server**:
   - Some servers may be overloaded or geographically distant
   - Try "Automatic" selection or manually choose a closer server

3. **Check network conditions**:
   - Ensure no other devices are consuming bandwidth
   - Test at different times of day

### Custom server not working
**Symptom**: Tests fail when using a custom server (LibreSpeed or speedtest-go backend only - Ookla has no custom-server support).

**Diagnostic steps**:
1. **Verify server URL**:
   - Ensure URL is complete (e.g., `https://speedtest.example.com`)
   - Test the URL in a browser - you should see the LibreSpeed server interface
   
2. **SSL Certificate issues** (LibreSpeed backend only):
   - If using self-signed certificates, enable "Skip Certificate Verification"
   - Check logs for SSL-related errors
   
3. **Server compatibility**:
   - Ensure server is running LibreSpeed (PHP or Rust backend)
   - Check server logs for any access errors

### Tests not running automatically
**Symptom**: Scheduled speed tests are not executing at the configured interval.

**Solutions**:
1. **Verify configuration**:
   - Check that "Automatic Updates" is enabled
   - Confirm update interval is set (minimum 30 minutes)
   
2. **Check Home Assistant logs**:
   ```
   grep pace home-assistant.log
   ```
   

### Plan Compliance sensors don't appear
**Symptom**: `sensor.pace_download_plan_compliance` / `sensor.pace_upload_plan_compliance` are missing or stuck on `unknown`.

**Cause**: These sensors are disabled until you set **ISP Rated Download/Upload Speed** in the integration options (default is `0`, which disables them).

**Solution**: Go to Settings → Devices & Services → PACE → Configure, and set your ISP's advertised Mbit/s values.

3. **Review automation conflicts**:
   - Ensure no other automations are interfering
   - Check if Home Assistant is in maintenance mode

## Error Messages and Solutions

### "Speed test timed out after multiple attempts"
**Cause**: Network connectivity issues or server unavailability.

**Solutions**:
- Check internet connectivity
- Try a different server
- Increase timeout in configuration
- The integration automatically retries 3 times with exponential backoff

### "Network error: Connection refused"
**Cause**: Firewall blocking connections or server is down.

**Solutions**:
- Check firewall rules for outbound HTTPS (port 443)
- Verify the server is operational
- Try the automatic server selection

### "SSL: CERTIFICATE_VERIFY_FAILED"
**Cause**: Custom server using self-signed or expired certificate.

**Solutions**:
- Enable "Skip Certificate Verification" in configuration
- Update server certificate
- Use a Let's Encrypt certificate on your server

### "Speed test already in progress"
**Cause**: Previous test didn't complete properly.

**Solutions**:
- Wait 2-3 minutes for timeout
- Restart the integration if stuck
- Check logs for underlying errors

## Advanced Debugging

### Enable debug logging
Add to `configuration.yaml`:
```yaml
logger:
  default: info
  logs:
    custom_components.pace: debug
```

### Check integration state
In Developer Tools → States, search for `pace` entities:
- `binary_sensor.pace_speed_test_running` - Should be `off` when idle
- `sensor.pace_last_test_time` - Shows last successful test

### Manual CLI testing
Each backend's binary lives under its own subfolder of `custom_components/pace/bin/`. Test it directly:
```bash
# From Home Assistant container/environment
./custom_components/pace/bin/librespeed/librespeed-cli --json
./custom_components/pace/bin/ookla/speedtest --accept-license --accept-gdpr --format=json
./custom_components/pace/bin/speedtest_go/speedtest-go --json
```

## Performance Optimization

### For connections > 500 Mbps
- Use the Ookla CLI or speedtest-go backend for best performance
- Ensure Home Assistant has sufficient CPU resources
- Consider running tests during off-peak hours

### Reducing resource usage
- Increase update interval (e.g., every 6-12 hours)
- Disable automatic updates and use automations for specific times
- Use server selection instead of automatic to avoid latency tests

## Getting Help

If you're still experiencing issues:
1. Enable debug logging (see above)
2. Collect relevant log entries
3. Check for existing issues on [GitHub](https://github.com/twodrops/pace-ha/issues)
4. Create a new issue with:
   - Your configuration (without sensitive data)
   - Debug logs
   - Expected vs actual behavior
   - Home Assistant version
   - Integration version