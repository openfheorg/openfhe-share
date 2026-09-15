from duality_wheel_runtime import build_component


class AnalyticsAggregator:
    def __new__(cls, *args, **kwargs):
        return build_component("analytics_aggregator_impl", "AnalyticsAggregator", *args, **kwargs)
