"""Provider dispatch only; adapters are deliberately unimplemented."""
from . import isolved, prismhr, ukg_ready

ADAPTERS = {"prismhr": prismhr, "isolved": isolved, "ukg-ready": ukg_ready}
ENTITIES = ("company", "employee", "payroll")
