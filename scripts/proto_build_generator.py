#!/usr/bin/env python3

import os
import re
import sys
import subprocess

TAB = " " * 4

##==================== REFERENCE ===========================================##
#
# https://github.com/grpc/grpc/blob/master/bazel/test/python_test_repo/BUILD
#
##==================== HEADER TEMPLATE =====================================##
TEMPLATE_HEADER = """## Auto generated by `proto_build_generator.py`
load("@rules_proto//proto:defs.bzl", "proto_library")
load("@rules_cc//cc:defs.bzl", "cc_proto_library")
load("//tools:python_rules.bzl", {}"py_proto_library")
{}
package(default_visibility = ["//visibility:public"])

"""

HEADER_PY_GRPC = """"py_grpc_library", """

HEADER_CC_GRPC = \
    """load("@com_github_grpc_grpc//bazel:cc_grpc_library.bzl", "cc_grpc_library")
"""

##=================== NON-GRPC TEMPLATE ====================================##
TEMPLATE_NO_DEPS = \
    """cc_proto_library(
    name = "{cc_name}",
    deps = [
        ":{pb_name}",
    ],
)

proto_library(
    name = "{pb_name}",
    srcs = ["{protofile}"],
)

py_proto_library(
    name = "{py_name}",
    deps = [
        ":{pb_name}",
    ],
)
"""

TEMPLATE_DEPS = \
    """cc_proto_library(
    name = "{cc_name}",
    deps = [
        ":{pb_name}",
    ],
)

proto_library(
    name = "{pb_name}",
    srcs = ["{protofile}"],
    deps = [
        {pb_context}
    ],
)

py_proto_library(
    name = "{py_name}",
    deps = [
        ":{pb_name}",
        {py_context}
    ],
)

"""

##=========================== GRPC TEMPLATE ================================##
TEMPLATE_GRPC_NO_DEPS = \
    """cc_grpc_library(
    name = "{cc_name_grpc}",
    srcs = [":{pb_name}"],
    grpc_only = True,
    deps = [":{cc_name}"],
)

cc_proto_library(
    name = "{cc_name}",
    deps = [
        ":{pb_name}",
    ],
)

proto_library(
    name = "{pb_name}",
    srcs = ["{protofile}"],
)

py_grpc_library(
    name = "{py_name_grpc}",
    srcs = [":{pb_name}"],
    deps = [":{py_name}"],
)

py_proto_library(
    name = "{py_name}",
    deps = [
        ":{pb_name}",
    ],
)
"""

TEMPLATE_GRPC_DEPS = \
    """cc_grpc_library(
    name = "{cc_name_grpc}",
    srcs = [":{pb_name}"],
    grpc_only = True,
    deps = [":{cc_name}"],
)

cc_proto_library(
    name = "{cc_name}",
    deps = [
        ":{pb_name}",
    ],
)

proto_library(
    name = "{pb_name}",
    srcs = ["{protofile}"],
    deps = [
        {pb_context}
    ],
)

py_grpc_library(
    name = "{py_name_grpc}",
    srcs = [":{pb_name}"],
    deps = [":{py_name}"],
)

py_proto_library(
    name = "{py_name}",
    deps = [
        ":{pb_name}",
        {py_context}
    ],
)
"""

##==================== PRETTY FORMAT SETTINGS ==============================##
TEMPLATE_DEPENDENCY_FIRST_ENTRY = """"{}","""
TEMPLATE_DEPENDENCY_OTHER_ENTRY = """
{}"{}","""

##==========================================================================##
# ONLY .proto files in these topdirs are supported

ALLOWED_MODULES = ["modules", "cyber"]


def _path_check(build_file_path):
    return any(
        build_file_path.startswith(mod + "/") for mod in ALLOWED_MODULES)


##================ REGEX FOR GRPC CHECK ====================================##
PATT_SERVICE = re.compile("^service\s+\S+\s+{$")
PATT_RPC_RET = re.compile("^rpc\s+\S+(\S+)\s+returns")
PATT_RPC_ONLY = re.compile("^rpc\s+\S+(\S+)")
PATT_RET_ONLY = re.compile("^returns\s+(\S+)\s+{")


##===============  GRPC CHECK ==============================================##
def grpc_check(fpath):
    """
    Check whether grpc service is enabled in this .proto file.
    Note: only proto file with the following form will pass our check.

    service MyService {
        rpc MethodA(XXX) returns (XXX) {
        rpc MethodB(XXX)
            returns (XXX) {
        }
    }
    """
    if not fpath.endswith(".proto"):
        return False

    grpc_found = False
    with open(fpath) as fin:
        kw1_found = False
        kw2_found = False
        for line in fin:
            line = line.strip()
            if kw1_found and kw2_found:
                if PATT_RET_ONLY.match(line):
                    grpc_found = True
                    break
            elif kw1_found:
                if PATT_RPC_RET.match(line):
                    kw2_found = True
                    grpc_found = True
                    break
                if PATT_RPC_ONLY.match(line):
                    kw2_found = True
            elif PATT_SERVICE.match(line):
                kw1_found = True

        return grpc_found


##================== FORMAT GENERATED FILE =================================##
def run_buildifier(build_file_path):
    script_path = "/apollo/scripts/buildifier.sh"
    if os.path.exists(script_path):
        subprocess.call(["bash", script_path, build_file_path])


