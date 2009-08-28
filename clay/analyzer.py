from clay.xprint import *
from clay.error import *
from clay.multimethod import *
from clay.coreops import *
from clay.env import *
from clay.types import *
from clay.unify import *
from clay.evaluator import *



#
# RTValue, RTReference (RT for runtime)
#

class RTValue(object) :
    def __init__(self, type_) :
        self.type = type_

class RTReference(object) :
    def __init__(self, type_) :
        self.type = type_

def isRTValue(x) : return type(x) is RTValue
def isRTReference(x) : return type(x) is RTReference



#
# toRTValue, toRTLValue, toRTReference
#

toRTValue.register(RTValue)(lambda x : x)
toRTValue.register(RTReference)(lambda x : RTValue(x.type))
toRTValue.register(Value)(lambda x : RTValue(x.type))
toRTValue.register(Reference)(lambda x : RTValue(x.type))

toRTLValue.register(RTReference)(lambda x : x)
toRTLValue.register(Reference)(lambda x : RTReference(x.type))

toRTReference.register(RTReference)(lambda x : x)
toRTReference.register(RTValue)(lambda x : RTReference(x.type))
toRTReference.register(Value)(lambda x : RTReference(x.type))
toRTReference.register(Reference)(lambda x : RTReference(x.type))



#
# printer
#

xregister(RTValue, lambda x : XObject("RTValue", x.type))
xregister(RTReference, lambda x : XObject("RTReference", x.type))



#
# analyze
#

def analyze(expr, env, converter=(lambda x : x)) :
    try :
        contextPush(expr)
        return converter(analyze2(expr, env))
    finally :
        contextPop()



#
# analyze2
#

analyze2 = multimethod(errorMessage="invalid expression")

@analyze2.register(BoolLiteral)
def foo(x, env) :
    return boolToValue(x.value)

@analyze2.register(IntLiteral)
def foo(x, env) :
    return intToValue(x.value)

@analyze2.register(CharLiteral)
def foo(x, env) :
    return charToValue(x.value)

@analyze2.register(NameRef)
def foo(x, env) :
    return analyzeNameRef(lookupIdent(env, x.name))

@analyze2.register(Tuple)
def foo(x, env) :
    assert len(x.args) > 0
    first = analyze(x.args[0], env)
    if len(x.args) == 1 :
        return first
    if isType(first) or isCell(first) :
        rest = [analyze(y, env, toTypeOrCell) for y in x.args[1:]]
        return tupleType([first] + rest)
    else :
        args = [withContext(x.args[0], lambda : toRTReference(first))]
        args.extend([analyze(y, env, toRTReference) for y in x.args[1:]])
        return RTValue(tupleType([y.type for y in args]))

@analyze2.register(Indexing)
def foo(x, env) :
    thing = analyze(x.expr, env)
    return analyzeIndexing(thing, x.args, env)

@analyze2.register(Call)
def foo(x, env) :
    thing = analyze(x.expr, env)
    return analyzeCall(thing, x.args, env)

@analyze2.register(FieldRef)
def foo(x, env) :
    thing = analyze(x.expr, env, toRTRecordReference)
    i = recordFieldIndex(thing.type, x.name)
    fieldType = recordFieldTypes(thing.type)[i]
    return RTReference(fieldType)

@analyze2.register(TupleRef)
def foo(x, env) :
    thing = analyze(x.expr, env, toRTReferenceWithTypeTag(tupleTypeTag))
    nFields = len(thing.type.params)
    ensure((0 <= x.index < nFields), "tuple field index out of range")
    return RTReference(thing.type.params[x.index])

@analyze2.register(Dereference)
def foo(x, env) :
    return analyzeCall(primitives.pointerDereference, [x.expr], env)

@analyze2.register(AddressOf)
def foo(x, env) :
    return analyzeCall(primitives.addressOf, [x.expr], env)

@analyze2.register(StaticExpr)
def foo(x, env) :
    return evaluate(x.expr, env, toStatic)



#
# analyzeNameRef
#

analyzeNameRef = multimethod(defaultProc=(lambda x : x))

@analyzeNameRef.register(Reference)
def foo(x) :
    return toValue(x)

@analyzeNameRef.register(RTValue)
def foo(x) :
    return toRTReference(x)



#
# analyzeIndexing
#

analyzeIndexing = multimethod(errorMessage="invalid indexing")

