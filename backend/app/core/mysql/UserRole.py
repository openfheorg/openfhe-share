from enum import Enum


class UserRole(str, Enum):
    # Enum of possible user roles in the system.
    # These roles determine access levels and permissions.
    CLIENT = "CLIENT"
    INITIATOR = "INITIATOR"
    OBSERVER = "OBSERVER"
    ADMIN = "ADMIN"

    def __str__(self):
        return self.value
