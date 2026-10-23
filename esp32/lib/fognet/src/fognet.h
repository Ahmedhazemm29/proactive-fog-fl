// fognet: the connection from an ESP32 to the fog node.
//
// Wi-Fi, the MQTT broker's address found with mDNS (e.g. fognode1.local),
// and the MQTT connection with a Last Will. All of it reconnects by itself:
// call update() in every loop(). The same logic as src/sensor/main.cpp,
// as a library so the FL client can use it.
#pragma once

#include <Arduino.h>
#include <PubSubClient.h>

// "esp32-" and the last 2 bytes of the board's Wi-Fi MAC in hex, e.g.
// "esp32-a1b2". Every board gets its own ID without any per-board setting.
String clientIdFromMac();

// The board's Wi-Fi MAC as 6 bytes (the client ID and the local data use it).
void readMac(uint8_t mac[6]);

class FogLink {
 public:
  explicit FogLink(PubSubClient& mqtt) : mqtt_(mqtt) {}

  // ssid/password: the Wi-Fi. clientId: MQTT client ID and mDNS name.
  // brokerName: mDNS name of the broker without ".local" (e.g. "fognode1").
  // willTopic/willMessage: published (retained) by the broker when this
  //   board disappears without saying goodbye.
  // onConnect: runs after every (re)connect, e.g. to subscribe and to say
  //   "online"; the broker forgets subscriptions when the connection drops.
  void begin(const char* ssid, const char* password, const String& clientId,
             const char* brokerName, uint16_t port, const String& willTopic,
             const char* willMessage, void (*onConnect)());

  // Keeps everything connected and lets MQTT receive messages.
  // Returns true while MQTT is connected.
  bool update();

 private:
  void startWifi();
  bool checkWifi();
  bool resolveBroker();
  bool checkMqtt();

  PubSubClient& mqtt_;
  const char* ssid_ = nullptr;
  const char* password_ = nullptr;
  String clientId_;
  const char* brokerName_ = nullptr;
  uint16_t port_ = 1883;
  String willTopic_;
  const char* willMessage_ = nullptr;
  void (*onConnect_)() = nullptr;

  IPAddress brokerIp_;              // broker address found with mDNS
  bool brokerKnown_ = false;        // true once brokerIp_ is valid
  bool mdnsStarted_ = false;        // mDNS needs Wi-Fi, so it starts later
  bool wifiWasConnected_ = false;   // to print "connected"/"lost" only once
  unsigned long lastWifiTry_ = 0;   // millis() of the last Wi-Fi attempt
  unsigned long lastMqttTry_ = 0;   // millis() of the last MQTT attempt
};