@analyzeIndexing.register(Record)
def foo(x, args, env) :
    ensureArity(args, len(x.typeVars))
    typeParams = [evaluate(y, env, toStaticOrCell) for y in args]
    return recordType(x, typeParams)

@analyzeIndexing.register(primitives.Tuple)
def foo(x, args, env) :
    ensure(len(args) > 1, "tuple types need atleast two member types")
    elementTypes = [evaluate(y, env, toTypeOrCell) for y in args]
    return tupleType(elementTypes)

@analyzeIndexing.register(primitives.Array)
def foo(x, args, env) :
    ensureArity(args, 2)
    elementType = evaluate(args[0], env, toTypeOrCell)
    sizeValue = evaluate(args[1], env, toValueOrCell)
    return arrayType(elementType, sizeValue)

@analyzeIndexing.register(primitives.Pointer)
def foo(x, args, env) :
    ensureArity(args, 1)
    targetType = evaluate(args[0], env, toTypeOrCell)
    return pointerType(targetType)



#
# analyzeCall
#

analyzeCall = multimethod(errorMessage="invalid call")

@analyzeCall.register(Record)
def foo(x, args, env) :
    ensureArity(args, len(x.fields))
    recordEnv, cells = bindTypeVars(x.env, x.typeVars)
    fieldTypePatterns = computeFieldTypes(x.fields, recordEnv)
    argRefs = [analyze(y, env, toRTReference) for y in args]
    for typePattern, argRef, arg in zip(fieldTypePatterns, argRefs, args) :
        withContext(arg, lambda : matchType(typePattern, argRef.type))
    typeParams = resolveTypeVars(x.typeVars, cells)
    recType = recordType(x, typeParams)
    return RTValue(recType)

@analyzeCall.register(Procedure)
def foo(x, args, env) :
    actualArgs = [RTActualArgument(y, env) for y in args]
    result = matchCodeSignature(x.env, x.code, actualArgs)
    if type(result) is MatchFailure :
        result.signalError()
    bindingNames, bindingValues = result
    return analyzeCodeBody(x.code, x.env, bindingNames, bindingValues)

@analyzeCall.register(Overloadable)
def foo(x, args, env) :
    actualArgs = [RTActualArgument(y, env) for y in args]
    for y in x.overloads :
        result = matchCodeSignature(y.env, y.code, actualArgs)
        if type(result) is MatchFailure :
            continue
        bindingNames, bindingValues = result
        return analyzeCodeBody(y.code, y.env, bindingNames, bindingValues)
    error("no matching overload")



#
# analyze primitives
#

@analyzeCall.register(primitives.default)
def foo(x, args, env) :
    ensureArity(args, 1)
    t = analyze(args[0], env, toType)
    return RTValue(t)

@analyzeCall.register(primitives.typeSize)
def foo(x, args, env) :
    ensureArity(args, 1)
    analyze(args[0], env, toType)
    return RTValue(intType)



#
# analyze pointer primitives
#

@analyzeCall.register(primitives.addressOf)
def foo(x, args, env) :
    ensureArity(args, 1)
    valueRef = analyze(args[0], env, toRTLValue)
    return RTValue(pointerType(valueRef.type))

@analyzeCall.register(primitives.pointerDereference)
def foo(x, args, env) :
    ensureArity(args, 1)
    cell = Cell()
    analyze(args[0], env, toRTValueOfType(pointerType(cell)))
    return RTReference(cell.param)

@analyzeCall.register(primitives.pointerOffset)
def foo(x, args, env) :
    ensureArity(args, 2)
    cell = Cell()
    ptr = analyze(args[0], env, toRTReferenceOfType(pointerType(cell)))
    analyze(args[1], env, toRTReferenceOfType(intType))
    return RTValue(ptr.type)

@analyzeCall.register(primitives.pointerSubtract)
def foo(x, args, env) :
    ensureArity(args, 2)
    cell = Cell()
    analyze(args[0], env, toRTReferenceOfType(pointerType(cell)))
    analyze(args[1], env, toRTReferenceOfType(pointerType(cell)))
    return RTValue(intType)

@analyzeCall.register(primitives.pointerCast)
def foo(x, args, env) :
    ensureArity(args, 2)
    cell = Cell()
    targetType = analyze(args[0], env, toType)
    analyze(args[1], env, toRTValueOfType(pointerType(cell)))
    return RTValue(pointerType(targetType))

