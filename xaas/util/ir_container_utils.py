import itertools
from functools import reduce
from typing import Generator

from xaas.config import BuildSystemArguments, FeatureType, PartialRunConfig, DockerLayerPrepared, CPUArchitecture, DerivedDockerImageDescriptor


def get_all_feature_permutations(
        effective_run_config: PartialRunConfig,
) -> Generator[tuple[dict[FeatureType, bool], dict[str, str]]]:
    permutations_boolean = [
        [tuple([feature, False]), tuple([feature, True])] for feature in effective_run_config.features_boolean.keys()
    ]

    permutations_select = [
        [tuple([k, v]) for v in values] for k, values in effective_run_config.features_select.items()
    ]

    for states_boolean in itertools.product(*permutations_boolean):
        for states_select in itertools.product(*permutations_select):
            yield dict(states_boolean), dict(states_select)


def get_name_suffix_for_configuration(
        effective_cpu_architecture: CPUArchitecture,
        states_boolean: dict[FeatureType, bool],
        states_select: dict[str, str],
) -> str:
    return "_".join([
        effective_cpu_architecture.value,
        *[x.value for x, state in states_boolean.items() if state],
        *[f"{k}-{v}" for k, v in states_select.items()]
    ])


def get_effective_build_system_arguments(
        effective_run_config: PartialRunConfig,
        states_boolean: dict[FeatureType, bool],
        states_select: dict[str, str],
) -> BuildSystemArguments:
    return reduce(BuildSystemArguments.merge, [
        # universal build arguments
        effective_run_config.build_args,

        # include build arguments for the current feature selection
        *[effective_run_config.features_boolean[feat].args_for_state(state) for feat, state in states_boolean.items()],
        *[effective_run_config.features_select[feat][state] for feat, state in states_select.items()],
    ])


def get_prepared_dependencies(
        effective_cpu_architecture: CPUArchitecture,
        states_boolean: dict[FeatureType, bool],
        states_select: dict[str, str],
        effective_build_system_arguments: BuildSystemArguments,
) -> list[DockerLayerPrepared]:
    return [d.prepare(effective_cpu_architecture, states_boolean, states_select) for d in effective_build_system_arguments.dependencies]
