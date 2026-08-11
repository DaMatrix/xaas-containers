from __future__ import annotations

import logging
import os
import shlex
import subprocess
from dataclasses import dataclass
from dataclasses import field

from xaas.actions.action import Action
from xaas.docker import VolumeMount
from xaas.config import BuildResult, TargetTriple, ArgumentsVariableEntry, DerivedDockerImageDescriptor, CPUArchitecture, BuildSystemArguments, ArgumentsVariableEntryType, XaaSConfig
from xaas.config import BuildSystem
from xaas.config import FeatureType
from xaas.config import RunConfig

from mashumaro.mixins.yaml import DataClassYAMLMixin

from xaas.util import ir_container_utils, shell


@dataclass
class CPUTuningFeatures(DataClassYAMLMixin):
    target_cpu: str | None = None
    target_features: str | None = None
    tune_cpu: str | None = None


@dataclass
class Config(RunConfig):
    build_results: list[BuildResult] = field(default_factory=list)
    target_flags: list[tuple[set, CPUTuningFeatures]] = field(default_factory=list)


class BuildGenerator(Action):
    def __init__(self):
        super().__init__(name="build", description="Builds the project with specified features")

    def execute(self, run_config: RunConfig) -> bool:
        logging.info(f"[{self.name}] Building project {run_config.project_name}")
        config_obj = Config.from_instance(run_config)

        # simple check for cuda runtime dependency
        if config_obj.may_contain_feature_boolean(FeatureType.CUDA):
            output = subprocess.run(
                f"grep CUDART_VERSION -nrw {config_obj.source_directory}",
                capture_output=True,
                shell=True,
                text=True,
            )
            if output.returncode == 0:
                # we need to use older CUDA - not necessary so far
                #raise NotImplementedError("We need to use older CUDA for this project")
                # TODO: jrabil: this doesn't seem to be necessary?
                pass

        status: bool = self._build_generic(config_obj, run_config.build_system)

        config_path = os.path.join(run_config.working_directory, "buildgen.yml")
        config_obj.save(config_path)

        return status

    def validate(self, run_config: RunConfig) -> bool:
        if not os.path.exists(run_config.source_directory):
            print(f"[{self.name}] Source location does not exist: {run_config.source_directory}")
            return False

        if run_config.build_system not in [BuildSystem.AUTOTOOLS, BuildSystem.CMAKE]:
            print(f"[{self.name}] Unsupported build system: {run_config.build_system}")
            return False

        return True

    def _build_generic(self, run_config: Config, build_system: BuildSystem) -> bool:
        containers = []

        # FIXME: test it for multiple combinations
        working_dir = os.path.join(run_config.working_directory)
        os.makedirs(working_dir, exist_ok=True)

        for effective_cpu_architecture in run_config.cpu_architectures:
            effective_run_config = run_config.for_target(effective_cpu_architecture)
            effective_base_builder_image, effective_base_runtime_image = effective_run_config.effective_docker_images()

            for states_boolean, states_select in ir_container_utils.get_all_feature_permutations(effective_run_config):
                build_dir = ir_container_utils.get_name_suffix_for_configuration(effective_cpu_architecture, states_boolean, states_select)

                arguments = ir_container_utils.get_effective_build_system_arguments(effective_run_config, states_boolean, states_select)

                builder_image_desc, runtime_image_desc = DerivedDockerImageDescriptor.create_builder_and_runtime(
                    effective_base_builder_image,
                    effective_base_runtime_image,
                    ir_container_utils.get_prepared_dependencies(effective_cpu_architecture, states_boolean, states_select, arguments))

                # TODO: jrabil: podman supports running containers with bind mounts from other images, so if we ever add support for podman that could make builds SIGNIFICANTLY faster
                prepared_builder_image = builder_image_desc.build_prepared_image(self.docker_runner)

                host_source_dir = run_config.source_directory

                new_dir = os.path.join(run_config.working_directory, "build", f"build_{build_dir}")
                os.makedirs(new_dir, exist_ok=True)

                container_source_dir = "/source"
                container_build_dir = "/build"

                # environment variables from the build arguments should be defined when running the build generator
                # TODO: jrabil: we probably want to have the environment variables be defined during compilation as well, should we store them in BuildResult?
                configure_environment = ArgumentsVariableEntry.reduce_to_dict(arguments.environment, self.docker_runner.get_image_env(prepared_builder_image))

                target_triple = TargetTriple.from_cpu_architecture(effective_cpu_architecture)

                logging.info(
                    f"Executing build in {new_dir}, image {prepared_builder_image}, combination: {states_boolean | states_select}"
                )

                configure_commands: shell.Command
                if build_system == BuildSystem.AUTOTOOLS:
                    configure_commands = self._build_command_autotools(
                        arguments, target_triple,
                        host_source_dir, new_dir,
                        container_source_dir, container_build_dir,
                    )
                elif build_system == BuildSystem.CMAKE:
                    configure_commands = self._build_command_cmake(
                        arguments, target_triple,
                        host_source_dir, new_dir,
                        container_source_dir, container_build_dir,
                    )
                else:
                    raise NotImplementedError(f"[{self.name}] Unsupported build system: {build_system}")

                configure_commands = shell.ListAnd([
                    configure_commands,
                    *[ shell.SimpleCommand(step) for step in run_config.additional_steps ],
                ])

                configure_cmd: str = configure_commands.to_shell(False)
                logging.info(f"[{self.name}] Running: {configure_cmd}")

                volumes = []
                volumes.append(
                    VolumeMount(
                        source=os.path.realpath(host_source_dir), target=container_source_dir, mode="ro"
                    )
                )
                volumes.append(VolumeMount(source=os.path.realpath(new_dir), target=container_build_dir))

                res = BuildResult(
                    directory=new_dir,
                    features_boolean=states_boolean,
                    features_select=states_select,

                    builder_image=builder_image_desc,
                    runtime_image=runtime_image_desc,

                    prepared_builder_image=prepared_builder_image,
                )

                containers.append(
                    (
                        self.docker_runner.run(
                            image=prepared_builder_image,
                            command=[ "bash", "-c", configure_cmd ],
                            environment=configure_environment,
                            mounts=volumes,
                            remove=False,
                            working_dir=container_build_dir,
                        ),
                        res,
                    )
                )

        all_successful = True
        logging.info(f"Waiting for {len(containers)} containers to finish")
        for container, result in containers:
            ret = container.wait()

            if ret["StatusCode"] != 0:
                logging.error(f"Build failed: {container.logs().decode()}")
                all_successful = False

            run_config.build_results.append(result)

            container.remove()

        if not all_successful:
            raise RuntimeError("Build failed")

        return True

    def _build_command_autotools(
            self,
            arguments: BuildSystemArguments,
            target_triple: TargetTriple,
            host_source_dir: str, host_build_dir: str,
            container_source_dir: str, container_build_dir: str,
    ) -> shell.Command:
        # extend the build system arguments to override the compiler binaries and compilation flags for the target
        modified_arguments = BuildSystemArguments.merge(
            BuildSystemArguments(property={
                "CC": ArgumentsVariableEntry(ArgumentsVariableEntryType.SET, arguments.effective_clang_path()),
                "CXX": ArgumentsVariableEntry(ArgumentsVariableEntryType.SET, arguments.effective_clangpp_path()),
                "F77": ArgumentsVariableEntry(ArgumentsVariableEntryType.SET, arguments.effective_flang_path()),

                "CFLAGS": ArgumentsVariableEntry(ArgumentsVariableEntryType.APPEND, f"--target={target_triple.value}", separator=" "),
                "CXXFLAGS": ArgumentsVariableEntry(ArgumentsVariableEntryType.APPEND, f"--target={target_triple.value}", separator=" "),
                "FFLAGS": ArgumentsVariableEntry(ArgumentsVariableEntryType.APPEND, f"--target={target_triple.value}", separator=" "),
            }),
            arguments)

        commands: list[shell.Command] = []

        # TODO: jrabil: only run this if the project actually has a configure script?
        if True:
            commands.append(shell.SimpleCommand([
                os.path.join(container_source_dir, "configure"),
                f"--srcdir={container_source_dir}",

                # properties from the build arguments should be defined as ./configure variables
                *[f"{name}={value}" for name, value in ArgumentsVariableEntry.reduce_to_dict(modified_arguments.property, None).items()],

                # additional ./configure arguments
                *modified_arguments.arguments,
            ]))

        commands.append(shell.SimpleCommand(["set", "-o", "pipefail"]))
        commands.append(shell.Pipeline([
            # generate the initial make dry-run log
            #   group it with an ' || true' so that even if this fails due to files without recipes, which seems to happen a lot during dry
            #   runs, it still exits successfully
            shell.ListOr([
                shell.SimpleCommand([
                    "make",
                    "--dry-run",
                    "--keep-going",
                    "--print-directory",
                ]),
                shell.SimpleCommand(["true"]),
            ]),

            # run compiledb on the initial make dry-run log to find all the compile commands, including any libtool part
            shell.SimpleCommand([
                XaaSConfig().tool_locations.compiledb_executable,
                "--output", "-",
                # make the command be a single string instead of a list to match CMake behavior
                "--command-style",
                # this is the default regex used by compiledb, but with an added case for 'libtool$'. this ensures that
                # for commands being proxied through libtool (of the style '/bin/bash ../libtool --tag=CC --mode=compile gcc [...]'),
                # we actually capture the entire command without the libtool part getting stripped away.
                "--regex-compile", r"^.*-?(libtool$|gcc|clang|cc|g\+\+|c\+\+|clang\+\+)-?.*(\.exe)?",
            ]),

            # run xaas_libtool_detector to determine the real libtool build commands from the original compiledb output
            shell.SimpleCommand([
                XaaSConfig().tool_locations.libtool_detector_executable,
                "--input", "/dev/stdin",
                "--output-normal", os.path.join(container_build_dir, "compile_commands.json"),
                "--output-lo", os.path.join(container_build_dir, ir_container_utils.CREATE_LIBTOOL_LOFILES_SCRIPT_NAME),
            ]),
        ]))

        return shell.ListAnd(commands)

    def _build_command_cmake(
            self,
            arguments: BuildSystemArguments,
            target_triple: TargetTriple,
            host_source_dir: str, host_build_dir: str,
            container_source_dir: str, container_build_dir: str,
    ) -> shell.Command:
        toolchain_file_name = "toolchain.cmake"
        toolchain_lines = [
            f"set(CMAKE_C_COMPILER \"{arguments.effective_clang_path()}\")",
            f"set(CMAKE_CXX_COMPILER \"{arguments.effective_clangpp_path()}\")",
            f"set(CMAKE_Fortran_COMPILER \"{arguments.effective_flang_path()}\")",
            f"set(CMAKE_C_FLAGS_INIT \"--target={target_triple.value}\")",
            f"set(CMAKE_CXX_FLAGS_INIT \"--target={target_triple.value}\")",
            f"set(CMAKE_Fortran_FLAGS_INIT \"--target={target_triple.value}\")",
        ]
        with open(os.path.join(host_build_dir, toolchain_file_name), "w") as toolchain_output:
            toolchain_output.write('\n'.join(toolchain_lines))

        return shell.SimpleCommand([
            "cmake",
            f"-DCMAKE_TOOLCHAIN_FILE={container_build_dir}/{toolchain_file_name}",
            "-DCMAKE_BUILD_TYPE=Release",
            "-DCMAKE_EXPORT_COMPILE_COMMANDS=ON",

            # properties from the build arguments should be defined as CMake variables
            *ArgumentsVariableEntry.reduce_to_cmake_args(arguments.property),

            # additional CMake arguments
            *arguments.arguments,

            "-S",
            container_source_dir,
            "-B",
            container_build_dir,
        ])
