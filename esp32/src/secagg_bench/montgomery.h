// Montgomery modular arithmetic in plain C, for numbers of any size.
//
// The ESP32's big-number hardware (used by mbedTLS) takes moduli up to 4096
// bits. Paillier with a 3072-bit key works modulo n^2, 6144 bits, so this is
// the software path: 32-bit limbs (least significant first), the CIOS method
// (Koc, Acar and Kaliski 1996). It is also run for 2048-bit keys, to compare
// with the hardware path.
//
// Montgomery form of a number a modulo N (N odd, s limbs) is a*R mod N with
// R = 2^(32*s). mont_mul(a, b) returns a*b/R mod N, so products stay in
// Montgomery form without any division.
#pragma once

#include <stdint.h>
#include <string.h>

// -N^-1 mod 2^32, from the lowest limb of N (Newton's method; N is odd)
static inline uint32_t mont_n0inv(uint32_t n0) {
  uint32_t inv = 1;
  for (int i = 0; i < 5; i++) {
    inv *= 2 - n0 * inv;   // each step doubles the correct low bits
  }
  return (uint32_t)(0 - inv);
}

// r = a * b / R mod N. a, b < N. t: scratch of s + 2 limbs. r may equal a or b.
static inline void mont_mul(uint32_t* r, const uint32_t* a, const uint32_t* b,
                            const uint32_t* N, uint32_t n0inv, int s, uint32_t* t) {
  memset(t, 0, (s + 2) * sizeof(uint32_t));
  for (int i = 0; i < s; i++) {
    // t += a * b[i]
    uint64_t carry = 0;
    for (int j = 0; j < s; j++) {
      uint64_t sum = (uint64_t)t[j] + (uint64_t)a[j] * b[i] + carry;
      t[j] = (uint32_t)sum;
      carry = sum >> 32;
    }
    uint64_t sum = (uint64_t)t[s] + carry;
    t[s] = (uint32_t)sum;
    t[s + 1] = (uint32_t)(sum >> 32);

    // t = (t + m * N) / 2^32, with m chosen so the lowest limb becomes 0
    uint32_t m = t[0] * n0inv;
    sum = (uint64_t)t[0] + (uint64_t)m * N[0];
    carry = sum >> 32;
    for (int j = 1; j < s; j++) {
      sum = (uint64_t)t[j] + (uint64_t)m * N[j] + carry;
      t[j - 1] = (uint32_t)sum;
      carry = sum >> 32;
    }
    sum = (uint64_t)t[s] + carry;
    t[s - 1] = (uint32_t)sum;
    t[s] = t[s + 1] + (uint32_t)(sum >> 32);
  }

  // The result is below 2N: subtract N once if it is N or more
  bool subtract = t[s] != 0;
  if (!subtract) {
    subtract = true;   // equal counts as "N or more"
    for (int j = s - 1; j >= 0; j--) {
      if (t[j] != N[j]) {
        subtract = t[j] > N[j];
        break;
      }
    }
  }
  if (subtract) {
    uint64_t borrow = 0;
    for (int j = 0; j < s; j++) {
      uint64_t diff = (uint64_t)t[j] - N[j] - borrow;
      t[j] = (uint32_t)diff;
      borrow = (diff >> 32) & 1;
    }
  }
  memcpy(r, t, s * sizeof(uint32_t));
}

// x = base^e / R^(e-1) mod N, i.e. Montgomery form in, Montgomery form out.
// one_m: R mod N (1 in Montgomery form). e: exponent limbs, e_bits long.
// tmp: scratch of s + 2 limbs. Left-to-right square and multiply.
static inline void mont_exp(uint32_t* x, const uint32_t* base_m, const uint32_t* e, int e_bits,
                            const uint32_t* one_m, const uint32_t* N, uint32_t n0inv, int s,
                            uint32_t* tmp) {
  memcpy(x, one_m, s * sizeof(uint32_t));
  for (int bit = e_bits - 1; bit >= 0; bit--) {
    mont_mul(x, x, x, N, n0inv, s, tmp);
    if ((e[bit / 32] >> (bit % 32)) & 1) {
      mont_mul(x, x, base_m, N, n0inv, s, tmp);
    }
  }
}
