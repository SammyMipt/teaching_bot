from enum import Enum

class Role(str, Enum):
    OWNER = "owner"
    TA = "ta"
    STUDENT = "student"
    UNKNOWN = "unknown"
