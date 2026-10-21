// ESP32 fog client: sends small JSON messages to the MQTT broker.
//
// Topic:   fog/client<ID>/data
// Message: {"client_id":1,"counter":42,"millis":42012,"sensor":23.71,"rate":1}
//
// The publish rate (messages per second, 1 to 50, default 1) can be changed
// live on fog/client<ID>/control, e.g.
//   mosquitto_pub -h fognode1.local -t fog/client1/control -m 30
// Add -r (retained) to keep the rate after the ESP32 reconnects or reboots.
//
// The broker's address is found with mDNS (fognode1.local), not hard-coded.
// Wi-Fi and MQTT reconnect by themselves if the connection drops.

#include <Arduino.h>
#include <WiFi.h>
#include <ESPmDNS.h>
#include <PubSubClient.h>

#include "secrets.h"  // WIFI_SSID and WIFI_PASSWORD (git-ignored)

// ---- Settings ----

// Client id, set at build time with -DCLIENT_ID=2 (default 1)
#ifndef CLIENT_ID
#define CLIENT_ID 1
#endif

const char* MQTT_HOSTNAME = "fognode1";  // the Pi, answers to fognode1.local
const uint16_t MQTT_PORT = 1883;
const uint32_t MDNS_TIMEOUT_MS = 2000;   // how long one mDNS query may take
const int DEFAULT_RATE = 1;   // messages per second at boot
const int MIN_RATE = 1;
const int MAX_RATE = 50;
const unsigned long RETRY_INTERVAL_MS = 5000;    // wait between reconnect tries

// ---- Global objects and state ----

WiFiClient wifiClient;              // TCP connection used by MQTT
PubSubClient mqtt(wifiClient);      // MQTT client on top of it

String topic;                       // fog/client<ID>/data
String controlTopic;                // fog/client<ID>/control
String mqttClientName;             // name the broker sees, e.g. esp32-client1
IPAddress brokerIp;                 // broker address found with mDNS
bool brokerKnown = false;           // true once brokerIp is valid
bool mdnsStarted = false;           // mDNS needs Wi-Fi, so it starts later

unsigned long counter = 0;          // number of messages sent
int rate = DEFAULT_RATE;            // messages per second right now
unsigned long publishIntervalUs = 1000000UL / DEFAULT_RATE;  // time between messages
unsigned long nextPublishUs = 0;    // micros() when the next message is due
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

// ---- Broker address (mDNS) ----

// Looks up fognode1.local with mDNS. Returns true when an address was found.
bool resolveBroker() {
  if (!mdnsStarted) {
    // Our own mDNS name, e.g. esp32-client1.local; needed before queries
    mdnsStarted = MDNS.begin(mqttClientName.c_str());
    if (!mdnsStarted) {
      Serial.println("[mdns] could not start mDNS");
      return false;
    }
  }

  Serial.printf("[mdns] resolving %s.local ...\n", MQTT_HOSTNAME);
  IPAddress ip = MDNS.queryHost(MQTT_HOSTNAME, MDNS_TIMEOUT_MS);
  if (ip == IPAddress(0, 0, 0, 0)) {  // 0.0.0.0 means no answer
    Serial.printf("[mdns] %s.local not found, retry in %lu s\n",
                  MQTT_HOSTNAME, RETRY_INTERVAL_MS / 1000);
    return false;
  }

  brokerIp = ip;
  brokerKnown = true;
  mqtt.setServer(brokerIp, MQTT_PORT);
  Serial.printf("[mdns] %s.local is %s\n", MQTT_HOSTNAME, ip.toString().c_str());
  return true;
}

// ---- MQTT ----

