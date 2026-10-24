// Secure-aggregation benchmark for ONE ESP32 (not the FL client).
//
// Times, once each, what one FL client would compute per round for
//   - pairwise masking (Bonawitz et al. 2017, fresh keys every round), for
//     7 and 50 clients: the same steps as MaskingClient in
//     scripts/secagg_benchmark.py (X25519, SHA-256, AES-GCM, AES-CTR masks,
//     Shamir shares in the field 2^521 - 1);
//   - Paillier encryption of one update with 2048 and 3072-bit keys: 6
//     ciphertexts (one per value) or 1 packed ciphertext (6 slots of 64 bits).
//     Two ways: mbedTLS (the ESP32's big-number hardware, moduli up to 4096
//     bits) and plain software Montgomery code (montgomery.h, any size).
// Before and after every step it records the free heap, and the lowest free
// heap during the step. Wi-Fi and MQTT are connected the whole time, as in
// the FL client.
//
// Then it publishes the messages a client would send (JSON, binary data in
// base64) on bench/<id>/<name>, not retained, so the laptop can measure their
// real size (and decrypt the Paillier ones to check them). Nothing goes to
// the fog/ topics. Results go to the serial port (115200) as lines starting
// with "RESULT", and are printed again every 30 s.
//
// Laptop side (test keys, message sizes, checking the ciphertexts):
// scripts/secagg_esp32_tools.py. Results: results/secagg_benchmark/report.md.
//
//   pio run -e secagg_bench -t upload --upload-port /dev/ttyUSB0

#include <Arduino.h>
#include <ArduinoJson.h>
#include <PubSubClient.h>
#include <WiFi.h>
#include <esp_heap_caps.h>
#include <esp_random.h>
#include <esp_timer.h>
#include <mbedtls/aes.h>
#include <mbedtls/base64.h>
#include <mbedtls/bignum.h>
#include <mbedtls/ecdh.h>
#include <mbedtls/gcm.h>
#include <mbedtls/sha256.h>

#include "fognet.h"
#include "montgomery.h"
#include "paillier_keys.h"
#include "secrets.h"   // WIFI_SSID and WIFI_PASSWORD (git-ignored)

SET_LOOP_TASK_STACK_SIZE(32 * 1024);   // room for mbedTLS; the high-water mark is printed

// ---- Settings ----

const char* BROKER_NAME = "fognode1";
const uint16_t BROKER_PORT = 1883;
const int VALUES = 6;               // 5 weighted weights and num_samples, as in the Python benchmark
const double SCALE = 16777216.0;    // 2^24 fixed point
const uint64_t OFFSET = 1ULL << 40; // packed Paillier: makes every value positive
const int MAX_CLIENTS = 50;
const int SHARE_BYTES = 66;         // one Shamir share (field 2^521 - 1)
const int PAYLOAD_BYTES = 2 * SHARE_BYTES;          // the shares of b and s_sk for one peer
const int BLOB_BYTES = 12 + PAYLOAD_BYTES + 16;     // nonce + AES-GCM ciphertext + tag

// The update every encryption uses: 5 weights and num_samples
const double WEIGHTS[5] = {0.1234, -0.3456, 0.5678, -0.7891, 0.9012};
const int NUM_SAMPLES = 236;

// ---- Objects ----

WiFiClient wifiClient;
PubSubClient mqtt(wifiClient);
FogLink fog(mqtt);
String clientId;
String topicBase;   // bench/<id>/

// ---- Results ----

struct Result {
  String name;
  int64_t us;            // wall time of the step in microseconds
  unsigned freeBefore;   // free heap before the step (bytes)
  unsigned freeAfter;    // free heap after it
  unsigned minDuring;    // lowest free heap during it
  int ret;               // 0 = ok, else the error code
};
Result results[64];
int numResults = 0;

struct Message {
  String name;
  String payload;
  bool sent;
};
Message messages[32];
int numMessages = 0;

int64_t stepStart;
unsigned stepFree;

void beginStep() {
  heap_caps_monitor_local_minimum_free_size_start();
  stepFree = heap_caps_get_free_size(MALLOC_CAP_8BIT);
  stepStart = esp_timer_get_time();
}

