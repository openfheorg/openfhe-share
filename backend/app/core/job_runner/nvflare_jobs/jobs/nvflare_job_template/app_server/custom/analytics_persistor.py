from duality_wheel_runtime import build_component


class AnalyticsPersistor:
    def __new__(cls, *args, **kwargs):
        return build_component("analytics_persistor_impl", "AnalyticsPersistor", *args, **kwargs)
