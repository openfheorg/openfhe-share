from enum import Enum

class SupportedFilterSystem(str, Enum):
    # Enum of "filter systems" supported, as in set of filter screens that tap into certain forms of data
    DEFAULT = "DEFAULT"
    CANCER_TYPE = "CANCER_TYPE"

    def __str__(self) -> str:
        return self.value

    @classmethod
    def is_supported(cls, name: str | None) -> bool:
        if not name:
            return False
        try:
            cls(name)
            return True
        except ValueError:
            return False
