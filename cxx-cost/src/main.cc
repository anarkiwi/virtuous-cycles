// vc-cxx-cost: the worst-case operation count of C++ entry points as a
// polynomial in declared capacities, with a ledger of what has no bound.
#include "extract.h"

#include "clang/AST/ASTConsumer.h"
#include "clang/Frontend/CompilerInstance.h"
#include "clang/Frontend/FrontendAction.h"
#include "clang/Frontend/TextDiagnosticPrinter.h"
#include "clang/Tooling/ArgumentsAdjusters.h"
#include "clang/Tooling/CommonOptionsParser.h"
#include "clang/Tooling/Tooling.h"
#include "llvm/Support/CommandLine.h"
#include "llvm/Support/FileSystem.h"
#include "llvm/Support/MemoryBuffer.h"
#include "llvm/Support/Path.h"
#include "llvm/Support/Regex.h"
#include "llvm/Support/ThreadPool.h"
#include "llvm/Support/Threading.h"

#include <chrono>
#include <fstream>
#include <iostream>
#include <mutex>

using namespace clang;
using namespace clang::tooling;
namespace cl = llvm::cl;

static cl::OptionCategory Category("vc-cxx-cost options");
static cl::list<std::string>
    Entries("entry", cl::desc("Entry-point glob over qualified names; repeat"),
            cl::OneOrMore, cl::cat(Category));
static cl::opt<std::string> Output("o", cl::desc("Report path (- for stdout)"),
                                   cl::init("-"), cl::cat(Category));
static cl::opt<std::string>
    Root("root", cl::desc("Directory that report paths are made relative to"),
         cl::cat(Category));
static cl::opt<std::string>
    Filter("files",
           cl::desc("With no sources, analyse the database's files matching "
                    "this regex"),
           cl::init(".*"), cl::cat(Category));
static cl::opt<std::string>
    Drop("drop-arg", cl::desc("Remove compiler arguments matching this regex"),
         cl::cat(Category));
static cl::opt<std::string>
    Models("models",
           cl::desc("JSON models of system functions, tried before the "
                    "built-in ones"),
           cl::cat(Category));
static cl::opt<std::string>
    Weights("weights",
            cl::desc("JSON {\"statement\": X, \"condition\": Y, \"call\": Z}: "
                     "what each kind of operation costs (default 1)"),
            cl::cat(Category));
static cl::opt<std::string> Tolerate(
    "tolerate-errors-in",
    cl::desc("Do not fail on compile errors in files matching this regex "
             "(third-party headers this clang rejects)"),
    cl::cat(Category));
static cl::opt<bool>
    Breakdown("breakdown",
              cl::desc("Report the cost of every function an entry reaches"),
              cl::init(false), cl::cat(Category));
static cl::opt<std::string>
    EmitIr("emit-ir",
           cl::desc("Write the merged per-function summaries, before "
                    "composition, to this path"),
           cl::cat(Category));
static cl::opt<unsigned> Jobs("j", cl::desc("Parallel translation units"),
                              cl::init(0), cl::cat(Category));