void endStep(const String& name, int ret) {
  int64_t us = esp_timer_get_time() - stepStart;
  unsigned minDuring = heap_caps_get_minimum_free_size(MALLOC_CAP_8BIT);
  heap_caps_monitor_local_minimum_free_size_stop();
  Result& r = results[numResults++];
  r = {name, us, stepFree, heap_caps_get_free_size(MALLOC_CAP_8BIT), minDuring, ret};
  Serial.printf("RESULT %s us=%lld free_before=%u free_after=%u min_free=%u ret=%d\n",
                name.c_str(), (long long)us, r.freeBefore, r.freeAfter, r.minDuring, ret);
}

void addMessage(const String& name, const String& payload) {
  messages[numMessages++] = {name, payload, false};
}

// ---- Helpers ----

int rng(void*, unsigned char* out, size_t len) {
  esp_fill_random(out, len);
  return 0;
}

String base64(const uint8_t* data, size_t len) {
  size_t outLen = 0;
  String s;
  s.reserve(4 * (len + 2) / 3 + 1);
  char* buf = (char*)malloc(4 * (len + 2) / 3 + 1);
  mbedtls_base64_encode((unsigned char*)buf, 4 * (len + 2) / 3 + 1, &outLen, data, len);
  buf[outLen] = 0;
  s = buf;
  free(buf);
  return s;
}

String peerId(int v) {
  char id[16];
  snprintf(id, sizeof(id), "esp32-%04x", v);
  return String(id);
}

// The 6 values of the update in fixed point (as to_fixed() in the Python benchmark)
void fixedValues(int64_t out[VALUES]) {
  for (int i = 0; i < 5; i++) {
    out[i] = llround(WEIGHTS[i] * NUM_SAMPLES * SCALE);
  }
  out[5] = llround(NUM_SAMPLES * SCALE);
}

// ----------------------------------------------------------------------
// Pairwise masking
// ----------------------------------------------------------------------
mbedtls_ecp_group curve;
mbedtls_ecp_point peerC[MAX_CLIENTS], peerS[MAX_CLIENTS];   // the other clients' public keys
mbedtls_mpi prime;                                          // 2^521 - 1

// 32-byte key from an X25519 key agreement, hashed with SHA-256 (kdf in Python)
int agree(const mbedtls_mpi& myKey, const mbedtls_ecp_point& peer, uint8_t key[32]) {
  mbedtls_mpi z;
  mbedtls_mpi_init(&z);
  int ret = mbedtls_ecdh_compute_shared(&curve, &z, &peer, &myKey, rng, nullptr);
  uint8_t shared[32];
  if (ret == 0) ret = mbedtls_mpi_write_binary_le(&z, shared, 32);
  if (ret == 0) ret = mbedtls_sha256(shared, 32, key, 0);
  mbedtls_mpi_free(&z);
  return ret;
}

// 6 numbers mod 2^64 from a 32-byte seed: AES-256 in counter mode (prg in Python)
int prg(const uint8_t seed[32], uint64_t out[VALUES]) {
  mbedtls_aes_context aes;
  mbedtls_aes_init(&aes);
  uint8_t counter[16] = {0}, block[16], zeros[8 * VALUES] = {0};
  size_t offset = 0;
  int ret = mbedtls_aes_setkey_enc(&aes, seed, 256);
  if (ret == 0) ret = mbedtls_aes_crypt_ctr(&aes, sizeof(zeros), &offset, counter, block, zeros,
                                            (uint8_t*)out);   // little-endian, as in Python
  mbedtls_aes_free(&aes);
  return ret;
}

// n Shamir shares (66 bytes each) of a 32-byte secret; any t rebuild it
int shamirShare(const uint8_t secret[32], int n, int t, uint8_t* shares) {
  mbedtls_mpi coeffs[MAX_CLIENTS], y;
  mbedtls_mpi_init(&y);
  for (int k = 0; k < t; k++) mbedtls_mpi_init(&coeffs[k]);
  int ret = mbedtls_mpi_read_binary(&coeffs[0], secret, 32);
  for (int k = 1; k < t && ret == 0; k++) {
    ret = mbedtls_mpi_fill_random(&coeffs[k], SHARE_BYTES, rng, nullptr);
    if (ret == 0) ret = mbedtls_mpi_mod_mpi(&coeffs[k], &coeffs[k], &prime);
  }
  for (int x = 1; x <= n && ret == 0; x++) {
    ret = mbedtls_mpi_lset(&y, 0);
    for (int k = t - 1; k >= 0 && ret == 0; k--) {   // Horner
      ret = mbedtls_mpi_mul_int(&y, &y, x);
      if (ret == 0) ret = mbedtls_mpi_add_mpi(&y, &y, &coeffs[k]);
      if (ret == 0) ret = mbedtls_mpi_mod_mpi(&y, &y, &prime);
    }
    if (ret == 0) ret = mbedtls_mpi_write_binary(&y, shares + (x - 1) * SHARE_BYTES, SHARE_BYTES);
  }
  for (int k = 0; k < t; k++) mbedtls_mpi_free(&coeffs[k]);
  mbedtls_mpi_free(&y);
  return ret;
}