##================== MAIN FUNCTION =========================================##
def main(build_file_path):
    if not _path_check(build_file_path):
        print("Expect to run this script at $APOLLO_ROOT_DIR")
        return

    workdir = os.path.dirname(build_file_path)
    files_all = [f for f in os.listdir(workdir) if
                 os.path.isfile(os.path.join(workdir, f))
                 and f != "BUILD"
                 and f != "CMakeLists.txt"]
    ok = all(f.endswith(".proto") for f in files_all)
    if not ok:
        print(
            "Except for BUILD/CMakeLists.txt, some files under {} are NOT proto files.".
            format(workdir))
        return

    grpc_found = any(grpc_check(os.path.join(workdir, f)) for f in files_all)

    fout = open(build_file_path, "w")
    if grpc_found:
        fout.write(TEMPLATE_HEADER.format(HEADER_PY_GRPC, HEADER_CC_GRPC))
    else:
        fout.write(TEMPLATE_HEADER.format("", ""))

    for protofile in files_all:
        (proto_deptext, py_proto_deptext) = generate_dependency_text(
            workdir, protofile)
        rules = generate_rule_for_protofile(workdir, protofile,
                                            proto_deptext, py_proto_deptext)
        fout.write(rules)

    fout.close()
    print("Congratulations, {} was successfully generated.".format(
        build_file_path))

    run_buildifier(build_file_path)


##=========== BAZEL BUILD RULE FOR A SINGLE PROTO FILE =====================##


def generate_rule_for_protofile(workdir, protofile, proto_deps, py_proto_deps):
    grpc_found = grpc_check(os.path.join(workdir, protofile))

    cc_name = cc_proto_name(protofile)
    py_name = py_proto_name(protofile)
    pb_name = proto_name(protofile)
    if not grpc_found:
        if len(proto_deps) == 0:
            return TEMPLATE_NO_DEPS.format(cc_name=cc_name,
                                           py_name=py_name,
                                           pb_name=pb_name,
                                           protofile=protofile)
        return TEMPLATE_DEPS.format(cc_name=cc_name,
                                    py_name=py_name,
                                    pb_name=pb_name,
                                    protofile=protofile,
                                    pb_context=proto_deps,
                                    py_context=py_proto_deps)
    else:
        cc_name_grpc = cc_grpc_name(protofile)
        py_name_grpc = py_grpc_name(protofile)
        if len(proto_deps) == 0:
            return TEMPLATE_GRPC_NO_DEPS.format(cc_name=cc_name,
                                                py_name=py_name,
                                                pb_name=pb_name,
                                                py_name_grpc=py_name_grpc,
                                                cc_name_grpc=cc_name_grpc,
                                                protofile=protofile)
        else:
            return TEMPLATE_GRPC_DEPS.format(cc_name=cc_name,
                                             py_name=py_name,
                                             pb_name=pb_name,
                                             py_name_grpc=py_name_grpc,
                                             cc_name_grpc=cc_name_grpc,
                                             protofile=protofile,
                                             pb_context=proto_deps,
                                             py_context=py_proto_deps)


##================ UNIFIED TARGET NAMING FOR PROTO FILE ====================##
def cc_grpc_name(protofile):
    (sketch, _) = os.path.splitext(protofile)
    return sketch + "_cc_grpc"


def cc_proto_name(protofile):
    (sketch, _) = os.path.splitext(protofile)
    return sketch + "_cc_proto"


def py_grpc_name(protofile):
    (sketch, _) = os.path.splitext(protofile)
    return sketch + "_py_pb2_grpc"


def py_proto_name(protofile):
    (sketch, _) = os.path.splitext(protofile)
    return sketch + "_py_pb2"


def proto_name(protofile):
    (sketch, _) = os.path.splitext(protofile)
    return sketch + "_proto"


##====================== DEPENDENCY TEXT GENERATION ========================##
def generate_dependency_text(workdir, protofile):
    dependencies = dependency_analysis(workdir, protofile)
    if len(dependencies) == 0:
        return ("", "")
    proto_notes = []
    py_proto_notes = []
    for dep in dependencies:
        depdir = os.path.dirname(dep)
        dep_name = os.path.basename(dep)
        proto_dep_name = proto_name(dep_name)
        py_dep_name = py_proto_name(dep_name)
        if depdir == workdir:
            proto_notes.append(":{}".format(proto_dep_name))
            py_proto_notes.append(":{}".format(py_dep_name))
        else:
            proto_notes.append("//{}:{}".format(depdir, proto_dep_name))
            py_proto_notes.append("//{}:{}".format(depdir, py_dep_name))

    proto_result = TEMPLATE_DEPENDENCY_FIRST_ENTRY.format(proto_notes[0])
    for note in proto_notes[1:]:
        proto_result += TEMPLATE_DEPENDENCY_OTHER_ENTRY.format(TAB * 2, note)

    py_proto_result = TEMPLATE_DEPENDENCY_FIRST_ENTRY.format(py_proto_notes[0])
    for note in py_proto_notes[1:]:
        py_proto_result += TEMPLATE_DEPENDENCY_OTHER_ENTRY.format(
            TAB * 2, note)
    return (proto_result, py_proto_result)


##================= DEPENDENCY ANALYSIS ====================================##
def _import_line_check(line):
    return "import " in line and \
        any("\"{}/".format(mod) in line for mod in ALLOWED_MODULES)


def dependency_analysis(workdir, protofile):
    dependencies = []
    fullpath = os.path.join(workdir, protofile)
    with open(fullpath) as fin:
        for line in fin:
            if _import_line_check(line):
                dependencies.append(line.split('"')[1])
    return dependencies


##================= COMMAND LINE ===========================================##
if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage:\n{}{} path/to/proto/BUILD".format(TAB, sys.argv[0]))
        sys.exit(1)

    main(sys.argv[1])