namespace {

/// Prints every diagnostic but counts as errors only those outside the files
/// `Ignore` matches, so a translation unit whose only errors are in them is
/// not a failure.
class Tolerant : public DiagnosticConsumer {
public:
  explicit Tolerant(const llvm::Regex &Ignore)
      : Ignore(Ignore), Printer(llvm::errs(), Opts.get()) {}
  void BeginSourceFile(const LangOptions &L, const Preprocessor *P) override {
    Printer.BeginSourceFile(L, P);
  }
  void EndSourceFile() override { Printer.EndSourceFile(); }
  void finish() override { Printer.finish(); }
  void HandleDiagnostic(DiagnosticsEngine::Level Level,
                        const Diagnostic &Info) override {
    Printer.HandleDiagnostic(Level, Info);
    bool Skip = false;
    if (Level >= DiagnosticsEngine::Error && Info.hasSourceManager() &&
        Info.getLocation().isValid()) {
      const SourceManager &SM = Info.getSourceManager();
      Skip =
          Ignore.match(SM.getFilename(SM.getExpansionLoc(Info.getLocation())));
    }
    if (!Skip)
      DiagnosticConsumer::HandleDiagnostic(Level, Info);
  }

private:
  const llvm::Regex &Ignore;
  llvm::IntrusiveRefCntPtr<DiagnosticOptions> Opts{new DiagnosticOptions};
  TextDiagnosticPrinter Printer;
};

class Consumer : public ASTConsumer {
public:
  Consumer(const vc::Options &O, vc::Program &P) : Opt(O), Out(P) {}
  void HandleTranslationUnit(ASTContext &Ctx) override {
    vc::extract(Ctx, Opt, Out);
  }

private:
  const vc::Options &Opt;
  vc::Program &Out;
};

class Action : public ASTFrontendAction {
public:
  Action(const vc::Options &O, vc::Program &P) : Opt(O), Out(P) {}
  std::unique_ptr<ASTConsumer> CreateASTConsumer(CompilerInstance &,
                                                 llvm::StringRef) override {
    return std::make_unique<Consumer>(Opt, Out);
  }

private:
  const vc::Options &Opt;
  vc::Program &Out;
};

class Factory : public FrontendActionFactory {
public:
  Factory(const vc::Options &O, vc::Program &P) : Opt(O), Out(P) {}
  std::unique_ptr<FrontendAction> create() override {
    return std::make_unique<Action>(Opt, Out);
  }

private:
  const vc::Options &Opt;
  vc::Program &Out;
};

} // namespace