String publicKeyB64(const mbedtls_ecp_point& Q) {
  uint8_t buf[32];
  size_t len = 0;
  mbedtls_ecp_point_write_binary(&curve, &Q, MBEDTLS_ECP_PF_UNCOMPRESSED, &len, buf, sizeof(buf));
  return base64(buf, len);
}

void maskingSetup() {
  mbedtls_ecp_group_init(&curve);
  mbedtls_ecp_group_load(&curve, MBEDTLS_ECP_DP_CURVE25519);
  mbedtls_mpi_init(&prime);
  mbedtls_mpi_lset(&prime, 1);
  mbedtls_mpi_shift_l(&prime, 521);
  mbedtls_mpi_sub_int(&prime, &prime, 1);

  // The other clients' public keys (not timed: they arrive from the broker)
  mbedtls_mpi d;
  mbedtls_mpi_init(&d);
  for (int v = 1; v < MAX_CLIENTS; v++) {
    mbedtls_ecp_point_init(&peerC[v]);
    mbedtls_ecp_point_init(&peerS[v]);
    mbedtls_ecdh_gen_public(&curve, &d, &peerC[v], rng, nullptr);
    mbedtls_ecdh_gen_public(&curve, &d, &peerS[v], rng, nullptr);
  }
  mbedtls_mpi_free(&d);

  // One key agreement both ways must give the same key
  mbedtls_mpi a, b;
  mbedtls_ecp_point A, B;
  mbedtls_mpi_init(&a); mbedtls_mpi_init(&b);
  mbedtls_ecp_point_init(&A); mbedtls_ecp_point_init(&B);
  uint8_t k1[32], k2[32];
  beginStep();
  int ret = mbedtls_ecdh_gen_public(&curve, &a, &A, rng, nullptr);
  endStep("x25519_keygen", ret);
  mbedtls_ecdh_gen_public(&curve, &b, &B, rng, nullptr);
  beginStep();
  ret = agree(a, B, k1);
  endStep("x25519_agreement_plus_sha256", ret);
  agree(b, A, k2);
  Serial.printf("CHECK x25519 both sides agree: %s\n", memcmp(k1, k2, 32) == 0 ? "yes" : "NO");
  mbedtls_mpi_free(&a); mbedtls_mpi_free(&b);
  mbedtls_ecp_point_free(&A); mbedtls_ecp_point_free(&B);
}