// Called every loop once Wi-Fi is up: (re)connects to the broker if needed.
// Returns true when MQTT is connected.
bool checkMqtt() {
  if (mqtt.connected()) {
    return true;
  }
  // Don't hammer the network: one try every RETRY_INTERVAL_MS
  if (lastMqttTry != 0 && millis() - lastMqttTry < RETRY_INTERVAL_MS) {
    return false;
  }
  lastMqttTry = millis();

  // Find the broker first (also again after a failed connect, in case
  // the Pi got a new IP address)
  if (!brokerKnown && !resolveBroker()) {
    return false;
  }

  Serial.printf("[mqtt] connecting to %s:%u as %s ...\n",
                brokerIp.toString().c_str(), MQTT_PORT, mqttClientName.c_str());
  if (mqtt.connect(mqttClientName.c_str())) {
    Serial.println("[mqtt] connected");
    // Subscribe again after every connect: the broker forgets it on a drop
    mqtt.subscribe(controlTopic.c_str());
    Serial.printf("[mqtt] listening for rate changes on %s\n", controlTopic.c_str());
    return true;
  }
  // state() codes: -2 = no TCP connection, -4 = timeout, 5 = not authorized ...
  Serial.printf("[mqtt] failed, state %d, retry in %lu s\n",
                mqtt.state(), RETRY_INTERVAL_MS / 1000);
  brokerKnown = false;  // look the address up again next time
  return false;
}

// ---- Control topic ----

// Called by PubSubClient for every message on fog/client<ID>/control.
// The payload is the new rate as a plain number, e.g. "30".
void onControl(char* receivedTopic, byte* payload, unsigned int length) {
  // Copy the payload into a normal C string (it has no end marker)
  char text[16];
  unsigned int n = min(length, (unsigned int)(sizeof(text) - 1));
  memcpy(text, payload, n);
  text[n] = '\0';

  int newRate = atoi(text);  // 0 if the text is not a number
  if (newRate < MIN_RATE || newRate > MAX_RATE) {
    Serial.printf("[ctrl] ignored \"%s\": rate must be %d to %d\n",
                  text, MIN_RATE, MAX_RATE);
    return;
  }
  rate = newRate;
  publishIntervalUs = 1000000UL / rate;
  nextPublishUs = micros();  // start the new rate right away
  Serial.printf("[ctrl] rate set to %d msg/s\n", rate);
}

// ---- Message ----

// Builds the JSON message and publishes it.
void publishReading() {
  counter++;

  // Fake sensor: a slow sine wave around 25 plus a little noise
  float sensor = 25.0 + 5.0 * sin(millis() / 10000.0) + random(-50, 51) / 100.0;

  char payload[128];
  snprintf(payload, sizeof(payload),
           "{\"client_id\":%d,\"counter\":%lu,\"millis\":%lu,\"sensor\":%.2f,\"rate\":%d}",
           CLIENT_ID, counter, millis(), sensor, rate);

  bool ok = mqtt.publish(topic.c_str(), payload);
  // Print about one line per second, not every message at 50 msg/s
  if (!ok) {
    Serial.println("[pub] publish failed");
  } else if (counter % rate == 0) {
    Serial.printf("[pub] %s %s\n", topic.c_str(), payload);
  }
}

// ---- Arduino entry points ----

void setup() {
  Serial.begin(115200);
  delay(500);  // give the serial monitor a moment
  Serial.printf("\n[boot] fog client %d starting\n", CLIENT_ID);

  topic = "fog/client" + String(CLIENT_ID) + "/data";
  controlTopic = "fog/client" + String(CLIENT_ID) + "/control";
  mqttClientName = "esp32-client" + String(CLIENT_ID);

  WiFi.mode(WIFI_STA);          // normal Wi-Fi client, no access point
  WiFi.setAutoReconnect(true);  // let the ESP32 also retry on its own
  startWifi();
  // The broker address is set in resolveBroker(), once Wi-Fi is up
  mqtt.setCallback(onControl);  // handles messages on the control topic
}

void loop() {
  if (!checkWifi()) {
    return;  // no Wi-Fi: nothing else to do yet
  }
  if (!checkMqtt()) {
    return;  // no broker: try again later
  }

  mqtt.loop();  // keeps the MQTT connection alive and receives control messages

  // Publish when the next message is due. Moving the due time forward by
  // one interval (not to "now") keeps the average rate exact.
  unsigned long now = micros();
  if ((long)(now - nextPublishUs) >= 0) {
    publishReading();
    nextPublishUs += publishIntervalUs;
    // Far behind (e.g. after a reconnect): don't send a burst to catch up
    if ((long)(now - nextPublishUs) >= (long)publishIntervalUs) {
      nextPublishUs = now + publishIntervalUs;
    }
  }
}