@analyzeCall.register(primitives.pointerCopy)
def foo(x, args, env) :
    ensureArity(args, 2)
    cell = Cell()
    analyze(args[0], env, toRTReferenceOfType(pointerType(cell)))
    analyze(args[1], env, toRTReferenceOfType(pointerType(cell)))
    return voidValue

@analyzeCall.register(primitives.pointerEquals)
def foo(x, args, env) :
    ensureArity(args, 2)
    cell = Cell()
    analyze(args[0], env, toRTReferenceOfType(pointerType(cell)))
    analyze(args[1], env, toRTReferenceOfType(pointerType(cell)))
    return RTValue(boolType)

@analyzeCall.register(primitives.pointerLesser)
def foo(x, args, env) :
    ensureArity(args, 2)
    cell = Cell()
    analyze(args[0], env, toRTReferenceOfType(pointerType(cell)))
    analyze(args[1], env, toRTReferenceOfType(pointerType(cell)))
    return RTValue(boolType)

@analyzeCall.register(primitives.allocateMemory)
def foo(x, args, env) :
    ensureArity(args, 1)
    analyze(args[0], env, toRTReferenceOfType(intType))
    return RTValue(pointerType(intType))

@analyzeCall.register(primitives.freeMemory)
def foo(x, args, env) :
    ensureArity(args, 1)
    analyze(args[0], env, toRTReferenceOfType(pointerType(intType)))
    return voidValue



#
# analyze tuple primitives
#

@analyzeCall.register(primitives.TupleType)
def foo(x, args, env) :
    ensureArity(args, 1)
    analyze(args[0], env, toType)
    return RTValue(boolType)

@analyzeCall.register(primitives.tuple)
def foo(x, args, env) :
    ensure(len(args) > 1, "tuples need atleast two members")
    valueRefs = [analyze(y, env, toRTReference) for y in args]
    tupType = tupleType([y.type for y in valueRefs])
    return RTValue(tupType)

@analyzeCall.register(primitives.tupleFieldCount)
def foo(x, args, env) :
    ensureArity(args, 1)
    analyze(args[0], env, toTypeWithTag(tupleTypeTag))
    return RTValue(intType)

@analyzeCall.register(primitives.tupleFieldRef)
def foo(x, args, env) :
    ensureArity(args, 2)
    thing = analyze(args[0], env, toRTReferenceWithTypeTag(tupleTypeTag))
    i = evaluate(args[1], env, toInt)
    nFields = len(thing.type.params)
    ensure((0 <= i < nFields), "tuple field index out of range")
    return RTReference(thing.type.params[i])



#
# analyze array primitives
#

@analyzeCall.register(primitives.array)
def foo(x, args, env) :
    ensureArity(args, 2)
    n = evaluate(args[0], env, toInt)
    v = analyze(args[1], env, toRTReference)
    return arrayType(v.type, intToValue(n))

@analyzeCall.register(primitives.arrayRef)
def foo(x, args, env) :
    ensureArity(args, 2)
    a = analyze(args[0], env, toRTReferenceWithTypeTag(arrayType))
    analyze(args[1], env, toRTValueOfType(intType))
    return RTReference(a.type.params[0])



#
# analyze record primitives
#

@analyzeCall.register(primitives.RecordType)
def foo(x, args, env) :
    ensureArity(args, 1)
    analyze(args[0], env, toType)
    return RTValue(boolType)

@analyzeCall.register(primitives.recordFieldCount)
def foo(x, args, env) :
    ensureArity(args, 1)
    analyze(args[0], env, toRecordType)
    return RTValue(intType)

@analyzeCall.register(primitives.recordFieldRef)
def foo(x, args, env) :
    ensureArity(args, 2)
    thing = analyze(args[0], env, toRTRecordReference)
    i = evaluate(args[1], env, toInt)
    nFields = len(thing.type.tag.fields)
    ensure((0 <= i < nFields), "record field index out of range")
    fieldType = recordFieldTypes(thing.type)[i]
    return RTReference(fieldType)



#
# analyze primitives util
#

def simpleOp(args, env, argTypes, returnType) :
    ensureArity(args, len(argTypes))
    for arg, argType in zip(args, argTypes) :
        analyze(arg, env, toRTReferenceOfType(argType))
    if returnType is None :
        return voidValue
    return RTValue(returnType)



#
# analyze bool primitives
#

@analyzeCall.register(primitives.boolCopy)
def foo(x, args, env) :
    return simpleOp(args, env, [boolType, boolType], None)

@analyzeCall.register(primitives.boolNot)
def foo(x, args, env) :
    return simpleOp(args, env, [boolType], boolType)