// One client's whole round with n clients; this client has index 0.
void maskingRound(int n) {
  int t = n / 2 + 1;
  int dropped = max(1, (int)lround(0.1 * n));
  String tag = "masking_n" + String(n);
  int ret = 0;

  uint8_t* bShares = (uint8_t*)malloc(n * SHARE_BYTES);
  uint8_t* sShares = (uint8_t*)malloc(n * SHARE_BYTES);
  uint8_t* outbox = (uint8_t*)malloc(n * BLOB_BYTES);
  uint8_t* held = (uint8_t*)malloc(n * PAYLOAD_BYTES);
  uint8_t (*keys)[32] = (uint8_t(*)[32])malloc(n * 32);
  mbedtls_mpi cKey, sKey;
  mbedtls_ecp_point cPub, sPub;
  mbedtls_mpi_init(&cKey); mbedtls_mpi_init(&sKey);
  mbedtls_ecp_point_init(&cPub); mbedtls_ecp_point_init(&sPub);
  uint8_t b[32];
  int64_t x[VALUES];
  uint64_t y[VALUES];
  fixedValues(x);
  int64_t total = 0;

  // Round 0: two fresh key pairs
  beginStep();
  ret = mbedtls_ecdh_gen_public(&curve, &cKey, &cPub, rng, nullptr);
  if (ret == 0) ret = mbedtls_ecdh_gen_public(&curve, &sKey, &sPub, rng, nullptr);
  endStep(tag + "_1_advertise", ret);
  total += results[numResults - 1].us;

  // Round 1: Shamir shares of b and s_sk, encrypted for every other client
  beginStep();
  esp_fill_random(b, 32);
  uint8_t sBytes[32];
  ret = mbedtls_mpi_write_binary(&sKey, sBytes, 32);
  if (ret == 0) ret = shamirShare(b, n, t, bShares);
  if (ret == 0) ret = shamirShare(sBytes, n, t, sShares);
  for (int v = 1; v < n && ret == 0; v++) {
    ret = agree(cKey, peerC[v], keys[v]);
    uint8_t payload[PAYLOAD_BYTES];
    memcpy(payload, bShares + v * SHARE_BYTES, SHARE_BYTES);
    memcpy(payload + SHARE_BYTES, sShares + v * SHARE_BYTES, SHARE_BYTES);
    uint8_t* blob = outbox + v * BLOB_BYTES;
    esp_fill_random(blob, 12);   // nonce
    mbedtls_gcm_context gcm;
    mbedtls_gcm_init(&gcm);
    if (ret == 0) ret = mbedtls_gcm_setkey(&gcm, MBEDTLS_CIPHER_ID_AES, keys[v], 256);
    if (ret == 0) ret = mbedtls_gcm_crypt_and_tag(&gcm, MBEDTLS_GCM_ENCRYPT, PAYLOAD_BYTES, blob, 12,
                                                  nullptr, 0, payload, blob + 12, 16,
                                                  blob + 12 + PAYLOAD_BYTES);
    mbedtls_gcm_free(&gcm);
  }
  endStep(tag + "_2_share_keys", ret);
  total += results[numResults - 1].us;

  // Round 2: decrypt the others' shares (here: the same-size blobs, with the
  // same pairwise keys), then the masked input x + self mask + pairwise masks
  beginStep();
  for (int v = 1; v < n && ret == 0; v++) {
    uint8_t* blob = outbox + v * BLOB_BYTES;
    mbedtls_gcm_context gcm;
    mbedtls_gcm_init(&gcm);
    ret = mbedtls_gcm_setkey(&gcm, MBEDTLS_CIPHER_ID_AES, keys[v], 256);
    if (ret == 0) ret = mbedtls_gcm_auth_decrypt(&gcm, PAYLOAD_BYTES, blob, 12, nullptr, 0,
                                                 blob + 12 + PAYLOAD_BYTES, 16, blob + 12,
                                                 held + v * PAYLOAD_BYTES);
    mbedtls_gcm_free(&gcm);
  }
  uint64_t mask[VALUES];
  if (ret == 0) ret = prg(b, mask);
  for (int i = 0; i < VALUES; i++) y[i] = (uint64_t)x[i] + mask[i];
  for (int v = 1; v < n && ret == 0; v++) {
    uint8_t seed[32];
    ret = agree(sKey, peerS[v], seed);
    if (ret == 0) ret = prg(seed, mask);
    for (int i = 0; i < VALUES; i++) y[i] += mask[i];   // index 0 < v: add
  }
  endStep(tag + "_3_masked_input", ret);
  total += results[numResults - 1].us;
  Serial.printf("CHECK %s: shares decrypted and authenticated: %s\n", tag.c_str(),
                ret == 0 && memcmp(held + PAYLOAD_BYTES, bShares + SHARE_BYTES, SHARE_BYTES) == 0
                    ? "yes" : "NO");

  // The total of the computing steps (round 3 only copies held shares)
  results[numResults] = {tag + "_total", total, 0, 0, 0, ret};
  Serial.printf("RESULT %s us=%lld\n", results[numResults].name.c_str(), (long long)total);
  numResults++;

  // Messages this client sends in the round (built after timing)
  String run = "\"run\":1792900000,\"round\":1";
  addMessage(tag + "_1_advertise",
             "{" + run + ",\"c_pk\":\"" + publicKeyB64(cPub) + "\",\"s_pk\":\"" +
                 publicKeyB64(sPub) + "\"}");
  String shares = "{" + run + ",\"shares\":{";
  for (int v = 1; v < n; v++) {
    shares += (v > 1 ? ",\"" : "\"") + peerId(v) + "\":\"" + base64(outbox + v * BLOB_BYTES, BLOB_BYTES) + "\"";
  }
  addMessage(tag + "_2_shares", shares + "}}");
  String masked = "{" + run + ",\"y\":[";
  for (int i = 0; i < VALUES; i++) {
    char num[24];
    snprintf(num, sizeof(num), "%s%llu", i ? "," : "", (unsigned long long)y[i]);
    masked += num;
  }
  addMessage(tag + "_3_masked_input", masked + "]}");
  // Round 3: my share of every survivor's b; with dropouts, of every dropped client's s_sk
  for (int d : {0, dropped}) {
    String unmask = "{" + run + ",\"b\":{";
    for (int v = 0; v < n - d; v++) {
      const uint8_t* share = v == 0 ? bShares : held + v * PAYLOAD_BYTES;
      unmask += (v ? ",\"" : "\"") + peerId(v) + "\":\"" + base64(share, SHARE_BYTES) + "\"";
    }
    unmask += "},\"s\":{";
    for (int v = n - d; v < n; v++) {
      unmask += (v > n - d ? ",\"" : "\"") + peerId(v) + "\":\"" +
                base64(held + v * PAYLOAD_BYTES + SHARE_BYTES, SHARE_BYTES) + "\"";
    }
    addMessage(tag + "_4_unmask_" + String(d) + "_dropped", unmask + "}}");
  }

  free(bShares); free(sShares); free(outbox); free(held); free(keys);
  mbedtls_mpi_free(&cKey); mbedtls_mpi_free(&sKey);
  mbedtls_ecp_point_free(&cPub); mbedtls_ecp_point_free(&sPub);
}

