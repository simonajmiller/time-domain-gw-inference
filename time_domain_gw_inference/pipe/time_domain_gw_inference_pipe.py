import abc
import configparser
import os
import shutil
import pathlib
from dataclasses import dataclass
from ezdag import DAG, Layer, Node, Option, Argument
from typing import Dict, List, Tuple, Union
from htcondor.dags import SimpleFormatter
import argparse
import subprocess
from time_domain_gw_inference.run_sampler import create_run_sampler_arg_parser
from time_domain_gw_inference.measure_eccentricity import create_measure_eccentricity_arg_parser
from time_domain_gw_inference.waveform_h5s import make_waveform_h5_arg_parser, get_waveform_filename

def get_option_from_list(option_name: str, option_list: list[Option]):
    return next((opt for opt in option_list if opt.name == option_name), None)


def set_option_in_list(option_list: list[Option], new_option: Option) -> None:
    """
    If the option already exists in the list, update the argument, otherwise append it to the list
    :param option_list:
    :param new_option:
    :return:
    """
    old_option = get_option_from_list(new_option.name, option_list)
    if old_option is None:
        option_list.append(new_option)
    else:
        option_list.pop(option_list.index(old_option))
        option_list.append(new_option)
    return

def check_and_create_directory(directory_path):
    """
    Check if directory exists. If no, create it, if yes, ask if should continue
    :param directory_path:
    :return:
    """
    if not os.path.exists(directory_path):
        os.makedirs(directory_path)
    else:
        continue_existing = input(
            f"The directory {directory_path} already exists."
            "This may overwrite a previous run and is not guaranteed to work"
            f" Do you want to continue? (yes/no): ").lower()
        if continue_existing not in {'yes', 'y'}:
            print("You chose wisely, exiting program.")
            exit()

