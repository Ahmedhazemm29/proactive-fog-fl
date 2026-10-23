// ESP32 hardware sanity test.
//
// Prints a report over serial (115200 baud), for example:
//
//   MAC: 1c:c3:ab:ba:8a:50
//   Chip: ESP32-D0WD-V3, revision v3.1
//   Flash: 4 MB
//   WiFi: connected after 2.3 s
//   IP: 192.168.1.57
//   RSSI: -48 dBm
//
// and prints it again every 5 seconds, so a serial monitor that is opened
// late still sees everything.
//
// If Wi-Fi has not connected after 20 s, it scans once and prints every
// network it sees, for example:
//
//   Scan: networks found: 2
//   Scan: -61 dBm, channel 6, WPA2-PSK, SSID "HomeNet"
//   Scan: -88 dBm, channel 11, WPA2/WPA3-PSK, SSID "Neighbour"
//   Scan: done
//
// sanity_test.py reads these lines, so keep their format when you change them.

#include <Arduino.h>
#include <WiFi.h>
#include <esp_mac.h>  // esp_efuse_mac_get_default()

#include "secrets.h"  // WIFI_SSID and WIFI_PASSWORD (git-ignored)

// ---- Settings ----

const unsigned long REPORT_INTERVAL_MS = 5000;  // one report every 5 s
const unsigned long WIFI_TIMEOUT_MS = 20000;    // no Wi-Fi by then: scan
                                                // (same limit as sanity_test.py)

// ---- State ----

unsigned long wifiStartMs = 0;    // millis() when WiFi.begin() was called
bool wifiConnected = false;       // true after the first connection
float wifiConnectSeconds = 0;     // how long that first connection took
bool wifiScanDone = false;        // true after the scan for a failed connection
unsigned long lastReportMs = 0;   // millis() of the last report

// ---- Hardware info ----

// Prints the MAC address, chip model and revision, and flash size.
void printHardwareInfo() {
  // MAC address burned into the chip (eFuse): the one esptool read_mac shows
  uint8_t mac[6];
  esp_efuse_mac_get_default(mac);
  Serial.printf("MAC: %02x:%02x:%02x:%02x:%02x:%02x\n",
                mac[0], mac[1], mac[2], mac[3], mac[4], mac[5]);

  // The revision comes as major * 100 + minor, e.g. 301 for v3.1
  uint16_t revision = ESP.getChipRevision();
  Serial.printf("Chip: %s, revision v%d.%d\n",
                ESP.getChipModel(), revision / 100, revision % 100);

  // Size of the flash chip, read from the chip's own ID
  unsigned long flashMB = ESP.getFlashChipSize() / (1024 * 1024);
  Serial.printf("Flash: %lu MB\n", flashMB);
}

// ---- Wi-Fi ----

// Readable name for a Wi-Fi status code.
const char* wifiStatusName(wl_status_t status) {
  switch (status) {
    case WL_IDLE_STATUS:     return "idle";
    case WL_NO_SSID_AVAIL:   return "network not found";
    case WL_CONNECTED:       return "connected";
    case WL_CONNECT_FAILED:  return "connection failed, wrong password?";
    case WL_CONNECTION_LOST: return "connection lost";
    case WL_DISCONNECTED:    return "disconnected";
    default:                 return "other";
  }
}

// Prints the Wi-Fi part of the report: IP and RSSI when connected,
// otherwise the current status.
void printWifiInfo(wl_status_t status) {
  if (status == WL_CONNECTED) {
    Serial.printf("WiFi: connected after %.1f s\n", wifiConnectSeconds);
    Serial.printf("IP: %s\n", WiFi.localIP().toString().c_str());
    Serial.printf("RSSI: %d dBm\n", WiFi.RSSI());
  } else {
    float waited = (millis() - wifiStartMs) / 1000.0;
    Serial.printf("WiFi: not connected after %.1f s (status %d: %s)\n",
                  waited, status, wifiStatusName(status));
  }
}

