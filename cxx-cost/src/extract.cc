#include "extract.h"

#include "clang/AST/ASTContext.h"
#include "clang/AST/Attr.h"
#include "clang/AST/ExprCXX.h"
#include "clang/AST/RecursiveASTVisitor.h"
#include "clang/AST/StmtCXX.h"
#include "clang/Basic/SourceManager.h"
#include "clang/Index/USRGeneration.h"
#include "clang/Lex/Lexer.h"
#include "llvm/Support/JSON.h"
#include "llvm/Support/Path.h"

#include <cmath>
#include <set>

using namespace clang;

namespace vc {

namespace {

const char *const RangeAlgorithms =
    "std::{fill,copy,copy_if,copy_backward,move,move_backward,transform,"
    "accumulate,reduce,transform_reduce,inner_product,partial_sum,"
    "exclusive_scan,inclusive_scan,adjacent_difference,iota,find,find_if,"
    "find_if_not,find_end,find_first_of,adjacent_find,count,count_if,all_of,"
    "any_of,none_of,for_each,min_element,max_element,minmax_element,remove,"
    "remove_if,remove_copy,remove_copy_if,unique,unique_copy,reverse,"
    "reverse_copy,rotate,equal,mismatch,search,is_sorted,is_sorted_until,"
    "replace,replace_if,partition,stable_partition,is_partitioned,nth_element,"
    "merge,inplace_merge,set_union,set_intersection,set_difference,includes,"
    "lexicographical_compare,make_heap,shuffle,generate,uninitialized_copy,"
    "uninitialized_fill,destroy,distance}";

const char *const MathFunctions =
    "{sqrt,cbrt,exp,exp2,expm1,log,log2,log10,log1p,pow,sin,cos,tan,asin,acos,"
    "atan,atan2,sinh,cosh,tanh,erf,erfc,lgamma,tgamma,fabs,floor,ceil,round,"
    "lround,llround,lrint,llrint,trunc,fmod,remainder,hypot,fmin,fmax,fma,"
    "copysign,"
    "nearbyint,rint,ldexp,frexp,modf,abs,labs,llabs,isnan,isinf,"
    "isfinite,signbit,nan}{,f,l}";

Model model(Model::Kind K, int Arg, const char *Glob, unsigned MinArgs = 0) {
  Model M = cantFail(Model::create(K, Arg, Glob));
  M.MinArgs = MinArgs;
  return M;
}

std::string text(const AnnotateAttr *A) {
  if (A->args_size() == 0)
    return "";
  if (auto *S =
          dyn_cast<StringLiteral>((*A->args_begin())->IgnoreParenImpCasts()))
    return S->getString().str();
  return "";
}

/// The text of the annotation `Tag` on `D` or any of its redeclarations.
std::optional<std::string> annotation(const Decl *D, llvm::StringRef Tag) {
  if (!D)
    return std::nullopt;
  for (const Decl *R : D->redecls())
    for (const auto *A : R->specific_attrs<AnnotateAttr>())
      if (A->getAnnotation() == Tag)
        return text(A);
  if (const auto *P = dyn_cast<ParmVarDecl>(D))
    if (const auto *F = dyn_cast<FunctionDecl>(P->getDeclContext()))
      for (const FunctionDecl *R : F->redecls())
        if (P->getFunctionScopeIndex() < R->getNumParams())
          for (const auto *A : R->getParamDecl(P->getFunctionScopeIndex())
                                   ->specific_attrs<AnnotateAttr>())
            if (A->getAnnotation() == Tag)
              return text(A);
  return std::nullopt;
}

/// `ns::Class::name`, with no template arguments and no inline namespaces.
std::string plain(const NamedDecl *D) {
  std::vector<std::string> Parts;
  for (const DeclContext *C = D->getDeclContext(); C; C = C->getParent()) {
    if (const auto *N = dyn_cast<NamespaceDecl>(C)) {
      if (!N->isInline())
        Parts.push_back(N->isAnonymousNamespace() ? "(anonymous namespace)"
                                                  : N->getName().str());
    } else if (const auto *R = dyn_cast<RecordDecl>(C)) {
      Parts.push_back(R->getName().empty() ? "(anonymous)"
                                           : R->getName().str());
    } else if (const auto *F = dyn_cast<FunctionDecl>(C)) {
      Parts.push_back(F->getNameAsString());
    }
  }
  std::string Out;
  for (auto It = Parts.rbegin(); It != Parts.rend(); ++It)
    Out += *It + "::";
  return Out + D->getNameAsString();
}

class Extractor {
public:
  Extractor(ASTContext &C, const Options &O, Program &P)
      : Ctx(C), SM(C.getSourceManager()), Opt(O), Out(P) {}

  void function(const FunctionDecl *FD);
  void method(const CXXMethodDecl *MD);
  void constant(const VarDecl *VD);
  /// Name the capacity of a container type written in a declaration.
  void declare(QualType T) {
    Function *Saved = Cur;
    Cur = nullptr;
    capacity(T);
    Cur = Saved;
  }
  void finish() {
    for (const std::string &S : Mentioned)
      if (S != Unbounded && !llvm::StringRef(S).starts_with("log2("))
        Out.symbol(S, Known.count(S) ? std::optional<double>(Known[S])
                                     : std::nullopt);
  }
  bool system(const Decl *D) const {
    SourceLocation L = D->getLocation();
    return L.isInvalid() || SM.isInSystemHeader(SM.getExpansionLoc(L));
  }

private:
  Site site(SourceLocation L) const;
  std::string usr(const Decl *D) const;
  /// The source text of `S`, whitespace collapsed, in backquotes.
  std::string source(const Stmt *S) const;
  std::string name(const FunctionDecl *FD) const;
  CostRef unbounded(llvm::StringRef Kind, std::string Reason, SourceLocation L);
  std::optional<Poly> annotated(const Decl *D, llvm::StringRef Tag,
                                SourceLocation L);
  std::optional<Poly> parsed(const std::string &Text, SourceLocation L);

