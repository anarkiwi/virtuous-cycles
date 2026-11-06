#include <memory>
#include <vector>
struct Mirror {
  std::vector<float> read;
};
struct Impl {
  Mirror mirror;
  int T = 0;
};
struct Det {
  std::unique_ptr<Impl> impl_;
  Impl *raw_ = nullptr;
  Impl inl_;
  float via_unique() const;
  float via_raw() const;
  float via_member() const;
  float int_via_unique(const float *s) const;
};
float Det::via_unique() const {
  float a = 0;
  for (float v : impl_->mirror.read)
    a += v;
  return a;
}
float Det::via_raw() const {
  float a = 0;
  for (float v : raw_->mirror.read)
    a += v;
  return a;
}
float Det::via_member() const {
  float a = 0;
  for (float v : inl_.mirror.read)
    a += v;
  return a;
}
float Det::int_via_unique(const float *s) const {
  float a = 0;
  for (int i = 0; i < impl_->T; ++i)
    a += s[i];
  return a;
}
