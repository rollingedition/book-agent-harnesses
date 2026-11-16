"""The errors unitcraft raises. Catch UnitError to handle all of them."""


class UnitError(Exception):
    """Base class for every error raised by unitcraft."""


class ParseError(UnitError):
    """The text is not a number followed by a unit."""


class UnknownUnitError(UnitError):
    """The unit symbol is not in the unit table."""


class IncompatibleUnitsError(UnitError):
    """Two units measure different dimensions, such as length and mass."""