int main(int Argc, const char **Argv) {
  auto Parsed = CommonOptionsParser::create(
      Argc, Argv, Category, cl::ZeroOrMore, "C++ worst-case cost analysis");
  if (!Parsed) {
    llvm::errs() << toString(Parsed.takeError()) << "\n";
    return 2;
  }
  if (Parsed->getSourcePathList().empty()) {
    // With no sources the parser loads no database: list the files of the
    // one `-p` names and parse again with them.
    const auto *Build =
        static_cast<cl::opt<std::string> *>(cl::getRegisteredOptions()["p"]);
    std::string Error;
    auto All = CompilationDatabase::autoDetectFromDirectory(
        Build ? Build->getValue() : "", Error);
    if (!All) {
      llvm::errs() << "vc-cxx-cost: " << Error << "\n";
      return 2;
    }
    std::vector<std::string> Listed;
    llvm::Regex Re(Filter);
    for (const std::string &F : All->getAllFiles())
      if (Re.match(F))
        Listed.push_back(F);
    std::vector<const char *> Args(Argv, Argv + Argc);
    for (const std::string &F : Listed)
      Args.push_back(F.c_str());
    cl::ResetAllOptionOccurrences();
    int N = Args.size();
    Parsed =
        CommonOptionsParser::create(N, Args.data(), Category, cl::ZeroOrMore);
    if (!Parsed) {
      llvm::errs() << toString(Parsed.takeError()) << "\n";
      return 2;
    }
  }
  CompilationDatabase &Db = Parsed->getCompilations();
  std::vector<std::string> Files = Parsed->getSourcePathList();

  vc::Options Opt;
  if (!Root.empty()) {
    // Absolute, so `--root .` strips the checkout's path from what clang
    // reports (which is always absolute).
    llvm::SmallString<256> R(Root);
    llvm::sys::fs::make_absolute(R);
    llvm::sys::path::remove_dots(R, true);
    while (R.size() > 1 && R.ends_with("/"))
      R.pop_back();
    Opt.Root = R.str().str();
  }
  if (!Weights.empty()) {
    auto Buf = llvm::MemoryBuffer::getFile(Weights);
    std::string Error;
    if (Buf)
      Opt.W = vc::parseWeights((*Buf)->getBuffer().str(), Error);
    if (!Buf || !Error.empty()) {
      llvm::errs() << "vc-cxx-cost: " << Weights << ": "
                   << (Buf ? Error : Buf.getError().message()) << "\n";
      return 2;
    }
  }
  if (!Models.empty()) {
    auto Buf = llvm::MemoryBuffer::getFile(Models);
    std::string Error;
    if (Buf)
      Opt.Models = vc::parseModels((*Buf)->getBuffer().str(), Error);
    if (!Buf || !Error.empty()) {
      llvm::errs() << "vc-cxx-cost: " << Models << ": "
                   << (Buf ? Error : Buf.getError().message()) << "\n";
      return 2;
    }
  }
  for (vc::Model &M : vc::builtinModels())
    Opt.Models.push_back(std::move(M));

  ArgumentsAdjuster Adjust = combineAdjusters(
      getClangStripOutputAdjuster(),
      getInsertArgumentAdjuster({"-w", "-Wno-unknown-warning-option"},
                                ArgumentInsertPosition::END));
  if (!Drop.empty()) {
    auto Re = std::make_shared<llvm::Regex>(Drop);
    Adjust = combineAdjusters(
        Adjust, [Re](const CommandLineArguments &Args, llvm::StringRef) {
          CommandLineArguments Out;
          for (const std::string &A : Args)
            if (!Re->match(A))
              Out.push_back(A);
          return Out;
        });
  }

  llvm::Regex Ignore(Tolerate);
  if (!Tolerate.empty()) {
    std::string Error;
    if (!Ignore.isValid(Error)) {
      llvm::errs() << "vc-cxx-cost: --tolerate-errors-in: " << Error << "\n";
      return 2;
    }
    // clang stops a translation unit after 19 errors by default.
    Adjust = combineAdjusters(
        Adjust, getInsertArgumentAdjuster("-ferror-limit=0",
                                          ArgumentInsertPosition::END));
  }

  vc::Program Program;
  std::mutex Lock;
  std::vector<std::string> Failed;
  size_t Done = 0;
  auto Start = std::chrono::steady_clock::now();
  {
    llvm::DefaultThreadPool Pool(llvm::hardware_concurrency(Jobs));
    for (const std::string &File : Files)
      Pool.async([&, File] {
        vc::Program Local;
        ClangTool Tool(Db, {File});
        Tool.appendArgumentsAdjuster(Adjust);
        std::unique_ptr<Tolerant> Quiet;
        if (!Tolerate.empty()) {
          Quiet = std::make_unique<Tolerant>(Ignore);
          Tool.setDiagnosticConsumer(Quiet.get());
        }
        Factory F(Opt, Local);
        int Rc = Tool.run(&F);
        std::lock_guard<std::mutex> G(Lock);
        if (Rc)
          Failed.push_back(File);
        Program.merge(std::move(Local));
        ++Done;
        double S = std::chrono::duration<double>(
                       std::chrono::steady_clock::now() - Start)
                       .count();
        llvm::errs() << llvm::format("[%zu/%zu %.1fs %.2f TU/s] ", Done,
                                     Files.size(), S, Done / std::max(S, 1e-9))
                     << File << "\n";
      });
    Pool.wait();
  }

  std::string Error;
  std::vector<std::string> Patterns(Entries.begin(), Entries.end());
  if (!EmitIr.empty()) {
    std::ofstream OS(EmitIr);
    vc::writeIr(OS, Program, Patterns, Breakdown);
  }
  std::vector<vc::Entry> Result = Program.resolve(Patterns, Error, Breakdown);
  if (!Error.empty()) {
    llvm::errs() << "vc-cxx-cost: " << Error << "\n";
    return 2;
  }
  if (Output == "-") {
    vc::writeJson(std::cout, Program, Result);
  } else {
    std::ofstream OS(Output);
    vc::writeJson(OS, Program, Result);
  }
  for (const std::string &F : Failed)
    llvm::errs() << "vc-cxx-cost: " << F << " did not compile\n";
  return Failed.empty() ? 0 : 2;
}
