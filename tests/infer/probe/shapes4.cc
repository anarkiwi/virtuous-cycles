#include <algorithm>
extern "C" void __infer_assume(bool);
float assume_upper(const float *s, int n) {
  __infer_assume(n <= 10);
  float a = 0;
  for (int i = 0; i < n; ++i)
    a += s[i];
  return a;
}
float min_break(const float *s, int b, int n) {
  float a = 0;
  for (int i = 0; i < n; ++i) {
    if (i >= b)
      break;
    a += s[i];
  }
  return a;
}
float min_capconst(const float *s, int b) {
  const int hi = std::min(b, 64);
  float a = 0;
  for (int i = 0; i < hi; ++i)
    a += s[i];
  return a;
}
float div_bound(const float *s, int n) {
  const int len = n / 128;
  float a = 0;
  for (int i = 0; i < len; ++i)
    a += s[i];
  return a;
}