  CostRef stmt(const Stmt *S, std::optional<Poly> Bound = std::nullopt);
  CostRef expr(const Stmt *S);
  CostRef loop(const Stmt *S, std::optional<Poly> Bound,
               std::optional<Poly> Inferred, const std::string &Why,
               CostRef Once, CostRef Each);
  CostRef call(const FunctionDecl *FD, const Expr *Site, const Expr *Object,
               llvm::ArrayRef<const Expr *> Args);
  CostRef callable(llvm::ArrayRef<const Expr *> Args);
  CostRef target(const FunctionDecl *FD, SourceLocation L);

  std::optional<Poly> bound(const Expr *E);
  std::optional<Poly> size(const Expr *E);
  std::optional<Poly> capacity(QualType T);
  std::optional<Poly> amount(const Expr *E);
  std::optional<Poly> trip(const ForStmt *F);
  std::optional<Poly> symbolOf(const VarDecl *VD);

  ASTContext &Ctx;
  SourceManager &SM;
  const Options &Opt;
  Program &Out;
  Function *Cur = nullptr;
  std::map<std::string, double> Known;
  std::set<std::string> Mentioned;
};

Site Extractor::site(SourceLocation L) const {
  PresumedLoc P = SM.getPresumedLoc(SM.getExpansionLoc(L));
  if (P.isInvalid())
    return {};
  llvm::SmallString<256> Path(P.getFilename());
  llvm::sys::path::remove_dots(Path, true);
  llvm::StringRef R(Path);
  if (!Opt.Root.empty() && R.consume_front(Opt.Root))
    R.consume_front("/");
  return {R.str(), P.getLine(), P.getColumn()};
}

std::string Extractor::source(const Stmt *S) const {
  if (!S)
    return "``";
  llvm::StringRef Text = Lexer::getSourceText(
      SM.getExpansionRange(S->getSourceRange()), SM, Ctx.getLangOpts());
  std::string Out;
  for (char C : Text)
    if (!std::isspace((unsigned char)C) || (!Out.empty() && Out.back() != ' '))
      Out += std::isspace((unsigned char)C) ? ' ' : C;
  return "`" + Out + "`";
}

std::string Extractor::usr(const Decl *D) const {
  llvm::SmallString<128> Buf;
  if (index::generateUSRForDecl(D, Buf))
    return "";
  return Buf.str().str();
}

std::string Extractor::name(const FunctionDecl *FD) const {
  if (const auto *MD = dyn_cast<CXXMethodDecl>(FD))
    if (MD->getParent()->isLambda()) {
      PresumedLoc P = SM.getPresumedLoc(SM.getExpansionLoc(MD->getLocation()));
      const auto *Outer = dyn_cast<NamedDecl>(
          Decl::castFromDeclContext(MD->getParent()->getDeclContext()));
      return (Outer ? plain(Outer) + "::" : std::string()) +
             "(lambda:" + std::to_string(P.getLine()) + ":" +
             std::to_string(P.getColumn()) + ")";
    }
  std::string S;
  llvm::raw_string_ostream OS(S);
  PrintingPolicy PP = Ctx.getPrintingPolicy();
  PP.SuppressInlineNamespace = true;
  FD->getNameForDiagnostic(OS, PP, true);
  return S;
}

CostRef Extractor::unbounded(llvm::StringRef Kind, std::string Reason,
                             SourceLocation L) {
  if (Cur)
    Cur->Ledger.push_back({Kind.str(), Cur->Name, std::move(Reason), site(L)});
  return Cost::leaf(Poly::symbol(Unbounded));
}

std::optional<Poly> Extractor::parsed(const std::string &Text,
                                      SourceLocation L) {
  if (auto P = Poly::parse(Text)) {
    for (const auto &[M, C] : P->terms())
      for (const auto &[S, E] : M)
        Mentioned.insert(S);
    if (P->degree(Unbounded))
      unbounded("annotation", "annotated as unbounded: " + Text, L);
    return P;
  }
  unbounded("annotation", "cannot parse \"" + Text + "\"", L);
  return Poly::symbol(Unbounded);
}

std::optional<Poly> Extractor::annotated(const Decl *D, llvm::StringRef Tag,
                                         SourceLocation L) {
  if (auto T = annotation(D, Tag))
    return parsed(*T, L);
  return std::nullopt;
}

void Extractor::constant(const VarDecl *VD) {
  if (!VD->hasGlobalStorage() || VD->isStaticLocal() ||
      !VD->getType()->isIntegralOrEnumerationType() ||
      !(VD->isConstexpr() || VD->getType().isConstQualified()) ||
      !VD->getAnyInitializer() || VD->getType()->isDependentType())
    return;
  if (const APValue *V = VD->evaluateValue(); V && V->isInt()) {
    auto Name = annotation(VD, "vc::symbol");
    std::string S = Name && !Name->empty() ? *Name : VD->getName().str();
    Known[S] = std::max<double>(0, V->getInt().getExtValue());
    if (Name)
      Out.symbol(S, Known[S]);
  }
}

void Extractor::method(const CXXMethodDecl *MD) {
  if (!MD->isVirtual() || system(MD))
    return;
  std::string Me = usr(MD);
  for (const CXXMethodDecl *O : MD->overridden_methods())
    Out.Overriders[usr(O)].insert(Me);
}

void Extractor::function(const FunctionDecl *FD) {
  if (!FD->isThisDeclarationADefinition() || !FD->hasBody() ||
      FD->isDependentContext() || FD->isImplicit() || FD->isDefaulted() ||
      system(FD))
    return;
  std::string U = usr(FD);
  if (U.empty() || Out.Functions.count(U))
    return;
  Function &F = Out.Functions[U];
  F.Name = name(FD);
  F.Plain = plain(FD);
  F.At = site(FD->getLocation());
  Cur = &F;
  if (auto C = annotated(FD, "vc::cost", FD->getLocation())) {
    F.Body = Cost::leaf(*C);
    return;
  }
  F.Recursion = annotated(FD, "vc::recursion", FD->getLocation());
  CostRef Body = Cost::leaf(Poly::constant(1));
  if (const auto *Ctor = dyn_cast<CXXConstructorDecl>(FD))
    for (const CXXCtorInitializer *I : Ctor->inits())
      if (I->isWritten())
        Body = Cost::sum(
            Body, Cost::sum(Cost::leaf(Poly::constant(1)), expr(I->getInit())));
  F.Body = Cost::sum(Body, stmt(FD->getBody()));
  if (F.Loops)
    F.Body = Cost::scale(Poly::symbol(Unbounded), F.Body);
}

CostRef Extractor::loop(const Stmt *S, std::optional<Poly> Bound,
                        std::optional<Poly> Inferred, const std::string &Why,
                        CostRef Once, CostRef Each) {
  Poly T;
  if (Bound)
    T = *Bound;
  else if (Inferred)
    T = *Inferred;
  else
    T = unbounded("loop", Why, S->getBeginLoc())->P;
  return Cost::sum(Once, Cost::scale(T, Each));
}

CostRef Extractor::stmt(const Stmt *S, std::optional<Poly> Bound) {
  auto One = [] { return Cost::leaf(Poly::constant(1)); };
  auto Plus = [](CostRef A, CostRef B) { return Cost::sum(A, B); };
  if (!S)
    return Cost::leaf({});
  if (const auto *A = dyn_cast<AttributedStmt>(S)) {
    for (const Attr *At : A->getAttrs())
      if (const auto *An = dyn_cast<AnnotateAttr>(At)) {
        if (An->getAnnotation() == "vc::cost")
          return Cost::leaf(*parsed(text(An), S->getBeginLoc()));
        if (An->getAnnotation() == "vc::bound")
          Bound = parsed(text(An), S->getBeginLoc());
      }
    const Stmt *Sub = A->getSubStmt();
    if (Bound && !isa<ForStmt, WhileStmt, DoStmt, CXXForRangeStmt>(Sub))
      unbounded("annotation", "a bound on something that is not a loop",
                S->getBeginLoc());
    return stmt(Sub, Bound);
  }
  if (const auto *C = dyn_cast<CompoundStmt>(S)) {
    CostRef R = Cost::leaf({});
    for (const Stmt *K : C->body())
      R = Plus(R, stmt(K));
    return R;
  }
  if (const auto *I = dyn_cast<IfStmt>(S)) {
    CostRef Cond = Plus(One(), expr(I->getCond()));
    if (const VarDecl *V = I->getConditionVariable())
      Cond = Plus(Cond, expr(V->getInit()));
    return Plus(Plus(stmt(I->getInit()), Cond),
                Cost::join(stmt(I->getThen()), stmt(I->getElse())));
  }
  if (const auto *F = dyn_cast<ForStmt>(S)) {
    CostRef Cond =
        F->getCond() ? Plus(One(), expr(F->getCond())) : Cost::leaf({});
    CostRef Inc = F->getInc() ? Plus(One(), expr(F->getInc())) : Cost::leaf({});
    std::optional<Poly> T = Bound ? std::nullopt : trip(F);
    return loop(S, Bound, T,
                "for loop with no bound on " + source(F->getCond()),
                Plus(stmt(F->getInit()), Cond),
                Plus(Plus(Cond, stmt(F->getBody())), Inc));
  }
  if (const auto *W = dyn_cast<WhileStmt>(S)) {
    CostRef Cond = Plus(One(), expr(W->getCond()));
    return loop(S, Bound, std::nullopt,
                "while loop with no bound on " + source(W->getCond()), Cond,
                Plus(Cond, stmt(W->getBody())));
  }
  if (const auto *D = dyn_cast<DoStmt>(S))
    return loop(S, Bound, std::nullopt,
                "do loop with no bound on " + source(D->getCond()),
                Cost::leaf({}),
                Plus(Plus(One(), expr(D->getCond())), stmt(D->getBody())));
  if (const auto *R = dyn_cast<CXXForRangeStmt>(S)) {
    std::optional<Poly> T = Bound ? std::nullopt : size(R->getRangeInit());
    std::string Why = "range over " + source(R->getRangeInit()) + " (" +
                      R->getRangeInit()->getType().getAsString() +
                      "), which has no capacity";
    return loop(S, Bound, T, Why,
                Plus(One(), Plus(stmt(R->getInit()), expr(R->getRangeInit()))),
                Plus(Plus(One(), expr(R->getLoopVariable()->getInit())),
                     stmt(R->getBody())));
  }
  if (const auto *Sw = dyn_cast<SwitchStmt>(S))
    return Plus(Plus(stmt(Sw->getInit()), Plus(One(), expr(Sw->getCond()))),
                stmt(Sw->getBody()));
  if (const auto *C = dyn_cast<SwitchCase>(S))
    return stmt(C->getSubStmt());
  if (const auto *L = dyn_cast<LabelStmt>(S))
    return stmt(L->getSubStmt());
  if (const auto *T = dyn_cast<CXXTryStmt>(S)) {
    CostRef R = stmt(T->getTryBlock());
    for (unsigned I = 0; I < T->getNumHandlers(); ++I)
      R = Plus(R, stmt(T->getHandler(I)->getHandlerBlock()));
    return R;
  }
  if (const auto *G = dyn_cast<GotoStmt>(S)) {
    if (!SM.isBeforeInTranslationUnit(G->getLabel()->getLocation(),
                                      G->getGotoLoc()))
      return One();
    unbounded("loop", "backward goto", G->getGotoLoc());
    Cur->Loops = true;
    return One();
  }
  if (isa<NullStmt>(S))
    return Cost::leaf({});
  if (const auto *D = dyn_cast<DeclStmt>(S)) {
    CostRef R = One();
    for (const Decl *X : D->decls())
      if (const auto *V = dyn_cast<VarDecl>(X))
        R = Plus(R, expr(V->getInit()));
    return R;
  }
  return Plus(One(), expr(S));
}

CostRef Extractor::expr(const Stmt *S) {
  if (!S || isa<LambdaExpr>(S))
    return Cost::leaf({});
  if (const auto *C = dyn_cast<AbstractConditionalOperator>(S))
    return Cost::sum(expr(C->getCond()), Cost::join(expr(C->getTrueExpr()),
                                                    expr(C->getFalseExpr())));
  if (const auto *D = dyn_cast<CXXDefaultArgExpr>(S))
    return expr(D->getExpr());
  if (const auto *D = dyn_cast<CXXDefaultInitExpr>(S))
    return expr(D->getExpr());
  if (const auto *SE = dyn_cast<StmtExpr>(S))
    return stmt(SE->getSubStmt());
  CostRef R = Cost::leaf({});
  for (const Stmt *K : S->children())
    R = Cost::sum(R, expr(K));
  if (const auto *CE = dyn_cast<CallExpr>(S)) {
    llvm::SmallVector<const Expr *, 4> Args(CE->arguments());
    const Expr *Object = nullptr;
    if (const auto *M = dyn_cast<CXXMemberCallExpr>(CE))
      Object = M->getImplicitObjectArgument();
    const FunctionDecl *FD = CE->getDirectCallee();
    if (isa_and_nonnull<CXXMethodDecl>(FD) && isa<CXXOperatorCallExpr>(CE) &&
        !Args.empty()) {
      Object = Args.front();
      Args.erase(Args.begin());
    }
    if (!FD) {
      if (isa<CXXPseudoDestructorExpr>(CE->getCallee()->IgnoreParens()))
        return R;
      return Cost::sum(R, unbounded("indirect", "call through a pointer",
                                    CE->getBeginLoc()));
    }
    return Cost::sum(R, call(FD, CE, Object, Args));
  }
  if (const auto *CE = dyn_cast<CXXConstructExpr>(S)) {
    const CXXConstructorDecl *Ctor = CE->getConstructor();
    if (Ctor->isTrivial())
      return R;
    llvm::SmallVector<const Expr *, 4> Args(CE->arguments());
    return Cost::sum(R, call(Ctor, CE, nullptr, Args));
  }
  return R;
}

CostRef Extractor::target(const FunctionDecl *FD, SourceLocation L) {
  if (auto C = annotated(FD, "vc::cost", L))
    return Cost::leaf(*C);
  if (FD->isDefaulted() || FD->isImplicit())
    return Cost::leaf(Poly::constant(1));
  return Cost::call(usr(FD), plain(FD), site(L));
}

CostRef Extractor::callable(llvm::ArrayRef<const Expr *> Args) {
  CostRef R = Cost::leaf({});
  for (const Expr *A : Args) {
    const Expr *E = A->IgnoreParenImpCasts();
    if (const auto *U = dyn_cast<UnaryOperator>(E))
      if (U->getOpcode() == UO_AddrOf)
        E = U->getSubExpr()->IgnoreParenImpCasts();
    if (const auto *D = dyn_cast<DeclRefExpr>(E))
      if (const auto *F = dyn_cast<FunctionDecl>(D->getDecl())) {
        R = Cost::join(R, target(F, A->getBeginLoc()));
        continue;
      }
    const CXXRecordDecl *RD =
        A->getType().getNonReferenceType()->getAsCXXRecordDecl();
    if (!RD || system(RD) || !RD->hasDefinition())
      continue;
    for (const Decl *D : RD->decls()) {
      if (const auto *T = dyn_cast<FunctionTemplateDecl>(D)) {
        if (T->getTemplatedDecl()->getOverloadedOperator() == OO_Call)
          for (const FunctionDecl *S : T->specializations())
            R = Cost::join(R, target(S, A->getBeginLoc()));
      } else if (const auto *M = dyn_cast<CXXMethodDecl>(D)) {
        if (M->getOverloadedOperator() == OO_Call)
          R = Cost::join(R, target(M, A->getBeginLoc()));
      }
    }
  }
  return R->zero() ? Cost::leaf(Poly::constant(1)) : R;
}

CostRef Extractor::call(const FunctionDecl *FD, const Expr *E,
                        const Expr *Object, llvm::ArrayRef<const Expr *> Args) {
  if (unsigned ID = FD->getBuiltinID();
      ID && !Ctx.BuiltinInfo.isPredefinedLibFunction(ID))
    return Cost::leaf({});
  SourceLocation L = E->getBeginLoc();
  if (auto C = annotated(FD, "vc::cost", L))
    return Cost::leaf(*C);
  if (system(FD)) {
    std::string Name = plain(FD);
    const auto *Method = dyn_cast<CXXMethodDecl>(FD);
    const auto *Ctor = dyn_cast<CXXConstructorDecl>(FD);
    if ((Method && Method->isMoveAssignmentOperator()) ||
        (Ctor && Ctor->isMoveConstructor()))
      return Cost::leaf(Poly::constant(1));
    const Model *M = nullptr;
    for (const Model &X : Opt.Models)
      if (Args.size() >= X.MinArgs && X.Match.match(Name)) {
        M = &X;
        break;
      }
    if (!M)
      return unbounded("external", "call to " + Name + ", which has no model",
                       L);
    if (M->K == Model::Const)
      return Cost::leaf(Poly::constant(1));
    if (M->K == Model::Indirect)
      return unbounded("indirect", "call through " + Name, L);
    if (M->K == Model::Opaque)
      return unbounded("external", "call to " + Name + ", modelled opaque", L);
    const Expr *Of = M->Arg < 0                     ? Object
                     : size_t(M->Arg) < Args.size() ? Args[M->Arg]
                                                    : nullptr;
    std::optional<Poly> N = Of ? (M->Arg < 0 ? size(Of) : amount(Of))
                               : std::optional<Poly>(Poly::constant(1));
    if (!N)
      return unbounded("library",
                       "call to " + Name + " on a range with no bound", L);
    Poly F = M->K == Model::Linear      ? *N
             : M->K == Model::LinearLog ? *N * N->log2()
                                        : N->log2();
    return Cost::sum(Cost::leaf(Poly::constant(1)),
                     Cost::scale(F, callable(Args)));
  }
  if (const auto *MD = dyn_cast<CXXMethodDecl>(FD);
      MD && MD->isVirtual() && isa<CXXMemberCallExpr>(E)) {
    const auto *ME = dyn_cast<MemberExpr>(
        cast<CXXMemberCallExpr>(E)->getCallee()->IgnoreParens());
    if (ME && !ME->hasQualifier()) {
      if (const CXXMethodDecl *D = MD->getDevirtualizedMethod(Object, false))
        return target(D, L);
      if (auto C = annotated(MD, "vc::cost", L))
        return Cost::leaf(*C);
      return Cost::call(usr(MD), plain(MD), site(L), true, MD->isPureVirtual());
    }
  }
  return target(FD, L);
}

std::optional<Poly> Extractor::symbolOf(const VarDecl *VD) {
  auto Name = annotation(VD, "vc::symbol");
  bool Named = Name || (VD->hasGlobalStorage() && !VD->isStaticLocal());
  if (!VD->getType().isConstQualified() && !VD->isConstexpr() && !Name)
    return std::nullopt;
  std::optional<double> Value;
  if (const VarDecl *Def = VD->getDefinition() ? VD->getDefinition() : VD)
    if (Def->getAnyInitializer())
      if (const APValue *V = Def->evaluateValue(); V && V->isInt())
        Value = std::max<double>(0, V->getInt().getExtValue());
  if (!Named)
    return Value ? std::optional<Poly>(Poly::constant(*Value)) : std::nullopt;
  std::string S = Name && !Name->empty() ? *Name : VD->getName().str();
  Out.symbol(S, Value);
  return Poly::symbol(S);
}

std::optional<Poly> Extractor::bound(const Expr *E) {
  for (const Expr *X = E;;) {
    if (const auto *S = dyn_cast<SubstNonTypeTemplateParmExpr>(X)) {
      auto V = bound(S->getReplacement());
      if (V && V->constantValue())
        return Poly::capacity(*V->constantValue());
      return V;
    }
    const Expr *Next = isa<ParenExpr, CastExpr, FullExpr>(X)
                           ? cast<Expr>(*X->child_begin())
                           : X;
    if (Next == X)
      break;
    X = Next;
  }
  E = E->IgnoreParenCasts();
  const ValueDecl *D = nullptr;
  if (const auto *R = dyn_cast<DeclRefExpr>(E))
    D = R->getDecl();
  else if (const auto *M = dyn_cast<MemberExpr>(E))
    D = M->getMemberDecl();
  if (D) {
    if (auto P = annotated(D, "vc::size", E->getBeginLoc()))
      return P;
    if (const auto *VD = dyn_cast<VarDecl>(D)) {
      if (auto P = symbolOf(VD))
        return P;
      if (VD->isLocalVarDecl() && VD->getType().isConstQualified() &&
          VD->getInit())
        return bound(VD->getInit());
    }
  }
  if (const auto *B = dyn_cast<BinaryOperator>(E)) {
    auto L = bound(B->getLHS()), R = bound(B->getRHS());
    std::optional<double> LC = L ? L->constantValue() : std::nullopt;
    std::optional<double> RC = R ? R->constantValue() : std::nullopt;
    switch (B->getOpcode()) {
    case BO_Add:
      if (L && R)
        return *L + *R;
      break;
    case BO_Mul:
      if (L && R)
        return *L * *R;
      break;
    case BO_Sub:
      if (LC && RC)
        return Poly::constant(std::max(0.0, *LC - *RC));
      return L;
    case BO_Div:
      if (LC && RC && *RC > 0)
        return Poly::constant(std::floor(*LC / *RC));
      return L;
    case BO_Shr:
      if (LC && RC)
        return Poly::constant(std::floor(std::ldexp(*LC, -int(*RC))));
      return L;
    case BO_Shl:
      if (L && RC)
        return *L * Poly::constant(std::ldexp(1.0, int(*RC)));
      break;
    case BO_Rem:
      if (R && RC && *RC > 0)
        R = Poly::constant(*RC - 1);
      [[fallthrough]];
    case BO_And:
      if (L && R)
        return Poly::tighter(*L, *R);
      return L ? L : R;
    default:
      break;
    }
  }
  if (const auto *C = dyn_cast<ConditionalOperator>(E)) {
    auto T = bound(C->getTrueExpr()), F = bound(C->getFalseExpr());
    if (T && F)
      return T->join(*F);
  }
  if (const auto *CE = dyn_cast<CallExpr>(E))
    if (const FunctionDecl *FD = CE->getDirectCallee()) {
      if (auto P = annotated(FD, "vc::size", E->getBeginLoc()))
        return P;
      std::string N = plain(FD);
      llvm::SmallVector<const Expr *, 4> Args(CE->arguments());
      if (Args.size() > 2)
        Args.resize(2);
      if (!Args.empty())
        if (const auto *IL = dyn_cast<CXXStdInitializerListExpr>(
                Args[0]->IgnoreParenImpCasts()))
          if (const auto *Init = dyn_cast<InitListExpr>(
                  IL->getSubExpr()->IgnoreParenImpCasts()))
            Args.assign(Init->inits().begin(), Init->inits().end());
      if (N == "std::min" || N == "std::max") {
        std::optional<Poly> R;
        for (const Expr *A : Args) {
          auto P = bound(A);
          if (N == "std::max" && !P)
            return std::nullopt;
          if (P)
            R = !R ? *P : N == "std::max" ? R->join(*P) : Poly::tighter(*R, *P);
        }
        return R;
      }
      llvm::StringRef Short = FD->getName();
      if (Short == "size" || Short == "capacity" || Short == "length" ||
          Short == "ssize") {
        if (const auto *M = dyn_cast<CXXMemberCallExpr>(CE))
          return size(M->getImplicitObjectArgument());
        if (const auto *M =
                dyn_cast<MemberExpr>(CE->getCallee()->IgnoreParenImpCasts()))
          return size(M->getBase());
        if (CE->getNumArgs() == 1)
          return size(CE->getArg(0));
      }
    }
  Expr::EvalResult R;
  if (!E->isValueDependent() && E->EvaluateAsInt(R, Ctx))
    return Poly::constant(std::max<double>(0, R.Val.getInt().getExtValue()));
  return std::nullopt;
}

std::optional<Poly> Extractor::capacity(QualType T) {
  for (int Step = 0; Step < 32 && !T.isNull(); ++Step) {
    T = T.getNonReferenceType();
    if (const auto *A = Ctx.getAsConstantArrayType(T))
      return Poly::constant(A->getSize().getZExtValue());
    const auto *TST = T->getAs<TemplateSpecializationType>();
    if (!TST)
      break;
    if (TST->isTypeAlias()) {
      T = TST->getAliasedType();
      continue;
    }
    const TemplateDecl *TD = TST->getTemplateName().getAsTemplateDecl();
    if (!TD)
      break;
    const TemplateParameterList *Params = TD->getTemplateParameters();
    int Index = -1;
    if (plain(TD) == "std::array")
      Index = 1;
    else if (annotation(TD->getTemplatedDecl(), "vc::capped"))
      for (unsigned I = 0; I < Params->size(); ++I)
        if (isa<NonTypeTemplateParmDecl>(Params->getParam(I)))
          Index = I;
    if (Index < 0 || unsigned(Index) >= TST->template_arguments().size())
      break;
    const TemplateArgument &Arg = TST->template_arguments()[Index];
    if (Arg.getKind() == TemplateArgument::Expression)
      return bound(Arg.getAsExpr());
    if (Arg.getKind() == TemplateArgument::Integral)
      return Poly::capacity(Arg.getAsIntegral().getZExtValue());
    break;
  }
  if (T.isNull())
    return std::nullopt;
  const auto *Spec = dyn_cast_or_null<ClassTemplateSpecializationDecl>(
      T.getCanonicalType()->getAsCXXRecordDecl());
  if (!Spec)
    return std::nullopt;
  const ClassTemplateDecl *TD = Spec->getSpecializedTemplate();
  bool Array = plain(TD) == "std::array";
  if (!Array && !annotation(TD->getTemplatedDecl(), "vc::capped"))
    return std::nullopt;
  const TemplateArgumentList &Args = Spec->getTemplateArgs();
  for (unsigned I = Args.size(); I-- > 0;)
    if (Args[I].getKind() == TemplateArgument::Integral && (!Array || I == 1))
      return Poly::capacity(Args[I].getAsIntegral().getZExtValue());
  return std::nullopt;
}

std::optional<Poly> Extractor::size(const Expr *E) {
  E = E->IgnoreParenImpCasts();
  if (const auto *M = dyn_cast<MaterializeTemporaryExpr>(E))
    return size(M->getSubExpr());
  if (const auto *IL = dyn_cast<CXXStdInitializerListExpr>(E))
    if (const auto *Init =
            dyn_cast<InitListExpr>(IL->getSubExpr()->IgnoreParenImpCasts()))
      return Poly::constant(Init->getNumInits());
  if (const auto *U = dyn_cast<UnaryOperator>(E))
    if (U->getOpcode() == UO_Deref)
      return size(U->getSubExpr());
  const ValueDecl *D = nullptr;
  if (const auto *R = dyn_cast<DeclRefExpr>(E))
    D = R->getDecl();
  else if (const auto *M = dyn_cast<MemberExpr>(E))
    D = M->getMemberDecl();
  else if (const auto *C = dyn_cast<CallExpr>(E))
    if (const FunctionDecl *FD = C->getDirectCallee()) {
      if (auto P = annotated(FD, "vc::size", E->getBeginLoc()))
        return P;
      if (auto P = capacity(FD->getReturnType()))
        return P;
    }
  if (D) {
    if (auto P = annotated(D, "vc::size", E->getBeginLoc()))
      return P;
    if (const auto *DD = dyn_cast<DeclaratorDecl>(D))
      if (const TypeSourceInfo *TI = DD->getTypeSourceInfo()) {
        TypeLoc TL = TI->getTypeLoc().IgnoreParens();
        if (auto R = TL.getAs<ReferenceTypeLoc>())
          TL = R.getPointeeLoc().IgnoreParens();
        if (auto A = TL.getAs<ConstantArrayTypeLoc>())
          if (const Expr *N = A.getSizeExpr())
            return bound(N);
      }
    if (auto P = capacity(D->getType()))
      return P;
  }
  QualType T = E->getType();
  if (T->isPointerType())
    T = T->getPointeeType();
  return capacity(T);
}

std::optional<Poly> Extractor::amount(const Expr *E) {
  const Expr *X = E->IgnoreParenImpCasts();
  if (X->getType()->isIntegralOrEnumerationType())
    return bound(X);
  if (const auto *IL = dyn_cast<CXXStdInitializerListExpr>(X))
    if (const auto *Init =
            dyn_cast<InitListExpr>(IL->getSubExpr()->IgnoreParenImpCasts()))
      return Poly::constant(Init->getNumInits());
  if (const auto *B = dyn_cast<BinaryOperator>(X))
    if (B->isAdditiveOp())
      return amount(B->getLHS());
  if (const auto *CE = dyn_cast<CallExpr>(X))
    if (const FunctionDecl *FD = CE->getDirectCallee()) {
      llvm::StringRef N = FD->getName();
      if (N == "begin" || N == "cbegin" || N == "rbegin" || N == "data" ||
          N == "end" || N == "cend" || N == "rend") {
        if (const auto *M = dyn_cast<CXXMemberCallExpr>(CE))
          return size(M->getImplicitObjectArgument());
        if (CE->getNumArgs() == 1)
          return size(CE->getArg(0));
      }
    }
  if (X->getType()->isPointerType())
    if (const auto *C = dyn_cast<ImplicitCastExpr>(E->IgnoreParens()))
      if (C->getCastKind() == CK_ArrayToPointerDecay)
        return size(C->getSubExpr());
  return size(X);
}

/// True if `S` writes to or takes the address of `V`.
bool writes(const Stmt *S, const VarDecl *V) {
  if (!S)
    return false;
  auto Is = [V](const Expr *E) {
    const auto *R = dyn_cast<DeclRefExpr>(E->IgnoreParenImpCasts());
    return R && R->getDecl() == V;
  };
  if (const auto *B = dyn_cast<BinaryOperator>(S))
    if (B->isAssignmentOp() && Is(B->getLHS()))
      return true;
  if (const auto *U = dyn_cast<UnaryOperator>(S))
    if ((U->isIncrementDecrementOp() || U->getOpcode() == UO_AddrOf) &&
        Is(U->getSubExpr()))
      return true;
  for (const Stmt *K : S->children())
    if (writes(K, V))
      return true;
  return false;
}

std::optional<Poly> Extractor::trip(const ForStmt *F) {
  const auto *Cond = dyn_cast_or_null<BinaryOperator>(
      F->getCond() ? F->getCond()->IgnoreParenImpCasts() : nullptr);
  if (!Cond || !Cond->isComparisonOp())
    return std::nullopt;
  auto VarOf = [](const Expr *E) -> const VarDecl * {
    E = E->IgnoreParenImpCasts();
    if (const auto *U = dyn_cast<UnaryOperator>(E))
      if (U->isPostfix() && U->isDecrementOp())
        E = U->getSubExpr()->IgnoreParenImpCasts();
    const auto *R = dyn_cast<DeclRefExpr>(E);
    return R ? dyn_cast<VarDecl>(R->getDecl()) : nullptr;
  };
  const VarDecl *V = nullptr;
  double Step = 0;
  if (const Expr *Inc =
          F->getInc() ? F->getInc()->IgnoreParenImpCasts() : nullptr) {
    if (const auto *U = dyn_cast<UnaryOperator>(Inc)) {
      if (U->isIncrementDecrementOp()) {
        V = VarOf(U->getSubExpr());
        Step = U->isIncrementOp() ? 1 : -1;
      }
    } else if (const auto *C = dyn_cast<CompoundAssignOperator>(Inc)) {
      Expr::EvalResult R;
      if (C->getRHS()->EvaluateAsInt(R, Ctx) &&
          R.Val.getInt().isStrictlyPositive()) {
        V = VarOf(C->getLHS());
        Step = double(R.Val.getInt().getExtValue()) *
               (C->getOpcode() == BO_AddAssign   ? 1
                : C->getOpcode() == BO_SubAssign ? -1
                                                 : 0);
      }
    }
  } else {
    for (const Expr *Side : {Cond->getLHS(), Cond->getRHS()})
      if (const auto *U = dyn_cast<UnaryOperator>(Side->IgnoreParenImpCasts()))
        if (U->isPostfix() && U->isDecrementOp()) {
          V = VarOf(U);
          Step = -1;
        }
  }
  if (!V || Step == 0 || !V->getType()->isIntegerType())
    return std::nullopt;
  BinaryOperatorKind Op = Cond->getOpcode();
  const Expr *Limit = Cond->getRHS();
  if (VarOf(Cond->getLHS()) != V) {
    if (VarOf(Cond->getRHS()) != V)
      return std::nullopt;
    Limit = Cond->getLHS();
    Op = BinaryOperator::reverseComparisonOp(Op);
  }
  if (writes(F->getBody(), V))
    return std::nullopt;
  const Expr *Init = nullptr;
  if (const auto *D = dyn_cast_or_null<DeclStmt>(F->getInit())) {
    for (const Decl *X : D->decls())
      if (X == V)
        Init = V->getInit();
  } else if (const auto *B = dyn_cast_or_null<BinaryOperator>(F->getInit())) {
    if (B->getOpcode() == BO_Assign && VarOf(B->getLHS()) == V)
      Init = B->getRHS();
  }
  bool Inclusive = Op == BO_LE || Op == BO_GE;
  const Expr *Hi = Limit, *Lo = Init;
  if (Step < 0) {
    if (Op != BO_GT && Op != BO_GE && Op != BO_NE)
      return std::nullopt;
    std::swap(Hi, Lo);
  } else if (Op != BO_LT && Op != BO_LE && Op != BO_NE) {
    return std::nullopt;
  }
  if (!Hi)
    return std::nullopt;
  auto H = bound(Hi);
  if (!H)
    return std::nullopt;
  std::optional<Poly> L = Lo ? bound(Lo) : std::nullopt;
  auto HC = H->constantValue();
  auto LC = L ? L->constantValue() : std::nullopt;
  double Extra = Inclusive ? 1 : 0;
  if (HC && LC) {
    double Span = *HC - *LC + Extra;
    if (Op == BO_NE && std::fmod(Span, std::fabs(Step)) != 0)
      return std::nullopt;
    return Poly::constant(std::max(0.0, std::ceil(Span / std::fabs(Step))));
  }
  if (Op == BO_NE && std::fabs(Step) != 1)
    return std::nullopt;
  return *H + Poly::constant(Extra);
}

class Visitor : public RecursiveASTVisitor<Visitor> {
public:
  explicit Visitor(Extractor &X) : X(X) {}
  bool shouldVisitTemplateInstantiations() const { return true; }
  bool TraverseDecl(Decl *D) {
    if (D && !isa<TranslationUnitDecl>(D) && X.system(D))
      return true;
    return RecursiveASTVisitor::TraverseDecl(D);
  }
  bool VisitFunctionDecl(FunctionDecl *FD) {
    X.function(FD);
    return true;
  }
  bool VisitTemplateSpecializationTypeLoc(TemplateSpecializationTypeLoc L) {
    X.declare(L.getType());
    return true;
  }
  bool VisitVarDecl(VarDecl *VD) {
    X.constant(VD);
    return true;
  }
  bool VisitCXXMethodDecl(CXXMethodDecl *MD) {
    X.method(MD);
    return true;
  }
  bool VisitLambdaExpr(LambdaExpr *L) {
    const CXXRecordDecl *C = L->getLambdaClass();
    if (const FunctionTemplateDecl *T = C->getDependentLambdaCallOperator())
      for (const FunctionDecl *S : T->specializations())
        X.function(S);
    else
      X.function(L->getCallOperator());
    return true;
  }

private:
  Extractor &X;
};

} // namespace

llvm::Expected<Model> Model::create(Kind K, int Arg, std::string Glob) {
  Model M;
  M.K = K;
  M.Arg = Arg;
  M.Pattern = std::make_shared<const std::string>(std::move(Glob));
  auto G = llvm::GlobPattern::create(*M.Pattern, 4096);
  if (!G)
    return G.takeError();
  M.Match = std::move(*G);
  return M;
}

std::vector<Model> builtinModels() {
  return {
      model(Model::Indirect, 0,
            "std::{function,move_only_function}::operator()"),
      model(Model::Indirect, 0, "std::{invoke,invoke_r,apply}"),
      model(Model::LinearLog, 0,
            "std::{sort,stable_sort,partial_sort,sort_heap}"),
      model(Model::Log, 0,
            "std::{lower_bound,upper_bound,equal_range,binary_search,push_heap,"
            "pop_heap}"),
      model(Model::Linear, 0, RangeAlgorithms, 2),
      model(Model::Linear, 1, "std::{fill_n,copy_n,generate_n,for_each_n}"),
      model(Model::Linear, 2, "{,std::}{memcpy,memmove,memset,memcmp}"),
      model(Model::Linear, 0, "std::ranges::*::operator()"),
      model(Model::Log, -1,
            "std::{map,set,multimap,multiset}::{find,count,contains,insert,"
            "emplace,erase,lower_bound,upper_bound,equal_range,operator\\[\\],"
            "at}"),
      model(Model::Linear, 0,
            "std::{vector,basic_string,deque}::{resize,reserve,assign,vector,"
            "deque,operator=}"),
      model(Model::Linear, -1,
            "std::{vector,basic_string,deque}::{insert,erase}"),
      model(Model::Const, 0, "std::*"),
      model(Model::Const, 0, "__gnu_cxx::*"),
      model(Model::Const, 0, "{__builtin_*,__cxa_*,__assert_fail}"),
      model(Model::Const, 0, MathFunctions),
      model(Model::Const, 0,
            "{strlen,strcmp,strncmp,printf,fprintf,snprintf,puts,abort,exit,"
            "malloc,calloc,free,getenv}"),
      model(Model::Const, 0, "operator {new,delete}*"),
  };
}

std::vector<Model> parseModels(const std::string &Json, std::string &Error) {
  auto V = llvm::json::parse(Json);
  if (!V) {
    Error = toString(V.takeError());
    return {};
  }
  std::vector<Model> Out;
  const auto *A = V->getAsArray();
  if (!A) {
    Error = "models: expected a JSON array";
    return {};
  }
  static const std::map<std::string, Model::Kind> Kinds = {
      {"const", Model::Const},       {"linear", Model::Linear},
      {"nlogn", Model::LinearLog},   {"log", Model::Log},
      {"indirect", Model::Indirect}, {"opaque", Model::Opaque}};
  for (const llvm::json::Value &E : *A) {
    const auto *O = E.getAsObject();
    auto Match = O ? O->getString("match") : std::nullopt;
    auto Kind = O ? O->getString("cost") : std::nullopt;
    if (!Match || !Kind || !Kinds.count(Kind->str())) {
      Error = "models: each entry needs \"match\" and a \"cost\" of const, "
              "linear, nlogn, log, indirect or opaque";
      return {};
    }
    auto M = Model::create(Kinds.at(Kind->str()),
                           int(O->getInteger("arg").value_or(0)), Match->str());
    if (!M) {
      Error = toString(M.takeError());
      return {};
    }
    M->MinArgs = unsigned(O->getInteger("min_args").value_or(0));
    Out.push_back(std::move(*M));
  }
  return Out;
}

void extract(ASTContext &Ctx, const Options &Opt, Program &Out) {
  Extractor X(Ctx, Opt, Out);
  Visitor(X).TraverseDecl(Ctx.getTranslationUnitDecl());
  X.finish();
}

} // namespace vc