// ----------------------------------------------------------------------
// Paillier: c = (1 + n*m) * r^n mod n^2
// ----------------------------------------------------------------------
struct PaillierKey {
  int bits;
  mbedtls_mpi n, n2, RR;   // RR: mbedTLS's cached Montgomery constant
  int s;                   // limbs of n^2
  uint32_t *N2, *R2, *oneM, *nLimbs, *tmp;
  uint32_t n0inv;
};

int toLimbs(const mbedtls_mpi& X, uint32_t* out, int s) {
  return mbedtls_mpi_write_binary_le(&X, (uint8_t*)out, s * 4);   // the ESP32 is little-endian
}

// The plaintexts: 6 values (negative ones as n - |v|), or all 6 packed into 384 bits
int plaintexts(PaillierKey& k, bool packed, mbedtls_mpi m[VALUES], int& count) {
  int64_t x[VALUES];
  fixedValues(x);
  int ret = 0;
  if (packed) {
    uint64_t slots[VALUES];
    for (int i = 0; i < VALUES; i++) slots[i] = (uint64_t)(x[i] + (int64_t)OFFSET);
    count = 1;
    return mbedtls_mpi_read_binary_le(&m[0], (uint8_t*)slots, sizeof(slots));
  }
  count = VALUES;
  for (int i = 0; i < VALUES && ret == 0; i++) {
    uint64_t a = (uint64_t)(x[i] < 0 ? -x[i] : x[i]);
    uint8_t be[8];
    for (int j = 0; j < 8; j++) be[j] = (uint8_t)(a >> (56 - 8 * j));
    ret = mbedtls_mpi_read_binary(&m[i], be, 8);
    if (ret == 0 && x[i] < 0) ret = mbedtls_mpi_sub_mpi(&m[i], &k.n, &m[i]);
  }
  return ret;
}

// mbedTLS path (big-number hardware): r^n mod n^2 with mbedtls_mpi_exp_mod
int encryptHardware(PaillierKey& k, const mbedtls_mpi& m, mbedtls_mpi& c) {
  mbedtls_mpi r, rn, gm;
  mbedtls_mpi_init(&r); mbedtls_mpi_init(&rn); mbedtls_mpi_init(&gm);
  int ret = mbedtls_mpi_fill_random(&r, k.bits / 8, rng, nullptr);
  if (ret == 0) ret = mbedtls_mpi_mod_mpi(&r, &r, &k.n);
  if (ret == 0) ret = mbedtls_mpi_exp_mod(&rn, &r, &k.n, &k.n2, &k.RR);
  if (ret == 0) ret = mbedtls_mpi_mul_mpi(&gm, &k.n, &m);
  if (ret == 0) ret = mbedtls_mpi_add_int(&gm, &gm, 1);
  if (ret == 0) ret = mbedtls_mpi_mul_mpi(&c, &gm, &rn);
  if (ret == 0) ret = mbedtls_mpi_mod_mpi(&c, &c, &k.n2);
  mbedtls_mpi_free(&r); mbedtls_mpi_free(&rn); mbedtls_mpi_free(&gm);
  return ret;
}

