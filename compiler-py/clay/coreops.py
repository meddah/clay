from clay.error import *
from clay.multimethod import *

__all__ = ["equals", "toType", "toNativeInt", "toBool",
           "toValue", "toLValue", "toReference", "toValueOrReference",
           "toStatic"]



#
# equals
#

equals = multimethod(n=2, defaultProc=(lambda x, y : x is y))



#
# converters
#

toType = multimethod(errorMessage="type expected")

toBool = multimethod(errorMessage="bool expected")

toNativeInt = multimethod(errorMessage="int expected")

toValue = multimethod(errorMessage="invalid value")

toLValue = multimethod(errorMessage="invalid l-value")

toReference = multimethod(errorMessage="invalid reference")

toValueOrReference = multimethod(errorMessage="invalid value or reference")

toStatic = multimethod(defaultProc=(lambda x : x))