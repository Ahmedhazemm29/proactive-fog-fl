// ESP32 federated learning client (first version: no secure aggregation yet).
//
// Every board runs this same firmware:
//   - Client ID from the chip's MAC: esp32-<last 4 hex>, e.g. esp32-a1b2.
//     Used as MQTT client ID, in the topics and as mDNS name.
//   - Local data: a time series made on the board, a sine wave with noise.
//     Its amplitude, period, phase, offset, noise and length come from the
//     MAC, so every client has different data. The data never leaves the board.
//   - Model: linear regression that predicts the next value from the last 4
//     (4 weights and a bias), trained on the board with SGD.
//
// Protocol (MQTT on fognode1.local:1883, messages in JSON):
//   fog/<id>/status   "online" (retained) after every connect. The broker
//                     publishes "offline" (retained, the Last Will) when the
//                     board disappears, so the fog sees leaves.
//   fog/global/model  from the aggregator, retained:
//                     {"run":1792900000,"round":3,"weights":[b,w1,w2,w3,w4]}
//   fog/<id>/update   to the aggregator, after local training:
//                     {"run":...,"round":3,"weights":[...],"num_samples":236,
//                      "loss":0.0123,"loss_before":0.0456}
//                     loss_before: mean squared error of the global model on
//                     the local data; loss: the same after local training.
//
// Wi-Fi, the broker lookup and MQTT reconnects come from lib/fognet.

#include <Arduino.h>
#include <ArduinoJson.h>
#include <PubSubClient.h>
#include <WiFi.h>

#include "fognet.h"
#include "secrets.h"   // WIFI_SSID and WIFI_PASSWORD (git-ignored)

// ---- Settings ----

const char* BROKER_NAME = "fognode1";      // the Pi, answers to fognode1.local
const uint16_t BROKER_PORT = 1883;
const char* MODEL_TOPIC = "fog/global/model";

const int LAGS = 4;                        // the model sees the last 4 values
const int NUM_WEIGHTS = LAGS + 1;          // bias + 4 weights
const int LOCAL_EPOCHS = 5;                // passes over the local data per round
const float LEARNING_RATE = 0.01;
const int MIN_POINTS = 150;                // length of the local series,
const int MAX_POINTS = 300;                // somewhere in between per board

// ---- Global objects and state ----

WiFiClient wifiClient;
PubSubClient mqtt(wifiClient);
FogLink fog(mqtt);         // Wi-Fi, broker lookup and MQTT reconnects

String clientId;        // esp32-<last 4 hex of the MAC>
String statusTopic;     // fog/<id>/status
String updateTopic;     // fog/<id>/update

// Local data
float series[MAX_POINTS];
int numPoints = 0;      // length of the series; samples = numPoints - LAGS
uint32_t rngState = 1;  // random generator, seeded from the MAC

// A new round from the aggregator, filled in by the MQTT callback and
// handled in loop(). (PubSubClient reuses its buffer when publishing, so
// the callback only copies the message and does not publish itself.)
bool roundPending = false;
uint32_t pendingRun = 0;
long pendingRound = 0;
float pendingWeights[NUM_WEIGHTS];

// The last round this board trained, so a repeated message is skipped
uint32_t lastRun = 0;
long lastRound = -1;

// ---- Random numbers (deterministic per board) ----

// xorshift32: small and fast; the same seed always gives the same numbers
uint32_t nextRandom() {
  rngState ^= rngState << 13;
  rngState ^= rngState >> 17;
  rngState ^= rngState << 5;
  return rngState;
}

float uniform() {   // 0 <= u < 1
  return (nextRandom() >> 8) / 16777216.0f;
}

float gaussian() {  // standard normal, Box-Muller
  float u1 = max(uniform(), 1e-7f);
  float u2 = uniform();
  return sqrtf(-2.0f * logf(u1)) * cosf(2.0f * PI * u2);
}

// ---- Local data ----

// Makes this board's series. Every parameter comes from the MAC (through
// the random generator), so each board has its own data and keeps it
// after a reboot.
void makeLocalData() {
  uint8_t mac[6];
  readMac(mac);
  rngState = ((uint32_t)mac[2] << 24) | ((uint32_t)mac[3] << 16) | ((uint32_t)mac[4] << 8) | mac[5];
  if (rngState == 0) {
    rngState = 1;   // xorshift must not start at 0
  }
  for (int i = 0; i < 10; i++) {
    nextRandom();   // mix the seed a little first
  }

  float amplitude = 0.5 + 1.0 * uniform();
  float period = 20 + 40 * uniform();          // in samples
  float phase = 2 * PI * uniform();
  float offset = -0.5 + 1.0 * uniform();
  float noise = 0.02 + 0.13 * uniform();       // standard deviation
  numPoints = MIN_POINTS + nextRandom() % (MAX_POINTS - MIN_POINTS + 1);

  for (int t = 0; t < numPoints; t++) {
    series[t] = offset + amplitude * sinf(2 * PI * t / period + phase) + noise * gaussian();
  }
  Serial.printf("[data] %d samples: amplitude %.2f, period %.1f, phase %.2f, "
                "offset %.2f, noise %.3f\n",
                numPoints - LAGS, amplitude, period, phase, offset, noise);
}

// ---- Model: linear regression on the last 4 values ----

