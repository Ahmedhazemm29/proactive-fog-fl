// fognet: Wi-Fi, mDNS lookup of the broker and MQTT, reconnecting by itself.
// See fognet.h for how to use it.
#include "fognet.h"

#include <ESPmDNS.h>
#include <WiFi.h>
#include <esp_mac.h>

const unsigned long RETRY_INTERVAL_MS = 5000;   // wait between reconnect tries
const uint32_t MDNS_TIMEOUT_MS = 2000;          // how long one mDNS query may take

// ---- Client ID ----

void readMac(uint8_t mac[6]) {
  esp_read_mac(mac, ESP_MAC_WIFI_STA);   // burnt into the chip, works before Wi-Fi starts
}

String clientIdFromMac() {
  uint8_t mac[6];
  readMac(mac);
  char id[16];
  snprintf(id, sizeof(id), "esp32-%02x%02x", mac[4], mac[5]);
  return String(id);
}

// ---- Setup ----

void FogLink::begin(const char* ssid, const char* password, const String& clientId,
                    const char* brokerName, uint16_t port, const String& willTopic,
                    const char* willMessage, void (*onConnect)()) {
  ssid_ = ssid;
  password_ = password;
  clientId_ = clientId;
  brokerName_ = brokerName;
  port_ = port;
  willTopic_ = willTopic;
  willMessage_ = willMessage;
  onConnect_ = onConnect;

  WiFi.mode(WIFI_STA);          // normal Wi-Fi client, no access point
  WiFi.setAutoReconnect(true);  // let the ESP32 also retry on its own
  startWifi();
}

bool FogLink::update() {
  if (!checkWifi()) {
    return false;   // no Wi-Fi: nothing else to do yet
  }
  if (!checkMqtt()) {
    return false;   // no broker: try again later
  }
  mqtt_.loop();     // keeps the connection alive and receives messages
  return true;
}

// ---- Wi-Fi ----

// Starts (or restarts) the Wi-Fi connection. Does not wait for it.
void FogLink::startWifi() {
  Serial.printf("[wifi] connecting to %s ...\n", ssid_);
  WiFi.disconnect();
  WiFi.begin(ssid_, password_);
  lastWifiTry_ = millis();
}

// Prints changes and retries every RETRY_INTERVAL_MS while Wi-Fi is down.
bool FogLink::checkWifi() {
  bool connected = (WiFi.status() == WL_CONNECTED);
  if (connected && !wifiWasConnected_) {
    Serial.printf("[wifi] connected, IP %s, RSSI %d dBm\n",
                  WiFi.localIP().toString().c_str(), WiFi.RSSI());
  }
  if (!connected && wifiWasConnected_) {
    Serial.println("[wifi] connection lost");
  }
  wifiWasConnected_ = connected;
  if (!connected && millis() - lastWifiTry_ >= RETRY_INTERVAL_MS) {
    startWifi();
  }
  return connected;
}

// ---- Broker address (mDNS) ----

// Looks up <brokerName>.local. Returns true when an address was found.
bool FogLink::resolveBroker() {
  if (!mdnsStarted_) {
    // Our own mDNS name, e.g. esp32-a1b2.local; needed before queries
    mdnsStarted_ = MDNS.begin(clientId_.c_str());
    if (!mdnsStarted_) {
      Serial.println("[mdns] could not start mDNS");
      return false;
    }
  }
  Serial.printf("[mdns] resolving %s.local ...\n", brokerName_);
  IPAddress ip = MDNS.queryHost(brokerName_, MDNS_TIMEOUT_MS);
  if (ip == IPAddress(0, 0, 0, 0)) {   // 0.0.0.0 means no answer
    Serial.printf("[mdns] %s.local not found, retry in %lu s\n",
                  brokerName_, RETRY_INTERVAL_MS / 1000);
    return false;
  }
  brokerIp_ = ip;
  brokerKnown_ = true;
  mqtt_.setServer(brokerIp_, port_);
  Serial.printf("[mdns] %s.local is %s\n", brokerName_, ip.toString().c_str());
  return true;
}

// ---- MQTT ----

// (Re)connects to the broker if needed, at most once every RETRY_INTERVAL_MS.
bool FogLink::checkMqtt() {
  if (mqtt_.connected()) {
    return true;
  }
  if (lastMqttTry_ != 0 && millis() - lastMqttTry_ < RETRY_INTERVAL_MS) {
    return false;
  }
  lastMqttTry_ = millis();

  // Find the broker first (also again after a failed connect, in case the
  // fog node got a new IP address)
  if (!brokerKnown_ && !resolveBroker()) {
    return false;
  }

  Serial.printf("[mqtt] connecting to %s:%u as %s ...\n",
                brokerIp_.toString().c_str(), port_, clientId_.c_str());
  // Last Will: QoS 1, retained, so the fog also sees the leave later on
  if (mqtt_.connect(clientId_.c_str(), willTopic_.c_str(), 1, true, willMessage_)) {
    Serial.println("[mqtt] connected");
    if (onConnect_) {
      onConnect_();
    }
    return true;
  }
  // state() codes: -2 = no TCP connection, -4 = timeout, 5 = not authorized ...
  Serial.printf("[mqtt] failed, state %d, retry in %lu s\n",
                mqtt_.state(), RETRY_INTERVAL_MS / 1000);
  brokerKnown_ = false;   // look the address up again next time
  return false;
}
