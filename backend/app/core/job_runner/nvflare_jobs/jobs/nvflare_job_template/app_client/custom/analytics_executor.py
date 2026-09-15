from duality_wheel_runtime import build_component


class AnalyticsExecutor:
    def __new__(cls, *args, **kwargs):
        return build_component("analytics_executor_impl", "AnalyticsExecutor", *args, **kwargs)