// Software path: everything in montgomery.h, 32-bit limbs
int encryptSoftware(PaillierKey& k, const mbedtls_mpi& m, mbedtls_mpi& c) {
  int s = k.s, half = s / 2 + 1;
  uint32_t* buf = (uint32_t*)calloc(5 * s, sizeof(uint32_t));
  if (!buf) return -1;
  uint32_t *rL = buf, *x = buf + s, *gm = buf + 2 * s, *mL = buf + 3 * s, *one = buf + 4 * s;
  mbedtls_mpi r;
  mbedtls_mpi_init(&r);
  int ret = mbedtls_mpi_fill_random(&r, k.bits / 8, rng, nullptr);
  if (ret == 0) ret = mbedtls_mpi_mod_mpi(&r, &r, &k.n);
  if (ret == 0) ret = toLimbs(r, rL, s);
  if (ret == 0) ret = toLimbs(m, mL, s);
  if (ret == 0) {
    // r^n in Montgomery form
    mont_mul(rL, rL, k.R2, k.N2, k.n0inv, s, k.tmp);
    mont_exp(x, rL, k.nLimbs, k.bits, k.oneM, k.N2, k.n0inv, s, k.tmp);
    // gm = 1 + n*m (below n^2, so no reduction), schoolbook multiply
    for (int i = 0; i < half; i++) {
      uint64_t carry = 0;
      for (int j = 0; j < half && i + j < s; j++) {
        uint64_t sum = (uint64_t)gm[i + j] + (uint64_t)k.nLimbs[j] * mL[i] + carry;
        gm[i + j] = (uint32_t)sum;
        carry = sum >> 32;
      }
      if (i + half < s) gm[i + half] += (uint32_t)carry;
    }
    uint64_t carry = 1;   // + 1
    for (int i = 0; i < s && carry; i++) {
      uint64_t sum = (uint64_t)gm[i] + carry;
      gm[i] = (uint32_t)sum;
      carry = sum >> 32;
    }
    // c = gm * r^n: to Montgomery form, multiply, back
    mont_mul(gm, gm, k.R2, k.N2, k.n0inv, s, k.tmp);
    mont_mul(x, x, gm, k.N2, k.n0inv, s, k.tmp);
    one[0] = 1;
    mont_mul(x, x, one, k.N2, k.n0inv, s, k.tmp);
    ret = mbedtls_mpi_read_binary_le(&c, (uint8_t*)x, s * 4);
  }
  mbedtls_mpi_free(&r);
  free(buf);
  return ret;
}

int setupKey(PaillierKey& k, int bits, const char* nHex) {
  k.bits = bits;
  mbedtls_mpi_init(&k.n); mbedtls_mpi_init(&k.n2); mbedtls_mpi_init(&k.RR);
  int ret = mbedtls_mpi_read_string(&k.n, 16, nHex);
  if (ret == 0) ret = mbedtls_mpi_mul_mpi(&k.n2, &k.n, &k.n);
  Serial.printf("[paillier %d] n^2 = n*n with mbedTLS: ret=%d, %u bits\n", bits, ret,
                (unsigned)mbedtls_mpi_bitlen(&k.n2));
  if (ret != 0) {
    // n^2 is too big for the hardware multiplier: square n in software instead
    int s = (2 * bits) / 32, h = bits / 32;
    uint32_t* nl = (uint32_t*)calloc(h, 4);
    uint32_t* sq = (uint32_t*)calloc(s, 4);
    toLimbs(k.n, nl, h);
    for (int i = 0; i < h; i++) {
      uint64_t carry = 0;
      for (int j = 0; j < h; j++) {
        uint64_t sum = (uint64_t)sq[i + j] + (uint64_t)nl[i] * nl[j] + carry;
        sq[i + j] = (uint32_t)sum;
        carry = sum >> 32;
      }
      sq[i + h] = (uint32_t)carry;
    }
    ret = mbedtls_mpi_read_binary_le(&k.n2, (uint8_t*)sq, s * 4);
    free(nl); free(sq);
    Serial.printf("[paillier %d] n^2 in software: ret=%d, %u bits\n", bits, ret,
                  (unsigned)mbedtls_mpi_bitlen(&k.n2));
  }
  // Software-path constants: N = n^2 as limbs, R^2 mod N, R mod N
  k.s = (mbedtls_mpi_bitlen(&k.n2) + 31) / 32;
  int s = k.s;
  k.N2 = (uint32_t*)calloc(s, 4);
  k.R2 = (uint32_t*)calloc(s, 4);
  k.oneM = (uint32_t*)calloc(s, 4);
  k.nLimbs = (uint32_t*)calloc(s, 4);
  k.tmp = (uint32_t*)calloc(s + 2, 4);
  mbedtls_mpi R2;
  mbedtls_mpi_init(&R2);
  if (ret == 0) ret = mbedtls_mpi_lset(&R2, 1);
  if (ret == 0) ret = mbedtls_mpi_shift_l(&R2, 64 * s);
  if (ret == 0) ret = mbedtls_mpi_mod_mpi(&R2, &R2, &k.n2);
  if (ret == 0) ret = toLimbs(k.n2, k.N2, s);
  if (ret == 0) ret = toLimbs(R2, k.R2, s);
  if (ret == 0) ret = toLimbs(k.n, k.nLimbs, s);
  mbedtls_mpi_free(&R2);
  k.n0inv = mont_n0inv(k.N2[0]);
  uint32_t* one = (uint32_t*)calloc(s, 4);
  one[0] = 1;
  mont_mul(k.oneM, k.R2, one, k.N2, k.n0inv, s, k.tmp);
  free(one);
  return ret;
}

