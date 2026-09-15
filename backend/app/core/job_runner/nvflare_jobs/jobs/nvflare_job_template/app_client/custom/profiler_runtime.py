from duality_wheel_runtime import build_component


class Profiler:
    def __new__(cls, *args, **kwargs):
        return build_component("duality_nvflare_apis.profiler", "Profiler", *args, **kwargs)


class ProfileSummaryPersistor:
    def __new__(cls, *args, **kwargs):
        return build_component("duality_nvflare_apis.profiler", "ProfileSummaryPersistor", *args, **kwargs)


class ProfileSummaryAggregator:
    def __new__(cls, *args, **kwargs):
        return build_component("duality_nvflare_apis.profiler", "ProfileSummaryAggregator", *args, **kwargs)
