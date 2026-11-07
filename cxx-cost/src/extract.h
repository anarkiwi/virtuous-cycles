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

struct Options {
  std::string Root;
  std::vector<Model> Models;
};

void extract(clang::ASTContext &Ctx, const Options &Opt, Program &Out);

} // namespace vc

#endif