String ciphertextB64(PaillierKey& k, const mbedtls_mpi& c) {
  size_t len = mbedtls_mpi_size(&k.n2);
  uint8_t* buf = (uint8_t*)malloc(len);
  mbedtls_mpi_write_binary(&c, buf, len);
  String s = base64(buf, len);
  free(buf);
  return s;
}

// One update encrypted, with one path, plain or packed
void paillierCase(PaillierKey& k, bool hardware, bool packed) {
  String tag = "paillier" + String(k.bits) + (packed ? "_packed" : "_6ct") +
               (hardware ? "_mbedtls_hw" : "_software");
  mbedtls_mpi m[VALUES], c[VALUES];
  for (int i = 0; i < VALUES; i++) { mbedtls_mpi_init(&m[i]); mbedtls_mpi_init(&c[i]); }
  int count = 0;
  int ret = plaintexts(k, packed, m, count);
  beginStep();
  for (int i = 0; i < count && ret == 0; i++) {
    ret = hardware ? encryptHardware(k, m[i], c[i]) : encryptSoftware(k, m[i], c[i]);
  }
  endStep(tag, ret);
  if (ret == 0) {
    String msg = "{\"run\":1792900000,\"round\":1,\"key_bits\":" + String(k.bits) + ",\"c\":";
    if (packed) {
      msg += "\"" + ciphertextB64(k, c[0]) + "\"";
    } else {
      msg += "[";
      for (int i = 0; i < count; i++) msg += (i ? ",\"" : "\"") + ciphertextB64(k, c[i]) + "\"";
      msg += "]";
    }
    addMessage(tag, msg + "}");
  }
  for (int i = 0; i < VALUES; i++) { mbedtls_mpi_free(&m[i]); mbedtls_mpi_free(&c[i]); }
}

void paillierBench(int bits, const char* nHex) {
  PaillierKey k;
  beginStep();
  int ret = setupKey(k, bits, nHex);
  endStep("paillier" + String(bits) + "_key_setup_once", ret);
  if (ret != 0) return;
  // mbedTLS computes and caches its own constant RR in the first exp_mod: one call first
  mbedtls_mpi a, b;
  mbedtls_mpi_init(&a); mbedtls_mpi_init(&b);
  mbedtls_mpi_lset(&a, 3);
  beginStep();
  ret = mbedtls_mpi_exp_mod(&b, &a, &k.n, &k.n2, &k.RR);
  endStep("paillier" + String(bits) + "_mbedtls_first_exp_mod", ret);
  mbedtls_mpi_free(&a); mbedtls_mpi_free(&b);
  for (bool packed : {false, true}) {
    paillierCase(k, true, packed);
    paillierCase(k, false, packed);
  }
}

