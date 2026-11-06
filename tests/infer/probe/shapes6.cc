#include <vector>
constexpr int kCap = 64;
template <class T, int Cap> struct Fixed {
  T v[Cap];
  int n = 0;
  bool push(const T &x) {
    if (n >= Cap)
      return false;
    v[n++] = x;
    return true;
  }
  int size() const { return n < 0 ? 0 : (n > Cap ? Cap : n); }
  int count() const { return n; }
};
void produce(const float *s, int m, Fixed<int, kCap> *out) {
  out->n = 0;
  for (int i = 0; i < m; ++i)
    if (s[i] > 0)
      out->push(i);
}
float consume_count(const float *s, int m) {
  Fixed<int, kCap> f;
  produce(s, m, &f);
  float a = 0;
  for (int i = 0; i < f.count(); ++i)
    for (int j = 0; j < f.count(); ++j)
      a += s[f.v[i]] * s[f.v[j]];
  return a;
}
float consume_size(const float *s, int m) {
  Fixed<int, kCap> f;
  produce(s, m, &f);
  float a = 0;
  for (int i = 0; i < f.size(); ++i)
    a += s[f.v[i]];
  return a;
}
float consume_cap_loop(const float *s, int m) {
  Fixed<int, kCap> f;
  produce(s, m, &f);
  float a = 0;
  for (int i = 0; i < kCap; ++i) {
    if (i >= f.n)
      break;
    a += s[f.v[i]];
  }
  return a;
}
void produce_vec(const float *s, int m, std::vector<int> *out) {
  out->clear();
  for (int i = 0; i < m; ++i)
    if (s[i] > 0)
      out->push_back(i);
}
float consume_vec(const float *s, int m) {
  std::vector<int> v;
  produce_vec(s, m, &v);
  float a = 0;
  for (int x : v)
    a += s[x];
  return a;
}
