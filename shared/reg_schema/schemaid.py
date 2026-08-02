from enum import IntEnum

class SchemaID(IntEnum):
    MAIN = 0
    SERVICE = 1
    ID = 2
    PIPELINE = 3
    INPUT = 4
    STEPS = 5
    VERSION = 6
    CONDITION = 7
    IF = 8
    ELSE = 9
    ACTION = 10
    OPERATIONS = 11
    TRIGGER = 12
    VALUE = 13
    ELIF = 14
    ON_COMPLETE = 15
    ON_SUCCESS = 16
    ON_ERROR = 17