// ----------------------------------------------------------------------
// The plain FedAvg update, built exactly as in src/fl/main.cpp
// ----------------------------------------------------------------------
void fedavgMessage() {
  JsonDocument doc;
  doc["run"] = 1792900000UL;
  doc["round"] = 1;
  JsonArray weights = doc["weights"].to<JsonArray>();
  const float w[5] = {0.1234567f, -0.3456789f, 0.5678912f, -0.7891234f, 0.9012345f};
  for (int i = 0; i < 5; i++) weights.add(w[i]);
  doc["num_samples"] = NUM_SAMPLES;
  doc["loss"] = 0.0123456f;
  doc["loss_before"] = 0.0456789f;
  char payload[384];
  serializeJson(doc, payload, sizeof(payload));
  addMessage("fedavg_update", payload);
}

// ----------------------------------------------------------------------
// Arduino entry points
// ----------------------------------------------------------------------
enum Phase { CONNECTING, MEASURING, PUBLISHING, DONE };
Phase phase = CONNECTING;
unsigned long lastSummary = 0;

void onConnect() {
  mqtt.publish((topicBase + "status").c_str(), "online");
  Serial.println("[bench] MQTT connected");
}

void printSummary() {
  Serial.printf("SUMMARY board %s, CPU %u MHz, heap total %u, stack high-water %u bytes\n",
                clientId.c_str(), (unsigned)getCpuFrequencyMhz(),
                heap_caps_get_total_size(MALLOC_CAP_8BIT), uxTaskGetStackHighWaterMark(nullptr));
  for (int i = 0; i < numResults; i++) {
    Result& r = results[i];
    Serial.printf("RESULT %s us=%lld free_before=%u free_after=%u min_free=%u ret=%d\n",
                  r.name.c_str(), (long long)r.us, r.freeBefore, r.freeAfter, r.minDuring, r.ret);
  }
  for (int i = 0; i < numMessages; i++) {
    Serial.printf("MESSAGE %s bytes=%u sent=%s\n", messages[i].name.c_str(),
                  messages[i].payload.length(), messages[i].sent ? "yes" : "NO");
  }
  Serial.println("BENCH DONE");
}

void setup() {
  Serial.begin(115200);
  delay(500);
  clientId = clientIdFromMac();
  topicBase = "bench/" + clientId + "/";
  Serial.printf("\n[boot] secure-aggregation benchmark on %s, free heap %u\n", clientId.c_str(),
                heap_caps_get_free_size(MALLOC_CAP_8BIT));
  mqtt.setBufferSize(16384);   // the biggest message (shares for 50 clients) must fit
  Serial.printf("[boot] MQTT buffer 16384 bytes: %s, free heap %u\n",
                mqtt.getBufferSize() == 16384 ? "allocated" : "FAILED",
                heap_caps_get_free_size(MALLOC_CAP_8BIT));
  fog.begin(WIFI_SSID, WIFI_PASSWORD, clientId + "-bench", BROKER_NAME, BROKER_PORT,
            topicBase + "status", "offline", onConnect);
}

void loop() {
  bool connected = fog.update();
  if (phase == CONNECTING && connected) {
    delay(2000);   // let Wi-Fi settle
    Serial.printf("[bench] start, free heap %u\n", heap_caps_get_free_size(MALLOC_CAP_8BIT));
    phase = MEASURING;
    fedavgMessage();
    maskingSetup();
    maskingRound(7);
    maskingRound(50);
    paillierBench(2048, PAILLIER_N_2048);
    paillierBench(3072, PAILLIER_N_3072);
    phase = PUBLISHING;
    Serial.println("[bench] measuring done, publishing the messages");
  } else if (phase == PUBLISHING && connected) {
    static int attempts = 0;
    for (int i = 0; i < numMessages && mqtt.connected(); i++) {
      if (!messages[i].sent) {
        messages[i].sent = mqtt.publish((topicBase + messages[i].name).c_str(),
                                        messages[i].payload.c_str());
        Serial.printf("[bench] published %s (%u bytes): %s\n", messages[i].name.c_str(),
                      messages[i].payload.length(), messages[i].sent ? "ok" : "FAILED");
        mqtt.loop();
        delay(200);
      }
    }
    // The connection is usually gone after the long measurements: count what
    // was really sent, and try the rest again after the reconnect
    bool all = true;
    for (int i = 0; i < numMessages; i++) all = all && messages[i].sent;
    if (!all && ++attempts < 20) {
      delay(1000);
      return;
    }
    phase = DONE;
    printSummary();
    lastSummary = millis();
  } else if (phase == DONE && millis() - lastSummary > 30000) {
    printSummary();
    lastSummary = millis();
  }
}
