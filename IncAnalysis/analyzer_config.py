from enum import Enum, auto
import json
from abc import ABC, abstractmethod
from pathlib import Path

from IncAnalysis.environment import Environment, IncrementalMode
from IncAnalysis.analyzer_utils import *

class AnalyzerConfig(ABC):
    def __init__(self, env: Environment, workspace: Path, output_path: Path, checker_file: str = None, config_file: str = None):
        super().__init__()
        self.json_config = {}
        self.json_checkers = None
        self.env: Environment = env
        self.workspace: Path = workspace
        self.output_path = output_path
        self.args = None
        if config_file is not None:
            self.init_from_file(config_file)
        if checker_file is not None:
            self.load_checkers(checker_file)
    
    def init_from_file(self, config_file):
        with open(config_file, 'r') as f:
            self.json_config = json.load(f)
    
    def load_checkers(self, checker_file):
        with open(checker_file, 'r') as f:
            self.json_checkers = json.load(f)
    
    def update_output_path(self, output_path):
        self.output_path = output_path
        self.analyze_args(True)

    @abstractmethod
    def analyze_args(self, update = False):
        return []

csa_default_config = {
    "CSAOptions": [
        # "-analyzer-disable-all-checks",
        "-analyzer-opt-analyze-headers",
        # "-analyzer-inline-max-stack-depth=5",
        # "-analyzer-inlining-mode=noredundancy",
        "-analyzer-stats", # Output time cost.
    ],
    "CSAConfig": [
        "crosscheck-with-z3=true",
        "expand-macros=true",
        "unroll-loops=true",
        # "mode=deep",
        # "ipa=dynamic-bifurcate",
        # "ctu-import-cpp-threshold=8",
        # "ctu-import-threshold=24",
        # "ipa-always-inline-size=3",
    ]
}

cppcheck_default_config = {
}

class IPAKind(Enum):
    # Perform only intra-procedural analysis.
    IPAK_None = auto(),
    # Inline C functions and blocks when their definitions are available.
    IPAK_BasicInlining = auto(),
    # Inline callees(C, C++, ObjC) when their definitions are available.
    IPAK_Inlining = auto(),
    # Enable inlining of dynamically dispatched methods.
    IPAK_DynamicDispatch = auto(),
    # Enable inlining of dynamically dispatched methods, bifurcate paths when
    # exact type info is unavailable.
    IPAK_DynamicDispatchBifurcate = auto()

class CSAConfig(AnalyzerConfig):
    def __init__(self, env: Environment, csa_workspace: Path, csa_output_path: Path, config_file: str=None, checker_file: str="config/clangsa_checkers.json"):
        super().__init__(env, csa_workspace, csa_output_path, checker_file, config_file)
        if not config_file:
            self.config_json = csa_default_config
        # Options may influence incremental analysis.
        self.AnalyzeAll = False
        self.IPAMode = IPAKind.IPAK_DynamicDispatchBifurcate
        self.parse_config_json()

    def parse_config_json(self):
        self.csa_options = self.config_json.get("CSAOptions")
        if self.csa_options:
            for cmd in self.csa_options:
                cmd = cmd.split()
                if cmd == "-analyzer-opt-analyze-headers":
                    self.AnalyzeAll = True
        else:
            self.csa_options = []
        self.csa_config = self.config_json.get("CSAConfig")
        if self.csa_config:
            for cmd in self.csa_config:
                cmd_pair = cmd.split("=")
                if cmd_pair[0] == "ipa":
                    if cmd_pair[1] == "none":
                        self.IPAMode = IPAKind.IPAK_None 
                    elif cmd_pair[1] == "basic-inlining":
                        self.IPAMode = IPAKind.IPAK_BasicInlining
                    elif cmd_pair[1] == "inlining":
                        self.IPAMode = IPAKind.IPAK_Inlining
                    elif cmd_pair[1] == "dynamic":
                        self.IPAMode = IPAKind.IPAK_DynamicDispatch
                    elif cmd_pair[1] == "dynamic-bifurcate":
                        self.IPAMode = IPAKind.IPAK_DynamicDispatchBifurcate
        else:
            self.csa_config = []
        self.csa_config.extend(["aggressive-binary-operation-simplification=true"])
        
        self.csa_options.append('-analyzer-output=html')
        # self.csa_options.append('-analyzer-disable-checker=deadcode')

        if self.json_checkers is not None:
            checkers = get_analyzer_checkers(self.env.CLANG)
            enable_checkers = []
            for checker_name, _ in checkers:
                check_info = self.json_checkers['labels'].get(checker_name)
                if check_info and "profile:default" in check_info:
                    # Only turn on default checkers.
                    enable_checkers.append(checker_name)
            self.csa_options.extend(['-analyzer-checker=' + ','.join(enable_checkers)])

        if self.env.ctu:
            self.csa_config.extend([
                'experimental-enable-naive-ctu-analysis=true',
                'ctu-dir=' + str(self.workspace),
                'ctu-index-name=' + str(self.workspace / 'externalDefMap.txt'),
                'ctu-invocation-list=' + str(self.workspace / 'invocations.yaml')
            ])
            if self.env.analyze_opts.verbose:
                self.csa_config.append('display-ctu-progress=true')

    def analyze_args(self, update = False):
        if not update:
            if self.args is not None:
                return self.args
        self.args = ['--analyze', '-o', str(self.output_path)]
        for option in self.csa_options:
            self.args += ['-Xanalyzer', option]
        if len(self.csa_config) > 0:
            self.args += ['-Xanalyzer', '-analyzer-config', '-Xanalyzer', ','.join(self.csa_config)]
        return self.args
        
class CppCheckConfig(AnalyzerConfig):
    def __init__(self, env: Environment, cppcheck_workspace: Path, cppcheck_output_path: Path, config_file: str=None):
        super().__init__(env, cppcheck_workspace, cppcheck_output_path, config_file)
        if not config_file:
            self.config_json = cppcheck_default_config
        self.parse_config_json()

    def parse_config_json(self):
        pass

    def analyze_args(self):
        args = []
        return args