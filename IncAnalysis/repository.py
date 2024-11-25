from pathlib import Path
from typing import List
import os

from IncAnalysis.logger import logger
from IncAnalysis.utils import * 
from IncAnalysis.environment import *
from IncAnalysis.configuration import Configuration, Option, BuildType

class Repository:
    name: str
    src_path: Path
    default_config: Configuration
    configurations: List[Configuration]
    running_status: bool # whether the repository sessions should keep running
    env: Environment

    def __init__(self, name, src_path, env: Environment, default_options: List[str] = [], options_list:List[List[str]]=None, 
                 build_root = None, build_dir_name=None, default_build_type: str="cmake"):
        self.name = name
        self.src_path = Path(src_path).absolute()
        self.env = env
        self.running_status = True
        logger.TAG = self.name
        self.default_build_type = BuildType.getType(default_build_type)
        self.build_root = build_root if build_root is not None else str(self.src_path / 'build')
        self.default_config = Configuration(self.name, self.src_path, self.env, default_options, 
                                            build_path=f"{self.build_root}/{build_dir_name}" if build_dir_name else f"{self.build_root}/build_0",
                                            build_type=self.default_build_type)
        self.configurations = [self.default_config]
        if options_list:
            for idx, options in enumerate(options_list):
                self.configurations.append(
                    Configuration(self.name, self.src_path, self.env, options, build_path=f'{self.build_root}/build_{idx + 1}', baseline=self.default_config)
                )

    def add_configuration(self, options, build_dir_name=None):
        previous_config = self.configurations[-1] if len(self.configurations) > 0 else self.default_config
        self.configurations.append(
            Configuration(self.name, self.src_path, self.env, options, 
                          build_path=f"{self.build_root}/{build_dir_name}" if build_dir_name else f'{self.build_root}/build_{len(self.configurations)}',
                          baseline=self.default_config, build_type=self.default_build_type)
        )

    def process_all_session(self):
        self.build_every_config()
        self.preprocess_every_config()
        # if need incremental analyze, please excute diff session after preprocess immediately
        self.diff_every_config()
        self.extract_ii_every_config()
        self.generate_efm_for_every_config()

    def process_one_config(self, config: Configuration):
        # 1. configure & build
        config.configure()
        config.build()
        # 2. preprocess and diff
        config.preprocess_repo()
        if self.env.inc_mode != IncrementalMode.NoInc:
            config.diff_with_other(self.default_config)
        # 3. extract inc info
        if self.env.inc_mode.value >= IncrementalMode.FuncitonLevel.value:
            config.extract_inc_info()
        # 4. prepare for CSA
        if self.env.ctu:
            config.generate_efm()
            config.merge_efm()
        # 5. execute analyzers
        if self.env.inc_mode.value >= IncrementalMode.FuncitonLevel.value:
            config.propagate_reanalyze_attr()
        config.analyze()

    def process_every_config(self, sessions, **kwargs):
        if not self.running_status:
            return
        for config in self.configurations:
            if isinstance(sessions, list):
                for session in sessions:
                    if session is None:
                        continue
                    getattr(config, session.__name__)(**kwargs)
                    if config.session_times[session.__name__] == SessionStatus.Failed:
                        print(f"Session {session.__name__} failed, stop all sessions.")
                        self.running_status = False
                        return
            else:
                getattr(config, sessions.__name__)(**kwargs)
                if config.session_times[sessions.__name__] == SessionStatus.Failed:
                    print(f"Session {sessions.__name__} failed, stop all sessions.")
                    self.running_status = False
                    return


    def build_every_config(self):
        self.process_every_config(Configuration.configure)
        self.process_every_config(Configuration.build)

    def extract_ii_every_config(self):
        self.process_every_config(Configuration.extract_inc_info)

    def diff_every_config(self):
        self.process_every_config(Configuration.diff_with_other, other=self.default_config)

    def preprocess_every_config(self):
        self.process_every_config(Configuration.preprocess_repo)

    def generate_efm_for_every_config(self):
        if self.env.ctu:
            self.process_every_config(Configuration.generate_efm)
            self.process_every_config(Configuration.merge_efm)

    def analyze_for_every_config(self):
        analyze_sessions = [
            Configuration.propagate_reanalyze_attr,
            Configuration.analyze
        ]
        if self.env.inc_mode.value >= IncrementalMode.FuncitonLevel.value:
            analyze_sessions[0] = None
        self.process_every_config(analyze_sessions)

    def session_summary(self):
        ret = f"name: {self.name}\nsrc: {self.src_path}\n"
        for config in self.configurations:
            ret += str(config)
        return ret
    
    def summary_to_csv_specific(self):
        headers = ["project", "version"]
        for session in self.default_config.session_times.keys():
            headers.append(str(session))
            # if str(session) == 'diff_with_other':
            #     headers.extend(["diff_command_time", "diff_parse_time"])
        headers.extend(["files", "diff files", "changed function", "reanalyze function", "diff but no cf", "diff but no cg"])
        data = []
        for (idx, config) in enumerate(self.configurations):
            config_data = [self.name, os.path.basename(config.build_path)]
            for session in config.session_times.keys():
                exe_time = config.session_times[session]
                if isinstance(exe_time, SessionStatus):
                    config_data.append(str(exe_time._name_))
                else:
                    config_data.append("%.3lf s" % exe_time)
                # if str(session) == 'diff_with_other' and idx == 0:
                #     config_data.append('Skipped')
                #     config_data.append('Skipped')
            config_data.append(len(config.file_list))
            config_data.append(len(config.diff_file_list))
            config_data.append(config.get_changed_function_num())
            config_data.append(config.get_reanalyze_function_num())
            config_data.append(config.diff_file_with_no_cf)
            config_data.append(config.diff_file_with_no_cg)
            data.append(config_data)

        return headers, data
    
    def summary_to_csv(self):
        headers = ["project", "version", "configure", "build", "prepare for inc", "prepare for CSA", "execute CSA"]
        prepare_for_inc = {"preprocess_repo", "diff_with_other", "extract_inc_info", "parse_call_graph", 
                           "parse_functions_changed", "propagate_reanalyze_attr", "parse_function_summaries"}
        prepare_for_csa = {"generate_efm", "merge_efm"}
        data = []
        for (idx, config) in enumerate(self.configurations):
            config_data = [self.name, os.path.basename(config.build_path)]
            config_time = 0.0
            inc_time = 0.0
            prepare_time = 0.0
            exe_csa_time = 0.0
            for session in config.session_times.keys():
                exe_time = config.session_times[session]
                if not isinstance(exe_time, SessionStatus):
                    if session in prepare_for_inc:
                        inc_time += exe_time
                    elif session in prepare_for_csa:
                        prepare_time += exe_time
                    elif session == "configure":
                        config_time = exe_time
                    elif session == "CSA":
                        exe_csa_time = exe_time
            config_data.append("%.3lf s" % config_time)
            config_data.append("%.3lf s" % inc_time)
            config_data.append("%.3lf s" % prepare_time)
            config_data.append("%.3lf s" % exe_csa_time)
            data.append(config_data)

        return headers, data
    
    def file_status_to_csv(self):
        for config in self.configurations:
            headers, data = config.file_status()
            add_to_csv(headers, data, str(config.workspace / 'file_status.csv'))