// ---- Wi-Fi scan ----

// Readable name for a Wi-Fi security type.
const char* securityName(wifi_auth_mode_t type) {
  switch (type) {
    case WIFI_AUTH_OPEN:                 return "open";
    case WIFI_AUTH_OWE:                  return "OWE";
    case WIFI_AUTH_WEP:                  return "WEP";
    case WIFI_AUTH_WPA_PSK:              return "WPA-PSK";
    case WIFI_AUTH_WPA2_PSK:             return "WPA2-PSK";
    case WIFI_AUTH_WPA_WPA2_PSK:         return "WPA/WPA2-PSK";
    case WIFI_AUTH_WPA3_PSK:             return "WPA3-PSK";
    case WIFI_AUTH_WPA2_WPA3_PSK:        return "WPA2/WPA3-PSK";
    case WIFI_AUTH_WPA2_ENTERPRISE:      return "WPA2-Enterprise";
    case WIFI_AUTH_WPA2_WPA3_ENTERPRISE: return "WPA2/WPA3-Enterprise";
    default:                             return "other";
  }
}

// Scans once and prints every network the board sees: signal strength
// (RSSI), channel, security type and name (SSID). This shows why Wi-Fi did
// not connect, e.g. the network is out of range or uses another security type.
void scanWifi() {
  // A scan cannot start while the ESP32 is still trying to connect, so stop
  // trying, and don't let it start a new attempt by itself during the scan
  WiFi.setAutoReconnect(false);
  WiFi.disconnect();

  int count = WiFi.scanNetworks(false, true);  // wait for the result, include hidden networks
  if (count < 0) {
    Serial.printf("Scan: failed (error %d)\n", count);
  } else {
    Serial.printf("Scan: networks found: %d\n", count);
    for (int i = 0; i < count; i++) {
      Serial.printf("Scan: %d dBm, channel %d, %s, SSID \"%s\"\n",
                    (int)WiFi.RSSI(i), (int)WiFi.channel(i),
                    securityName(WiFi.encryptionType(i)), WiFi.SSID(i).c_str());
    }
  }
  Serial.println("Scan: done");
  WiFi.scanDelete();  // free the memory of the scan results

  // Keep trying to connect, as before the scan
  WiFi.setAutoReconnect(true);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
}

// ---- Arduino entry points ----

void setup() {
  Serial.begin(115200);
  delay(500);  // give the serial monitor a moment

  Serial.println();  // ends any boot noise on the line before
  Serial.println("=== ESP32 sanity test ===");  // once per boot
  printHardwareInfo();

  // Start connecting; loop() watches for the connection
  WiFi.mode(WIFI_STA);  // normal Wi-Fi client, no access point
  Serial.printf("WiFi: connecting to \"%s\" ...\n", WIFI_SSID);
  wifiStartMs = millis();
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  lastReportMs = millis();  // first full report 5 s from now
}

void loop() {
  wl_status_t status = WiFi.status();

  // First connection: note how long it took and report it right away
  if (status == WL_CONNECTED && !wifiConnected) {
    wifiConnected = true;
    wifiConnectSeconds = (millis() - wifiStartMs) / 1000.0;
    printWifiInfo(status);
  }

  // No connection within WIFI_TIMEOUT_MS: print the status, then scan once
  if (!wifiConnected && !wifiScanDone && millis() - wifiStartMs >= WIFI_TIMEOUT_MS) {
    wifiScanDone = true;
    printWifiInfo(status);
    scanWifi();
    return;  // start the next loop with a fresh Wi-Fi status
  }

  // Full report every REPORT_INTERVAL_MS
  if (millis() - lastReportMs >= REPORT_INTERVAL_MS) {
    lastReportMs = millis();
    Serial.printf("--- report at %.1f s ---\n", millis() / 1000.0);
    printHardwareInfo();
    printWifiInfo(status);
  }

  delay(100);  // check the Wi-Fi status 10 times per second
}