@dataclass
class AbstractPipelineDAG(abc.ABC):
    output_directory: str
    config_file: str
    submit: bool
    transfer_files: bool

    def __post_init__(self):
        self.executables, self.condor_settings, self.time_domain_gw_inference_settings, \
        self.measure_eccentricity_settings, self.waveform_h5_settings = self.parse_config(self.config_file)

    def default_condor_settings(self):
        condor_settings = {
            "universe": "vanilla",
            "success_exit_code": 0,
            "getenv": "True",
            "initialdir": os.path.abspath(self.output_directory),
            "notification": "ERROR",
            "stream_output": "True",
            "stream_error": "True",
            "environment": "\"HDF5_USE_FILE_LOCKING=FAlSE OMP_NUM_THREADS=1 OMP_PROC_BIND=false\"",
            "output": "$(log_dir)/$(run_prefix)-$(nodename)-$(cluster)-$(process).out",
            "error": "$(log_dir)/$(run_prefix)-$(nodename)-$(cluster)-$(process).err",
            "log": "$(log_dir)/$(run_prefix)-$(nodename)-$(cluster)-$(process).log",
        }
        if self.transfer_files:
            condor_settings["when_to_transfer_output"] = "ON_EXIT_OR_EVICT"
        else:
            condor_settings["should_transfer_files"] = "NO"

        return condor_settings


    @staticmethod
    def find_executable_path(script_name):
        """
        Find the path of a script using the 'which' command.

        Parameters:
        - script_name (str): The name of the script to find.

        Returns:
        - str: The path of the script or an error message.
        """
        command = f'which {script_name}'
        result = subprocess.run(command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

        if result.returncode == 0:
            return result.stdout.strip()
        raise FileNotFoundError(f'Error: {result.stderr.strip()}')

    def validate_executables(self, executables: Dict[str, str]):
        if not os.path.exists(executables['run_sampler']):
            # Run the 'which' command to find the path of run_sampler.py
            executables['run_sampler'] = self.find_executable_path(executables['run_sampler'])
        else:
            executables['run_sampler'] = os.path.abspath(executables['run_sampler'])

    @staticmethod
    def validate_condor_settings(condor_settings: Dict[str, str]):
        if condor_settings.get("accounting_group_user", None) is None:
            print("WARNING: accounting_group_user not set under [condor] in the config file,"
                  " this may be a problem for some clusters")
        if condor_settings.get("accounting_group", None) is None:
            print("WARNING: accounting_group not set under [condor] in config file,"
                  " this may be a problem for some clusters")

    @staticmethod
    def validate_run_settings(run_settings: Dict[str, str]):
        return

    def parse_config(self, config_file: str) \
            -> Tuple[Dict[str, str], Dict[str, str], Dict[str, str], Dict[str, str], Dict[str, str]]:
        """
        Read the configuration file and extract values from the [data], [time_domain_gw_inference],
         and [executables] sections.

        Args:
            :param config_file: (str) The path to the configuration file.
            :param output_directory: (str) The path to the output directory that contains the dag files,
                config file, and submit script, and time_domain_gw_inference output directories.
        Returns:
            tuple[dict[str, str], dict[str, str], dict[str, str]]: A tuple containing 5 dictionaries,
            the first one for [data] section values, the second one for [time_domain_gw_inference] section values,
            and the third one for [executables] section values.

        """
        config = configparser.ConfigParser(interpolation=configparser.ExtendedInterpolation())
        config.optionxform = str  # Preserve case

        config.read(config_file)

        executables = dict(config.items("executables"))

        condor_settings = self.default_condor_settings()
        condor_settings.update(dict(config.items("condor")))

        run_settings = dict(config.items("time_domain_gw_inference"))

        try:
            measure_eccentricity_settings = dict(config.items("measure_eccentricity"))
        except configparser.NoSectionError:
            measure_eccentricity_settings = None

        try:
            waveform_h5_settings = dict(config.items("waveform_h5s"))
        except configparser.NoSectionError:
            waveform_h5_settings = None
        self.validate_executables(executables)
        self.validate_condor_settings(condor_settings)
        self.validate_run_settings(run_settings)

        return executables, condor_settings, run_settings, measure_eccentricity_settings, waveform_h5_settings

    def submit_dag_or_print_instructions(self, dag_file):
        if self.submit:
            print("TODO submit has not been implemented yet :-( ")
            # dag_submit = htcondor.Submit.from_dag(dag_file, {'force': 1})
        else:
            print(f"******************************************************")
            print(f"To submit the DAG, run the following command:")
            print(f"\tcondor_submit_dag -import_env -usedagdir {dag_file} ")
            print(f"******************************************************")

    @abc.abstractmethod
    def attach_layers_to_dag(self, dag):
        raise NotImplementedError("add_jobs_to_layers has not been implemented yet")

    def create_pipeline_dag(self):
        # Create the output directory if it doesn't exist
        check_and_create_directory(self.output_directory)

        # Create the DAG
        dag = DAG(formatter=SimpleFormatter())

        self.attach_layers_to_dag(dag)

        dagName = f"{os.path.basename(self.output_directory)}.dag"

        # Write the DAG to a file
        dag.write_dag(dagName, path=pathlib.Path(self.output_directory))
        dag.write_script(os.path.join(self.output_directory, "command_line.sh"))

        # Copy config file to output directory
        destination_path = os.path.join(self.output_directory, 'config.ini')
        shutil.copy(self.config_file, destination_path)

        dag_file = os.path.abspath(os.path.join(self.output_directory, dagName))

        self.submit_dag_or_print_instructions(dag_file)


@dataclass
class RunSamplerDag(AbstractPipelineDAG):
    cycle_list: List[float]
    times_list: List[float]
    full_only: bool = False

    @staticmethod
    def _copy_file_to_directory_and_return_new_name_(file, target_directory, relative_path=None):
        shutil.copy(file, target_directory)

        just_filename = os.path.basename(file)
        new_file_path = os.path.join(target_directory, just_filename)
        if relative_path is not None:
            new_file_path = os.path.relpath(new_file_path, relative_path)
        return new_file_path

    def move_input_files(self) -> Tuple[Option, Option]:
        """
        Move assorted input files to directory containing all the runs,
        then replace paths with paths relative to output_directory
        :return:
        """

        data_directory = os.path.join(self.output_directory, 'data_directory')
        os.makedirs(data_directory, exist_ok=True)

        data_dict = eval(self.time_domain_gw_inference_settings.pop('data-path-dict'))
        psd_dict = eval(self.time_domain_gw_inference_settings.pop('psd-path-dict'))
        new_data_dict = {}
        new_psd_dict = {}

        ifos = list(data_dict.keys())
        for ifo in ifos:
            new_data_dict[ifo] = self._copy_file_to_directory_and_return_new_name_(
                data_dict[ifo], data_directory, self.output_directory)
            new_psd_dict[ifo] = self._copy_file_to_directory_and_return_new_name_(
                psd_dict[ifo], data_directory, self.output_directory)

        injected_parameters = self.time_domain_gw_inference_settings.get('injected-parameters', None)
        if injected_parameters is None:
            pe_posterior_h5_file = self.time_domain_gw_inference_settings.get('pe-posterior-h5-file', None)
            reference_parameters = self.time_domain_gw_inference_settings.get('reference-parameters', None)
            if (pe_posterior_h5_file is None) and (reference_parameters is None):
                raise AssertionError(
                    'Neither injected-parameters nor pe-posterior-h5-file supplied nor reference-parameters is supplied, please include one')
            if pe_posterior_h5_file is not None:
                self.time_domain_gw_inference_settings['pe-posterior-h5-file'] = \
                    self._copy_file_to_directory_and_return_new_name_(
                        pe_posterior_h5_file, data_directory, self.output_directory)
            if reference_parameters is not None:
                self.time_domain_gw_inference_settings['reference-parameters'] = \
                    self._copy_file_to_directory_and_return_new_name_(
                        reference_parameters, data_directory, self.output_directory)
        else:
            pe_posterior_h5_file = self.time_domain_gw_inference_settings.get('pe-posterior-h5-file', None)
            if pe_posterior_h5_file is not None:
                raise AssertionError(
                    'both injected-parameters and pe-posterior-h5-file have been supplied, please only include one')
            self.time_domain_gw_inference_settings['injected-parameters'] = \
                self._copy_file_to_directory_and_return_new_name_(
                    injected_parameters, data_directory, self.output_directory)

        data_option = Option('data', [f"{key}:{path}" for key, path in new_data_dict.items()])
        psd_option = Option('psd', [f"{key}:{path}" for key, path in new_psd_dict.items()])

        return data_option, psd_option

    def attach_layers_to_dag(self, dag):
        data_option, psd_option = self.move_input_files()
        data_options = [data_option, psd_option]
        runSamplerLayerManager = RunSamplerLayerManager(self.time_domain_gw_inference_settings,
                                                        self.executables['run_sampler'],
                                                        self.condor_settings,
                                                        transfer_files=self.transfer_files,
                                                        additional_options=data_options)
        measureEccentricityLayerManager = None
        if self.measure_eccentricity_settings is not None:
            measureEccentricityLayerManager = MeasureEccentricityLayerManager(self.measure_eccentricity_settings,
                                                            self.executables['measure_eccentricity'],
                                                            self.condor_settings,
                                                            transfer_files=self.transfer_files,
                                                            additional_options=[])

        makeWaveformsLayerManager = None
        if self.waveform_h5_settings is not None:
            # make waveforms directory
            check_and_create_directory(os.path.join(self.output_directory, 'waveforms'))
            makeWaveformsLayerManager = MakeWaveformsLayerManager(self.waveform_h5_settings,
                                                            self.executables['waveform_h5s'],
                                                            self.condor_settings,
                                                            transfer_files=self.transfer_files,
                                                            additional_options=[])
        if len(self.cycle_list) > 0:
            for cycle in self.cycle_list:
                if cycle == 0:
                    run_modes = ['full', 'pre', 'post']
                else:
                    run_modes = ['pre', 'post']

                if self.full_only:
                    run_modes = ['full']
                    if len(self.cycle_list) > 1:
                        print("WARNING: Changing number of cycles doesn't make different runs when mode is full")
                        print("\t Consider having only cycle == 0 in cycle_list")

                for run_mode in run_modes:
                    runSamplerLayerManager.add_job(self.output_directory, run_mode, cycle, 'cycles')
                    if measureEccentricityLayerManager is not None:
                        measureEccentricityLayerManager.add_job(self.output_directory, run_mode, cycle, 'cycles')
                    if makeWaveformsLayerManager is not None:
                        makeWaveformsLayerManager.add_job(self.output_directory, run_mode, cycle, 'cycles')

        if len(self.times_list) > 0:
            for time in self.times_list:
                if time == 0:
                    run_modes = ['full', 'pre', 'post']
                else:
                    run_modes = ['pre', 'post']

                if self.full_only:
                    run_modes = ['full']
                    if len(self.times_list) > 1:
                        print("WARNING: Changing cut time doesn't make different runs when mode is full")
                        print("\t Consider having only time == 0 in times_list")

                for run_mode in run_modes:
                    runSamplerLayerManager.add_job(self.output_directory, run_mode, time, 'times')
                    if measureEccentricityLayerManager is not None:
                        measureEccentricityLayerManager.add_job(self.output_directory, run_mode, time, 'times')
                    if makeWaveformsLayerManager is not None:
                        makeWaveformsLayerManager.add_job(self.output_directory, run_mode, time, 'times')

        dag.attach(runSamplerLayerManager.layer)
        if makeWaveformsLayerManager is not None:
            # TODO, this makes parent child relationship to measureEccentricityLayerManager that I don't want
            dag.attach(makeWaveformsLayerManager.layer)
        if measureEccentricityLayerManager is not None:
            dag.attach(measureEccentricityLayerManager.layer)


@dataclass
class AbstractLayerManager(abc.ABC):
    run_settings_dict: Dict[str, str]
    executable_file: str
    shared_condor_settings: Dict[str, str]
    transfer_files: bool = True
    additional_options: List[Union[Option, Argument]] = None

    def __post_init__(self):
        if self.additional_options is None:
            self.additional_options = []
        print('transfer files is ', self.transfer_files)
        self.layer = Layer(self.executable_file, name=self.method_name, retries=0, transfer_files=self.transfer_files,
                           submit_description=self.condor_settings)

    def get_job_index(self):
        return len(self.layer.nodes)

    @property
    @abc.abstractmethod
    def argument_parser(self) -> argparse.ArgumentParser:
        raise NotImplementedError

    @property
    @abc.abstractmethod
    def method_name(self) -> str:
        raise NotImplementedError("method_name has not been implemented yet")

    @staticmethod
    def update_options_list(options_list: List[Option], new_options: List[Option]) -> None:
        """
        Update the options list with new options, if the option already exists in the list, update the argument
        :param options_list:
        :param new_options:
        :return:
        """
        if new_options is None:
            return
        for new_option in new_options:
            set_option_in_list(options_list, new_option)

    @property
    @abc.abstractmethod
    def condor_settings(self):
        raise NotImplementedError("condor_settings has not been implemented yet")

    def raise_option_exists_error(self, option_name, option_list) -> None:
        if get_option_from_list(option_name, option_list) is not None:
            raise ValueError(f"{option_name} option already exists in {self.method_name} settings, "
                             f"please remove it from the [{self.method_name}] section in the config file.")
        return

    @abc.abstractmethod
    def get_run_options(self, **kwargs) -> List[Option]:
        """
        Get the command line options for the executable
        :return:
        """
        raise NotImplementedError("get_run_options has not been implemented yet")

    @abc.abstractmethod
    def add_job(self, **kwargs) -> None:
        """
        Add a job to the layer
        :return:
        """
        return


@dataclass
class RunSamplerLayerManager(AbstractLayerManager):
    @property
    def method_name(self) -> str:
        return "run_sampler"

    @property
    def condor_settings(self):
        condor_settings = self.shared_condor_settings
        additional_settings = {
            "request_memory": "14GB",
            "request_disk": "5000MB",
            "request_cpus": self.argument_parser.get_default('ncpu'),
        }
        run_options = self.get_run_options()
        N_cpu = get_option_from_list('ncpu', run_options)
        if N_cpu is not None:
            additional_settings['request_cpus'] = N_cpu.argument[0]

        condor_settings.update(additional_settings)
        return condor_settings

    @property
    def argument_parser(self) -> argparse.ArgumentParser:
        return create_run_sampler_arg_parser()

    @staticmethod
    def get_run_key(run_mode, cutoff):
        if run_mode == 'full':
            return run_mode
        else:
            return f'{run_mode}_{cutoff}'

    @staticmethod
    def get_output_filename_prefix(run_mode, cutoff, unit):
        return f'{run_mode}_{cutoff}{unit}'

    def get_run_options(self, additional_options=None, **kwargs) -> List[Option]:
        """
        Get the command line options for the run_sampler executable
        :return:
        """
        run_options = [Option(key, value) for key, value in self.run_settings_dict.items()]
        # add additional options not in run settings dict
        run_options.extend(self.additional_options)

        if additional_options is not None:
            self.update_options_list(run_options, additional_options)

        self.raise_option_exists_error("output-h5", run_options)
        self.raise_option_exists_error("mode", run_options)

        return run_options

    def get_inputs(self, relative_output_dir_name):
        # Since we have already transferred the input into the data_directory, we just need to pass data_directory
        return [Option('data-directory', 'data_directory', suppress=True),
                Option('output-directory', relative_output_dir_name, suppress=True)
                ]

    def get_outputs(self, relative_output_dir_name):
        return [Option('output-directory', relative_output_dir_name, suppress=True)]

    def add_job(self, output_directory, run_mode, cutoff, cutoff_mode, additional_options=None) -> None:
        run_options = self.get_run_options(additional_options)
        run_options.append(Option('mode', run_mode))
        if cutoff_mode=='cycles':
            run_options.append(Option('Tcut-cycles', cutoff))
            unit = 'cycles'
            
        elif cutoff_mode=='times':
            run_options.append(Option('Tcut-seconds', cutoff))
            unit = 'seconds'
        else: 
            raise AssertionError("cutoff mode must be either 'cycles' or 'times'")

        relative_output_dir_name = self.get_output_filename_prefix(run_mode, cutoff, unit)
        check_and_create_directory(os.path.join(output_directory, relative_output_dir_name))

        h5_file = f'{relative_output_dir_name}/{relative_output_dir_name}.h5'
        run_options.append(Option('output-h5', h5_file))

        inputs = self.get_inputs(relative_output_dir_name)
        outputs = self.get_outputs(relative_output_dir_name)

        self.layer += Node(
            arguments=run_options,
            inputs=inputs,
            outputs=outputs,
            variables={'run_prefix': self.get_output_filename_prefix(run_mode, cutoff, unit)}
        )


@dataclass
class MeasureEccentricityLayerManager(AbstractLayerManager):
    @property
    def method_name(self) -> str:
        return "measure_eccentricity"

    @property
    def condor_settings(self):
        condor_settings = self.shared_condor_settings
        additional_settings = {
            "request_memory": "2GB",
            "request_disk": "5GB",
            "request_cpus": self.argument_parser.get_default('ncpu'),
        }
        run_options = self.get_run_options()
        N_cpu = get_option_from_list('ncpu', run_options)
        if N_cpu is not None:
            additional_settings['request_cpus'] = N_cpu.argument[0]

        condor_settings.update(additional_settings)
        return condor_settings

    @property
    def argument_parser(self) -> argparse.ArgumentParser:
        return create_run_sampler_arg_parser()

    def get_run_options(self, additional_options=None, **kwargs) -> List[Option]:
        """
        Get the command line options for the run_sampler executable
        :return:
        """
        run_options = [Option(key, value) for key, value in self.run_settings_dict.items()]
        # add additional options not in run settings dict
        run_options.extend(self.additional_options)

        if additional_options is not None:
            self.update_options_list(run_options, additional_options)

        self.raise_option_exists_error("directory", run_options)
        self.raise_option_exists_error("run_key", run_options)
        return run_options

    def get_inputs(self, relative_output_dir_name):
        # Since we have already transferred the input into the data_directory, we just need to pass data_directory
        return [
            Option('data-directory', 'data_directory', suppress=True),
            Option('command_line', 'command_line.sh', suppress=True),  # need to transfer this so it can be parsed
            Option('output-directory', relative_output_dir_name, suppress=True)
            ]

    def get_outputs(self, relative_output_dir_name):
        return [Option('output-directory', relative_output_dir_name, suppress=True)]

    def add_job(self, output_directory, run_mode, cutoff, cutoff_mode, additional_options=None) -> None:
        run_options = self.get_run_options(additional_options)
        run_options.append(Option('run_key', RunSamplerLayerManager.get_run_key(run_mode, cutoff)))
        run_options.append(Option('directory', '.'))
        if cutoff_mode == 'cycles':
            unit = 'cycles'

        elif cutoff_mode == 'times':
            unit = 'seconds'
        else:
            raise AssertionError("cutoff mode must be either 'cycles' or 'times'")

        relative_output_dir_name = RunSamplerLayerManager.get_output_filename_prefix(run_mode, cutoff, unit)

        inputs = self.get_inputs(relative_output_dir_name)
        outputs = self.get_outputs(relative_output_dir_name)

        self.layer += Node(
            arguments=run_options,
            inputs=inputs,
            outputs=outputs,
            variables={'run_prefix': RunSamplerLayerManager.get_output_filename_prefix(run_mode, cutoff, unit)}
        )

@dataclass
class MakeWaveformsLayerManager(AbstractLayerManager):
    @property
    def method_name(self) -> str:
        return "make_waveforms"

    @property
    def condor_settings(self):
        condor_settings = self.shared_condor_settings
        additional_settings = {
            "request_memory": "2GB",
            "request_disk": "5GB",
            "request_cpus": self.argument_parser.get_default('ncpu'),
        }
        run_options = self.get_run_options()
        N_cpu = get_option_from_list('ncpu', run_options)
        if N_cpu is not None:
            additional_settings['request_cpus'] = N_cpu.argument[0]

        condor_settings.update(additional_settings)
        return condor_settings

    @property
    def argument_parser(self) -> argparse.ArgumentParser:
        return make_waveform_h5_arg_parser()

    def get_run_options(self, additional_options=None, **kwargs) -> List[Option]:
        """
        Get the command line options for the run_sampler executable
        :return:
        """
        run_options = [Option(key, value) for key, value in self.run_settings_dict.items()]
        # add additional options not in run settings dict
        run_options.extend(self.additional_options)

        if additional_options is not None:
            self.update_options_list(run_options, additional_options)

        self.raise_option_exists_error("directory", run_options)
        self.raise_option_exists_error("run_key", run_options)
        return run_options

    def get_inputs(self, relative_output_dir_name):
        # Since we have already transferred the input into the data_directory, we just need to pass data_directory
        return [
            Option('data-directory', 'data_directory', suppress=True),
            Option('command_line', 'command_line.sh', suppress=True),  # need to transfer this so it can be parsed
            Option('output-directory', relative_output_dir_name, suppress=True)
            ]

    def get_outputs(self, run_key):
        return [Option('waveform_h5', get_waveform_filename('.', run_key), suppress=True)]

    def add_job(self, output_directory, run_mode, cutoff, cutoff_mode, additional_options=None) -> None:
        run_options = self.get_run_options(additional_options)
        run_key = RunSamplerLayerManager.get_run_key(run_mode, cutoff)
        run_options.append(Option('run_key', run_key))
        run_options.append(Option('directory', '.'))
        if cutoff_mode == 'cycles':
            unit = 'cycles'

        elif cutoff_mode == 'times':
            unit = 'seconds'
        else:
            raise AssertionError("cutoff mode must be either 'cycles' or 'times'")

        relative_output_dir_name = RunSamplerLayerManager.get_output_filename_prefix(run_mode, cutoff, unit)

        inputs = self.get_inputs(relative_output_dir_name)
        outputs = self.get_outputs(run_key)

        self.layer += Node(
            arguments=run_options,
            inputs=inputs,
            outputs=outputs,
            variables={'run_prefix': RunSamplerLayerManager.get_output_filename_prefix(run_mode, cutoff, unit)}
        )



if __name__ == "__main__":
    
    # Set up arg parser
    parser = argparse.ArgumentParser(description="Generate and optionally submit a Condor DAG for the "
                                                 "time_domain_gw_inference pipeline "
                                                 "pipeline.")
    parser.add_argument("--config_file", required=True, help="Path to the configuration file")
    parser.add_argument("--output_directory", required=True,
                        help="The path to the output directory that contains the dag files, config file, submit "
                             "script, and run_sampler output files")
    parser.add_argument("--cycle_list", required=False, nargs='+', type=float,
                        help="Cycles before merger to cut data at, e.g. --cycle_list -3 0 1") 
    parser.add_argument("--times_list", required=False, nargs='+', type=float,
                        help="Times in seconds before merger to cut data at, e.g. --times_list -0.001 0 0.2")
    parser.add_argument("--full_only", action='store_true', help="Do not run pre or post, only run full")

    parser.add_argument("--submit", action="store_true", help="Submit the DAG to Condor (NOT IMPLEMENTED YET))")
    parser.add_argument("--run_in_place", action="store_true",
                        help="Skip condor file transfer and bank on a shared file system")

    args = parser.parse_args()
    
    # Check that inputs are right
    assert args.cycle_list is not None or args.times_list is not None, "must give a list of cutoffs"

    if not os.path.isfile(args.config_file):
        raise FileNotFoundError(f"Config file '{args.config_file}' not found.")
    
    # Format cutoff times and/or cycles
    cutoff_cycles = args.cycle_list if args.cycle_list is not None else []
    cutoff_times = args.times_list if args.times_list is not None else []
    
    # Create dag file
    pipeline_dag = RunSamplerDag(args.output_directory, args.config_file, args.submit,
                                 transfer_files=not args.run_in_place,
                                 cycle_list=cutoff_cycles, times_list=cutoff_times,
                                 full_only=args.full_only)

    pipeline_dag.create_pipeline_dag()
