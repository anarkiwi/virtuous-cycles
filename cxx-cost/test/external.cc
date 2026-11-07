// Calls with no analysed body are unbounded, never free: a declaration
// defined elsewhere, a call through a pointer, std::function, and a system
// function with no model. A models file can cost them.
// RUN: %cost --entry 'outside' %s %flags | FileCheck %s
// RUN: echo '[{"match": "getpid", "cost": "const"}, {"match": \
// RUN:   "std::function::operator()", "cost": "linear", "arg": 0}]' > %t.json
// RUN: %cost --models %t.json --entry 'outside' %s %flags | FileCheck \
// RUN:   --check-prefix=MODEL %s
// CHECK-LABEL: "outside":
// CHECK: "polynomial": "4*? + 2"
// CHECK: "reason": "call to elsewhere whose body is not analysed"
// CHECK: "reason": "call through a pointer"
// CHECK: "reason": "call through std::function::operator()"
// CHECK: "reason": "call to getpid, which has no model"
// MODEL: "polynomial": "2*? + 7"
// MODEL-NOT: getpid
// MODEL-NOT: std::function
#include <functional>
#include <unistd.h>

int elsewhere(int);

int outside(int (*F)(int), const std::function<int(int)> &G) {
  return elsewhere(1) + F(2) + G(3) + getpid();
}
