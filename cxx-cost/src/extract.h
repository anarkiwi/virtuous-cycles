// The cost summaries of one translation unit's function definitions.
#ifndef VC_EXTRACT_H
#define VC_EXTRACT_H

#include "program.h"

#include "llvm/Support/GlobPattern.h"

#include <memory>
#include <string>
#include <vector>

namespace clang {
class ASTContext;
}

namespace vc {

/// How a call into a system header is costed.
struct Model {
  enum Kind {
    Const,     ///< one operation
    Linear,    ///< the size of argument `Arg` (the object when -1)
    LinearLog, ///< that size times its log2
    Log,       ///< log2 of that size
    Indirect,  ///< an indirect call: unbounded
    Opaque     ///< not modelled: unbounded
  } K = Opaque;
  int Arg = 0;
  /// Calls with fewer arguments are not this model's (`std::move(x)` is not
  /// the algorithm).
  unsigned MinArgs = 0;
  /// The glob's text, which `Match` refers into.
  std::shared_ptr<const std::string> Pattern;
  llvm::GlobPattern Match;
  static llvm::Expected<Model> create(Kind K, int Arg, std::string Glob);
};

/// The built-in models: the standard library's algorithms and containers,
/// libc's string and math functions. Anything else in a system header is
/// opaque.
std::vector<Model> builtinModels();
/// Parse `[{"match": GLOB, "cost": KIND, "arg": N}]`; `Error` on failure.
std::vector<Model> parseModels(const std::string &Json, std::string &Error);

/// What one operation costs, by kind (the default is 1 for each).
struct Weights {
  double Statement = 1; ///< an expression, declaration or return
  double Condition = 1; ///< an if/loop/switch test, a loop step
  double Call = 1;      ///< a function entered, a modelled call's overhead
};

struct Options {
  Weights W;
  std::string Root;
  std::vector<Model> Models;
};

/// Parse `{"statement": X, "condition": Y, "call": Z}`; `Error` on failure.
Weights parseWeights(const std::string &Json, std::string &Error);

void extract(clang::ASTContext &Ctx, const Options &Opt, Program &Out);

} // namespace vc

#endif
