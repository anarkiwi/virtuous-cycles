#include <algorithm>
#include <vector>

constexpr int kS = 5;
struct View {
  const float *pn[kS] = {};
  int n = 0;
};
struct Dwell {
  const float *pn[kS];
  int n;
};
Dwell ptr_array_copy(const View &v) {
  Dwell d;
  for (int s = 0; s < kS; ++s)
    d.pn[s] = v.pn[s];
  d.n = v.n;
  return d;
}
void int_array_copy(const int *src, int *dst) {
  for (int s = 0; s < kS; ++s)
    dst[s] = src[s];
}
float outer_const_inner_min(const float *s, int n) {
  float part[128];
  const int len = (n + 127) / 128;
  for (int p = 0; p < 128; ++p) {
    const int a = p * len, b = a + len;
    float sum = 0.0f;
    for (int i = a; i < b; ++i)
      sum += s[i];
    part[p] = sum;
  }
  return part[0];
}
float outer_const_inner_div(const float *s, int n) {
  float acc = 0;
  const int len = (n + 127) / 128;
  for (int p = 0; p < 128; ++p)
    for (int i = 0; i < len; ++i)
      acc += s[p * len + i];
  return acc;
}
float outer_const_inner_stride(const float *x, long lo, long hi) {
  std::vector<float> re(1024, 0.0f);
  for (int t = 0; t < 1024; ++t)
    for (long i = lo + t; i < hi; i += 1024)
      re[(size_t)t] += x[i];
  return re[0];
}
