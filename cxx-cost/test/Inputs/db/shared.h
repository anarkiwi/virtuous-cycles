#pragma once

struct Base {
  virtual ~Base() = default;
  virtual int work() const = 0;
};

int across(int X);
inline int twice(int X) { return 2 * X; }