#
# analyze char primitives
#

@analyzeCall.register(primitives.charCopy)
def foo(x, args, env) :
    return simpleOp(args, env, [charType, charType], None)

@analyzeCall.register(primitives.charEquals)
def foo(x, args, env) :
    return simpleOp(args, env, [charType, charType], boolType)

@analyzeCall.register(primitives.charLesser)
def foo(x, args, env) :
    return simpleOp(args, env, [charType, charType], boolType)



#
# analyze int primitives
#

@analyzeCall.register(primitives.intCopy)
def foo(x, args, env) :
    return simpleOp(args, env, [intType, intType], None)

@analyzeCall.register(primitives.intEquals)
def foo(x, args, env) :
    return simpleOp(args, env, [intType, intType], boolType)

@analyzeCall.register(primitives.intLesser)
def foo(x, args, env) :
    return simpleOp(args, env, [intType, intType], boolType)

@analyzeCall.register(primitives.intAdd)
def foo(x, args, env) :
    return simpleOp(args, env, [intType, intType], intType)

@analyzeCall.register(primitives.intSubtract)
def foo(x, args, env) :
    return simpleOp(args, env, [intType, intType], intType)

@analyzeCall.register(primitives.intMultiply)
def foo(x, args, env) :
    return simpleOp(args, env, [intType, intType], intType)

@analyzeCall.register(primitives.intDivide)
def foo(x, args, env) :
    return simpleOp(args, env, [intType, intType], intType)

@analyzeCall.register(primitives.intModulus)
def foo(x, args, env) :
    return simpleOp(args, env, [intType, intType], intType)

@analyzeCall.register(primitives.intNegate)
def foo(x, args, env) :
    return simpleOp(args, env, [intType], intType)



#
# analyze float primitives
#

@analyzeCall.register(primitives.floatCopy)
def foo(x, args, env) :
    return simpleOp(args, env, [floatType, floatType], None)

@analyzeCall.register(primitives.floatEquals)
def foo(x, args, env) :
    return simpleOp(args, env, [floatType, floatType], boolType)

@analyzeCall.register(primitives.floatLesser)
def foo(x, args, env) :
    return simpleOp(args, env, [floatType, floatType], boolType)

@analyzeCall.register(primitives.floatAdd)
def foo(x, args, env) :
    return simpleOp(args, env, [floatType, floatType], floatType)

@analyzeCall.register(primitives.floatSubtract)
def foo(x, args, env) :
    return simpleOp(args, env, [floatType, floatType], floatType)

@analyzeCall.register(primitives.floatMultiply)
def foo(x, args, env) :
    return simpleOp(args, env, [floatType, floatType], floatType)

@analyzeCall.register(primitives.floatDivide)
def foo(x, args, env) :
    return simpleOp(args, env, [floatType, floatType], floatType)

@analyzeCall.register(primitives.floatNegate)
def foo(x, args, env) :
    return simpleOp(args, env, [floatType], floatType)



#
# analyze double primitives
#

@analyzeCall.register(primitives.doubleCopy)
def foo(x, args, env) :
    return simpleOp(args, env, [doubleType, doubleType], None)

@analyzeCall.register(primitives.doubleEquals)
def foo(x, args, env) :
    return simpleOp(args, env, [doubleType, doubleType], boolType)

@analyzeCall.register(primitives.doubleLesser)
def foo(x, args, env) :
    return simpleOp(args, env, [doubleType, doubleType], boolType)

@analyzeCall.register(primitives.doubleAdd)
def foo(x, args, env) :
    return simpleOp(args, env, [doubleType, doubleType], doubleType)

@analyzeCall.register(primitives.doubleSubtract)
def foo(x, args, env) :
    return simpleOp(args, env, [doubleType, doubleType], doubleType)

@analyzeCall.register(primitives.doubleMultiply)
def foo(x, args, env) :
    return simpleOp(args, env, [doubleType, doubleType], doubleType)

@analyzeCall.register(primitives.doubleDivide)
def foo(x, args, env) :
    return simpleOp(args, env, [doubleType, doubleType], doubleType)

@analyzeCall.register(primitives.doubleNegate)
def foo(x, args, env) :
    return simpleOp(args, env, [doubleType], doubleType)



#
# analyze conversion primitives
#

@analyzeCall.register(primitives.charToInt)
def foo(x, args, env) :
    return simpleOp(args, env, [charType], intType)

