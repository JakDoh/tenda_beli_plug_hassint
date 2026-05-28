# Tenda Beli Plug Home Assistant Integration

Simple local Home Assistant integration for Tenda Beli SP3 and SP9 plugs.

## What this integration adds

- A switch entity for each plug
- Sensors for power and energy
- Diagnostic sensors:
  - uptime
  - on-time
  - status
  - last seen
- Buttons for manual power/energy refresh
- Local "hub" control inside Home Assistant

---

## Before you start

- Home Assistant and the plug must be on the same local network
- The Home Assistant host should have a stable IPv4 address
- Ports `1821` and `1822` must be reachable on the Home Assistant host
- The plug may require temporary internet or local NTP access to set its clock correctly

---

## Step-by-step setup

### 1. Install the integration

1. Copy the repository `tendabeli` folder into your Home Assistant configuration directory:

```text
/custom_components/tendabeli
```

2. Restart Home Assistant.
3. Go to:

```text
Settings -> Devices & Services -> Add Integration
```

4. Search for:

```text
Tenda Smart Plug
```

5. Submit the setup form.

This starts the local Tenda hub inside Home Assistant.

---

### 2. Prepare the plug

Before first use, configure the plug:

1. Reset the plug by holding the on/off button until the orange LED lights up.
2. Wait for a Wi-Fi access point similar to the following to appear:

```text
Tenda_Smart_Plug_XXXX
```

3. Connect your computer to the temporary plug Wi-Fi network.
4. Prepare the following information:
   - Your Wi-Fi SSID
   - Your Wi-Fi password
   - IPv4 address or hostname of your Home Assistant instance

> Hostnames work only if correctly resolvable by the plug environment. IPv6 is not supported.

5. Run the following PowerShell command with your own values:

```powershell
curl http://192.168.25.1:5000/guideDone `
  -Method Post `
  -Body '{"account":"1","ssid":"your_ap_ssid","key":"your_ap_password","server":"ipaddress_or_hostname_of_your_hass","location":"Europe/Prague","time_zone":0}'
```

6. Reconnect your computer back to your normal network.
7. The plug should then connect to your Wi-Fi and Home Assistant automatically.

---

## Provisioning response behavior

If the Wi-Fi configuration is invalid or the plug cannot connect for any reason, the plug keeps its temporary AP active and replies with:

```powershell
StatusCode        : 200
StatusDescription : OK
Content           : {123, 34, 114, 101...}
RawContent        : HTTP/1.1 200 OK

                    {"resp_code":2}

Headers           : {}
RawContentLength  : 15
```

If the configuration is valid, the plug disables its temporary AP immediately and closes the connection without returning a response.

This behavior is expected.

---

## 3. Let the plug connect to Home Assistant

1. Make sure the plug can reach Home Assistant on ports `1821` and `1822`.
2. Wait for the plug to contact the Home Assistant host.
3. The integration should automatically discover the plug and create entities.

---

## Notes

- Only one Tenda hub instance can be configured
- Using a direct Home Assistant IP address is recommended if hostname discovery is unreliable
- Live power values can be refreshed on demand
- Energy history updates are delayed and should not be refreshed too aggressively
- If the plug does not appear:
  - verify local network connectivity
  - test ping reachability
  - check firewall rules for ports `1821` and `1822`
