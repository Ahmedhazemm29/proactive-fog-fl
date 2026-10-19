// ESP32 fog client: sends a small JSON message to the MQTT broker every second.
//
// Topic:   fog/client<ID>/data
// Message: {"client_id":1,"counter":42,"millis":42012,"sensor":23.71}
//
// Wi-Fi and MQTT reconnect by themselves if the connection drops.

#include <Arduino.h>
#include <WiFi.h>
#include <PubSubClient.h>

#include "secrets.h"  // WIFI_SSID and WIFI_PASSWORD (git-ignored)

// ---- Settings ----

// Client id, set at build time with -DCLIENT_ID=2 (default 1)
#ifndef CLIENT_ID
#define CLIENT_ID 1
#endif

const char* MQTT_HOST = "192.168.1.113";
const uint16_t MQTT_PORT = 1883;
const unsigned long PUBLISH_INTERVAL_MS = 1000;  // one message per second
const unsigned long RETRY_INTERVAL_MS = 5000;    // wait between reconnect tries

// ---- Global objects and state ----

WiFiClient wifiClient;              // TCP connection used by MQTT
PubSubClient mqtt(wifiClient);      // MQTT client on top of it

String topic;                       // fog/client<ID>/data
String mqttClientName;              // name the broker sees, e.g. esp32-client1

unsigned long counter = 0;          // number of messages sent
unsigned long lastPublish = 0;      // millis() of the last message
unsigned long lastWifiTry = 0;      // millis() of the last Wi-Fi attempt
unsigned long lastMqttTry = 0;      // millis() of the last MQTT attempt
bool wifiWasConnected = false;      // to print "connected"/"lost" only once

// ---- Wi-Fi ----

// Starts (or restarts) the Wi-Fi connection. Does not wait for it.
void startWifi() {
  Serial.printf("[wifi] connecting to %s ...\n", WIFI_SSID);
  WiFi.disconnect();
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  lastWifiTry = millis();
}

// Called every loop: prints changes and retries when Wi-Fi is down.
// Returns true when Wi-Fi is connected.
bool checkWifi() {
  bool connected = (WiFi.status() == WL_CONNECTED);

  if (connected && !wifiWasConnected) {
    Serial.printf("[wifi] connected, IP %s, RSSI %d dBm\n",
                  WiFi.localIP().toString().c_str(), WiFi.RSSI());
  }
  if (!connected && wifiWasConnected) {
    Serial.println("[wifi] connection lost");
  }
  wifiWasConnected = connected;

  // Not connected: try again every RETRY_INTERVAL_MS
  if (!connected && millis() - lastWifiTry >= RETRY_INTERVAL_MS) {
    startWifi();
  }
  return connected;
}

// ---- MQTT ----

// Called every loop once Wi-Fi is up: (re)connects to the broker if needed.
// Returns true when MQTT is connected.
bool checkMqtt() {
  if (mqtt.connected()) {
    return true;
  }
  // Don't hammer the broker: one try every RETRY_INTERVAL_MS
  if (lastMqttTry != 0 && millis() - lastMqttTry < RETRY_INTERVAL_MS) {
    return false;
  }
  lastMqttTry = millis();

  Serial.printf("[mqtt] connecting to %s:%u as %s ...\n",
                MQTT_HOST, MQTT_PORT, mqttClientName.c_str());
  if (mqtt.connect(mqttClientName.c_str())) {
    Serial.println("[mqtt] connected");
    return true;
  }
  // state() codes: -2 = no TCP connection, -4 = timeout, 5 = not authorized ...
  Serial.printf("[mqtt] failed, state %d, retry in %lu s\n",
                mqtt.state(), RETRY_INTERVAL_MS / 1000);
  return false;
}

// ---- Message ----

// Builds the JSON message and publishes it.
void publishReading() {
  counter++;

  // Fake sensor: a slow sine wave around 25 plus a little noise
  float sensor = 25.0 + 5.0 * sin(millis() / 10000.0) + random(-50, 51) / 100.0;

  char payload[128];
  snprintf(payload, sizeof(payload),
           "{\"client_id\":%d,\"counter\":%lu,\"millis\":%lu,\"sensor\":%.2f}",
           CLIENT_ID, counter, millis(), sensor);

  if (mqtt.publish(topic.c_str(), payload)) {
    Serial.printf("[pub] %s %s\n", topic.c_str(), payload);
  } else {
    Serial.println("[pub] publish failed");
  }
}

// ---- Arduino entry points ----

void setup() {
  Serial.begin(115200);
  delay(500);  // give the serial monitor a moment
  Serial.printf("\n[boot] fog client %d starting\n", CLIENT_ID);

  topic = "fog/client" + String(CLIENT_ID) + "/data";
  mqttClientName = "esp32-client" + String(CLIENT_ID);

  WiFi.mode(WIFI_STA);          // normal Wi-Fi client, no access point
  WiFi.setAutoReconnect(true);  // let the ESP32 also retry on its own
  startWifi();

  mqtt.setServer(MQTT_HOST, MQTT_PORT);
}

void loop() {
  if (!checkWifi()) {
    return;  // no Wi-Fi: nothing else to do yet
  }
  if (!checkMqtt()) {
    return;  // no broker: try again later
  }

  mqtt.loop();  // keeps the MQTT connection alive (ping)

  if (millis() - lastPublish >= PUBLISH_INTERVAL_MS) {
    lastPublish = millis();
    publishReading();
  }
}
