#include <algorithm>
#include <cstddef>

extern "C" void __infer_assume(bool);
extern void opaque(int);

constexpr int kCap = 64;
template <class T, int Cap> struct Fixed {
  T v[Cap];
  int n = 0;
  int size() const {
    __infer_assume(n >= 0 && n <= Cap);
    return n;
  }
};

float min_assumed(const float *s, int a, int b, int n) {
  const int lo = std::max(0, a), hi = std::min(n, b);
  __infer_assume(lo >= 0 && hi <= n);
  float acc = 0;
  for (int i = lo; i < hi; ++i)
    acc += s[i];
  return acc;
}
float min_capped(const float *s, int a, int b) {
  const int lo = std::max(0, a), hi = std::min(kCap, b);
  __infer_assume(lo >= 0 && hi <= kCap);
  float acc = 0;
  for (int i = lo; i < hi; ++i)
    acc += s[i];
  return acc;
}
float fixed_pairs(const Fixed<float, kCap> &f) {
  float acc = 0;
  for (int i = 0; i < f.size(); ++i)
    for (int j = i + 1; j < f.size(); ++j)
      acc += f.v[i] * f.v[j];
  return acc;
}
int fixed_restart(Fixed<int, kCap> &f) {
  int changed = 0;
  for (bool again = true; again;) {
    again = false;
    for (int i = 0; i < f.size() && !again; ++i)
      for (int j = i + 1; j < f.size() && !again; ++j)
        if (f.v[i] == f.v[j]) {
          f.v[j] = f.v[--f.n];
          ++changed;
          again = true;
        }
  }
  return changed;
}
int restart_counted(Fixed<int, kCap> &f) {
  int changed = 0;
  for (int round = 0; round < kCap; ++round) {
    bool again = false;
    for (int i = 0; i < f.size() && !again; ++i)
      for (int j = i + 1; j < f.size() && !again; ++j)
        if (f.v[i] == f.v[j]) {
          f.v[j] = f.v[--f.n];
          ++changed;
          again = true;
        }
    if (!again)
      break;
  }
  return changed;
}
void unknown_in_loop(int n) {
  for (int i = 0; i < n; ++i)
    opaque(i);
}
struct Arm {
  virtual ~Arm() = default;
  virtual float work(const float *s, int n) const = 0;
};
struct HostArm : Arm {
  float work(const float *s, int n) const override {
    float a = 0;
    for (int i = 0; i < n; ++i)
      for (int j = 0; j < n; ++j)
        a += s[i] * s[j];
    return a;
  }
};
float via_virtual(const Arm &a, const float *s, int n) { return a.work(s, n); }
float direct(const HostArm &a, const float *s, int n) { return a.work(s, n); }
