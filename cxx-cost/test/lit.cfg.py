"""lit configuration: each fixture runs vc-cxx-cost and FileChecks the report."""

# pylint: disable=undefined-variable
import lit.formats

config.name = "vc-cxx-cost"
config.test_format = lit.formats.ShTest(execute_external=True)
config.suffixes = [".cc", ".test"]
config.excludes = ["Inputs"]
config.test_source_root = os.path.dirname(__file__)
tool = lit_config.params["tool"]
include = lit_config.params["include"]
shim = os.path.join(config.test_source_root, "crosscheck.py")
config.substitutions.append(("%cost", f"python3 {shim} {tool}"))
config.substitutions.append(("%flags", f"-- -std=c++20 -I{include}"))
config.environment["LLVM_PROFILE_FILE"] = os.environ.get(
    "LLVM_PROFILE_FILE", "/dev/null"
)
config.environment["PATH"] = os.environ["PATH"]