@analyzeCall.register(primitives.intToChar)
def foo(x, args, env) :
    return simpleOp(args, env, [intType], charType)

@analyzeCall.register(primitives.floatToInt)
def foo(x, args, env) :
    return simpleOp(args, env, [floatType], intType)

@analyzeCall.register(primitives.intToFloat)
def foo(x, args, env) :
    return simpleOp(args, env, [intType], floatType)

@analyzeCall.register(primitives.floatToDouble)
def foo(x, args, env) :
    return simpleOp(args, env, [floatType], doubleType)

@analyzeCall.register(primitives.doubleToFloat)
def foo(x, args, env) :
    return simpleOp(args, env, [doubleType], floatType)

@analyzeCall.register(primitives.doubleToInt)
def foo(x, args, env) :
    return simpleOp(args, env, [doubleType], intType)

@analyzeCall.register(primitives.intToDouble)
def foo(x, args, env) :
    return simpleOp(args, env, [intType], doubleType)



#
# analyze actual arguments
#

class RTActualArgument(object) :
    def __init__(self, expr, env) :
        self.expr = expr
        self.env = env
        self.result_ = analyze(self.expr, self.env)

    def asReference(self) :
        return withContext(self.expr, lambda : toRTReference(self.result_))

    def asValue(self) :
        return withContext(self.expr, lambda : toRTValue(self.result_))

    def asStatic(self) :
        return withContext(self.expr, lambda : toStatic(self.result_))



#
# analyzeCodeBody
#

_analysisTable = {}

class RecursiveAnalysisError(Exception) :
    pass

def analyzeCodeBody(code, env, bindingNames, bindingValues) :
    key = [code]
    for v in bindingValues :
        if type(v) in (RTValue, RTReference) :
            v = v.type
        key.append(v)
    key = tuple(key)
    result = _analysisTable.get(key)
    if result is not None :
        if result is False :
            raise RecursiveAnalysisError()
        return result
    try :
        result = None
        _analysisTable[key] = False
        env = extendEnv(env, bindingNames, bindingValues)
        result = analyzeCodeBody2(code, env)
        _analysisTable[key] = result
        return result
    finally :
        if result is None :
            del _analysisTable[key]

def analyzeCodeBody2(code, env) :
    if code.returnType is not None :
        returnType = evaluate(code.returnType, env, toType)
        if code.returnByRef :
            return RTReference(returnType)
        else :
            return RTValue(returnType)
    context = CodeContext2(code.returnByRef)
    result = analyzeStatement(code.body, env, context)
    if result is not None :
        return result
    return voidValue



#
# analyzeStatement
#

class CodeContext2(object) :
    def __init__(self, returnByRef) :
        self.returnByRef = returnByRef

def analyzeStatement(x, env, context) :
    return withContext(x, lambda : analyzeStatement2(x, env, context))



#
# analyzeStatement2
#

analyzeStatement2 = multimethod(errorMessage="invalid statement")

@analyzeStatement2.register(Block)
def foo(x, env, context) :
    env = Environment(env)
    for y in x.statements :
        if type(y) is LocalBinding :
            converter = toRTValue
            if y.type is not None :
                declaredType = evaluate(y.type, env, toType)
                converter = toRTValueOfType(declaredType)
            right = analyze(y.expr, env, converter)
            addIdent(env, y.name, right)
        else :
            result = analyzeStatement(y, env, context)
            if result is not None :
                return result

@analyzeStatement2.register(Assignment)
def foo(x, env, context) :
    # nothing to do
    pass

@analyzeStatement2.register(Return)
def foo(x, env, context) :
    if context.returnByRef :
        return analyze(x.expr, env, toRTReference)
    if x.expr is None :
        return voidValue
    return analyze(x.expr, env, toRTValue)

@analyzeStatement2.register(IfStatement)
def foo(x, env, context) :
    analyze(x.condition, env, toRTValueOfType(boolType))
    result = None
    failed = 0
    try :
        result = analyzeStatement(x.thenPart, env, context)
        if result is not None :
            return result
    except RecursiveAnalysisError :
        failed += 1
    if x.elsePart is None :
        return
    try :
        result = analyzeStatement(x.elsePart, env, context)
        if result is not None :
            return result
    except RecursiveAnalysisError :
        failed += 1
    if failed == 2 :
        raise RecursiveAnalysisError()

@analyzeStatement2.register(ExprStatement)
def foo(x, env, context) :
    # nothing to do
    pass



#
# remove temp name used for multimethod instances
#

del foo