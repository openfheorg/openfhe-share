from duality_wheel_runtime import build_component


class customSAG:
    def __new__(cls, *args, **kwargs):
        return build_component("duality_nvflare_workflows.customSAG", "customSAG", *args, **kwargs)