// Prediction of series[t] from series[t-1] .. series[t-4].
// w[0] is the bias, w[1] the weight of the newest value.
float predict(const float* w, int t) {
  float y = w[0];
  for (int i = 1; i <= LAGS; i++) {
    y += w[i] * series[t - i];
  }
  return y;
}

// Mean squared error of the weights on the local data.
float meanSquaredError(const float* w) {
  float sum = 0;
  for (int t = LAGS; t < numPoints; t++) {
    float error = predict(w, t) - series[t];
    sum += error * error;
  }
  return sum / (numPoints - LAGS);
}

// LOCAL_EPOCHS passes of SGD over the local samples, in a new random order
// each pass. Changes w in place.
void trainLocally(float* w) {
  static int order[MAX_POINTS];
  int samples = numPoints - LAGS;
  for (int i = 0; i < samples; i++) {
    order[i] = LAGS + i;
  }
  for (int epoch = 0; epoch < LOCAL_EPOCHS; epoch++) {
    for (int i = samples - 1; i > 0; i--) {   // shuffle (Fisher-Yates)
      int j = nextRandom() % (i + 1);
      int keep = order[i];
      order[i] = order[j];
      order[j] = keep;
    }
    for (int i = 0; i < samples; i++) {
      int t = order[i];
      float error = predict(w, t) - series[t];
      w[0] -= LEARNING_RATE * error;
      for (int k = 1; k <= LAGS; k++) {
        w[k] -= LEARNING_RATE * error * series[t - k];
      }
    }
  }
}

// ======================================================================
// SECURE AGGREGATION HOOK
// protect_update() gets the locally trained weights and fills in what is
// sent to the fog. Secure aggregation goes here later, for example pairwise
// masks that cancel out when the fog adds all updates, so the fog only
// learns the combined model and never one client's weights.
// For now it passes the weights through unchanged.
// ======================================================================
void protect_update(const float* weights, float* sent, int count) {
  for (int i = 0; i < count; i++) {
    sent[i] = weights[i];
  }
}

// ---- Rounds ----

// Trains on the new global model and publishes the update.
void runRound() {
  float w[NUM_WEIGHTS];
  memcpy(w, pendingWeights, sizeof(w));

  float lossBefore = meanSquaredError(w);
  unsigned long start = micros();
  trainLocally(w);
  unsigned long trainingUs = micros() - start;
  float loss = meanSquaredError(w);

  float sent[NUM_WEIGHTS];
  protect_update(w, sent, NUM_WEIGHTS);

  JsonDocument doc;
  doc["run"] = pendingRun;
  doc["round"] = pendingRound;
  JsonArray weights = doc["weights"].to<JsonArray>();
  for (int i = 0; i < NUM_WEIGHTS; i++) {
    weights.add(sent[i]);
  }
  doc["num_samples"] = numPoints - LAGS;
  doc["loss"] = loss;
  doc["loss_before"] = lossBefore;
  char payload[384];
  serializeJson(doc, payload, sizeof(payload));

  bool ok = mqtt.publish(updateTopic.c_str(), payload);
  lastRun = pendingRun;
  lastRound = pendingRound;
  Serial.printf("[fl] round %ld: loss %.4f -> %.4f, trained in %lu us, update %s\n",
                pendingRound, lossBefore, loss, trainingUs, ok ? "sent" : "FAILED");
}

// Called by PubSubClient for every message on fog/global/model.
void onMessage(char* topic, byte* payload, unsigned int length) {
  if (length == 0) {
    return;   // the aggregator cleared the retained model
  }
  JsonDocument doc;
  DeserializationError error = deserializeJson(doc, payload, length);
  if (error) {
    Serial.printf("[fl] bad model message: %s\n", error.c_str());
    return;
  }
  JsonArray weights = doc["weights"];
  if (weights.size() != NUM_WEIGHTS) {
    Serial.printf("[fl] model has %d weights, expected %d\n", (int)weights.size(), NUM_WEIGHTS);
    return;
  }
  uint32_t run = doc["run"];
  long round = doc["round"];
  if (run == lastRun && round <= lastRound) {
    return;   // already trained (e.g. the retained model again after a reconnect)
  }
  for (int i = 0; i < NUM_WEIGHTS; i++) {
    pendingWeights[i] = weights[i];
  }
  pendingRun = run;
  pendingRound = round;
  roundPending = true;
}

// After every (re)connect: say "online" and listen for the global model.
void onConnect() {
  mqtt.publish(statusTopic.c_str(), "online", true);   // retained
  mqtt.subscribe(MODEL_TOPIC, 1);
  Serial.printf("[fl] online, waiting for rounds on %s\n", MODEL_TOPIC);
}

// ---- Arduino entry points ----

void setup() {
  Serial.begin(115200);
  delay(500);   // give the serial monitor a moment

  clientId = clientIdFromMac();
  statusTopic = "fog/" + clientId + "/status";
  updateTopic = "fog/" + clientId + "/update";
  Serial.printf("\n[boot] FL client %s\n", clientId.c_str());

  makeLocalData();

  mqtt.setBufferSize(512);   // room for the model and update messages
  mqtt.setCallback(onMessage);
  fog.begin(WIFI_SSID, WIFI_PASSWORD, clientId, BROKER_NAME, BROKER_PORT,
            statusTopic, "offline", onConnect);
}

void loop() {
  if (!fog.update()) {
    return;
  }
  if (roundPending) {
    roundPending = false;
    runRound();
  }
}
