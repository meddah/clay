import ctypes
from clay.xprint import *
from clay.cleanup import *
from clay.error import *
from clay.multimethod import *
from clay.coreops import *
from clay.env import *
from clay.types import *
from clay.unify import *
from clay.evaluator import *
from clay import analyzer
import clay.llvmwrapper as llvm



#
# global llvm data
#

llvmModuleInitialized = False
llvmFunction = None
llvmInitBuilder = None
llvmBuilder = None

def initLLVMModule() :
    global llvmModuleInitialized
    llvmModuleInitialized = True
    intPtrType = llvm.Type.pointer(llvmType(nativeIntType))
    ft = llvm.Type.function(llvm.Type.void(), [intPtrType])
    f = llvm.Function.new(llvmModule(), ft, "_clay_print_int")
    f.linkage = llvm.LINKAGE_EXTERNAL

    boolPtrType = llvm.Type.pointer(llvmType(boolType))
    ft = llvm.Type.function(llvm.Type.void(), [boolPtrType])
    f = llvm.Function.new(llvmModule(), ft, "_clay_print_bool")
    f.linkage = llvm.LINKAGE_EXTERNAL

def _cleanCompilerLLVMGlobals() :
    global llvmModuleInitialized, llvmFunction, llvmInitBuilder, llvmBuilder
    llvmModuleInitialized = False
    llvmFunction = None
    llvmInitBuilder = None
    llvmBuilder = None

installGlobalsCleanupHook(_cleanCompilerLLVMGlobals)



#
# RTValue, RTReference
#

class RTValue(object) :
    def __init__(self, type_, llvmValue) :
        self.type = type_
        self.llvmValue = llvmValue

class RTReference(object) :
    def __init__(self, type_, llvmValue) :
        self.type = type_
        self.llvmValue = llvmValue

def isRTValue(x) : return type(x) is RTValue
def isRTReference(x) : return type(x) is RTReference



#
# toStatic
#

@toStatic.register(RTValue)
def foo(x) :
    error("invalid static value")

@toStatic.register(RTReference)
def foo(x) :
    error("invalid static value")



#
# temp values
#

class RTTempsBlock(object) :
    def __init__(self) :
        self.temps = []

    def add(self, temp) :
        self.temps.append(temp)

    def newTemp(self, type_) :
        llt = llvmType(type_)
        ptr = llvmInitBuilder.alloca(llt)
        value = RTValue(type_, ptr)
        self.add(value)
        return value

    def detachTemp(self, temp) :
        for i, x in enumerate(self.temps) :
            if x is temp :
                self.temps.pop(i)
                return
        assert False

    def cleanup(self) :
        for temp in reversed(self.temps) :
            rtValueDestroy(temp)

_rtTempsBlocks = []

def pushRTTempsBlock() :
    block = RTTempsBlock()
    _rtTempsBlocks.append(block)

def popRTTempsBlock() :
    block = _rtTempsBlocks.pop()
    block.cleanup()

def detachFromRTTempsBlock(temp) :
    _rtTempsBlocks[-1].detachTemp(temp)

def tempRTValue(type_) :
    return _rtTempsBlocks[-1].newTemp(type_)



#
# toRTValue, toRTLValue, toRTReference, toRTValueOrReference
#

toRTValue = multimethod(errorMessage="invalid value")

@toRTValue.register(RTValue)
def foo(x) :
    return x

@toRTValue.register(RTReference)
def foo(x) :
    temp = tempRTValue(x.type)
    rtValueCopy(temp, x)
    return temp

@toRTValue.register(Value)
def foo(x) :
    if isBoolType(x.type) :
        constValue = llvm.Constant.int(llvmType(x.type), int(x.buf.value))
    elif isIntegerType(x.type) :
        constValue = llvm.Constant.int(llvmType(x.type), x.buf.value)
    else :
        error("unsupported type in toRTValue")
    temp = tempRTValue(x.type)
    llvmBuilder.store(constValue, temp.llvmValue)
    return temp


toRTLValue = multimethod(errorMessage="invalid reference")

@toRTLValue.register(RTReference)
def foo(x) :
    return x


toRTReference = multimethod(errorMessage="invalid reference")

@toRTReference.register(RTReference)
def foo(x) :
    return x

@toRTReference.register(RTValue)
def foo(x) :
    return RTReference(x.type, x.llvmValue)

@toRTReference.register(Value)
def foo(x) :
    return toRTReference(toRTValue(x))


toRTValueOrReference = multimethod(errorMessage="invalid value or reference")

@toRTValueOrReference.register(RTValue)
def foo(x) :
    return x

@toRTValueOrReference.register(RTReference)
def foo(x) :
    return x

@toRTValueOrReference.register(Value)
def foo(x) :
    return toRTValue(x)



#
# type checking converters
#

def toRTReferenceWithTag(tag) :
    def f(x) :
        r = toRTReference(x)
        ensure(r.type.tag is tag, "type mismatch")
        return r
    return f

def toRTIntegerReference(x) :
    r = toRTReference(x)
    ensure(isIntegerType(r.type), "integer type expected")
    return r

def toRTFloatingPointReference(x) :
    r = toRTReference(x)
    ensure(isFloatingPointType(r.type), "floating point type expected")
    return r

def toRTNumericReference(x) :
    r = toRTReference(x)
    t = r.type
    ensure(isType(t) and (isIntegerType(t) or isFloatingPointType(t)),
           "numeric type expected")
    return r

def toRTRecordReference(x) :
    r = toRTReference(x)
    ensure(isRecordType(r.type), "record type expected")
    return r



#
# type pattern matching converters
#

def toRTValueOfType(pattern) :
    def f(x) :
        v = toRTValue(x)
        matchType(pattern, v.type)
        return v
    return f

def toRTLValueOfType(pattern) :
    def f(x) :
        v = toRTLValue(x)
        matchType(pattern, v.type)
        return v
    return f

def toRTReferenceOfType(pattern) :
    def f(x) :
        r = toRTReference(x)
        matchType(pattern, r.type)
        return r
    return f

def toRTValueOrReferenceOfType(pattern) :
    def f(x) :
        y = toRTValueOrReference(x)
        matchType(pattern, y.type)
        return y
    return f



#
# printer
#

xregister(RTValue, lambda x : XObject("RTValue", x.type))
xregister(RTReference, lambda x : XObject("RTReference", x.type))



#
# core value operations
#

def _compileBuiltin(builtinName, args) :
    env = Environment(primitivesEnv)
    variables = [Identifier("v%d" % i) for i in range(len(args))]
    for variable, arg in zip(variables, args) :
        addIdent(env, variable, arg)
    argNames = map(NameRef, variables)
    builtin = NameRef(Identifier(builtinName))
    call = Call(builtin, argNames)
    return compile(call, env)

def rtValueInit(a) :
    if isSimpleType(a.type) :
        return
    _compileBuiltin("init", [a])

def rtValueCopy(dest, src) :
    assert equals(dest.type, src.type)
    if isSimpleType(dest.type) :
        temp = llvmBuilder.load(src.llvmValue)
        llvmBuilder.store(temp, dest.llvmValue)
        return
    _compileBuiltin("copy", [dest, src])

def rtValueAssign(dest, src) :
    assert equals(dest.type, src.type)
    if isSimpleType(dest.type) :
        temp = llvmBuilder.load(src.llvmValue)
        llvmBuilder.store(temp, dest.llvmValue)
        return
    _compileBuiltin("assign", [dest, src])

def rtValueDestroy(a) :
    if isSimpleType(a.type) :
        return
    _compileBuiltin("destroy", [a])



#
# utility operations
#

def rtTupleFieldRef(a, i) :
    assert isRTReference(a) and isTupleType(a.type)
    ensure((0 <= i < len(a.type.params)), "tuple index out of range")
    elementType = toType(a.type.params[i])
    zero = llvm.Constant.int(llvmType(nativeIntType), 0)
    iValue = llvm.Constant.int(llvmType(nativeIntType), i)
    elementPtr = llvmBuilder.gep(a.llvmValue, [zero, iValue])
    return RTReference(elementType, elementPtr)

def rtMakeTuple(argRefs) :
    t = tupleType([x.type for x in argRefs])
    value = tempRTValue(t)
    valueRef = toRTReference(value)
    for i, argRef in enumerate(argRefs) :
        left = rtTupleFieldRef(valueRef, i)
        rtValueCopy(left, argRef)
    return value

def rtRecordFieldRef(a, i) :
    assert isRTReference(a) and isRecordType(a.type)
    nFields = len(recordValueArgs(a.type.tag))
    ensure((0 <= i < nFields), "record field index out of range")
    fieldType = recordFieldTypes(a.type)[i]
    zero = llvm.Constant.int(llvmType(nativeIntType), 0)
    iValue = llvm.Constant.int(llvmType(nativeIntType), i)
    fieldPtr = llvmBuilder.gep(a.llvmValue, [zero, iValue])
    return RTReference(fieldType, fieldPtr)

def rtMakeRecord(recType, argRefs) :
    value = tempRTValue(recType)
    valueRef = toRTReference(value)
    for i, argRef in enumerate(argRefs) :
        left = rtRecordFieldRef(valueRef, i)
        rtValueCopy(left, argRef)
    return value



#
# compile
#

def compile(expr, env, converter=(lambda x : x)) :
    contextPush(expr)
    result = compile2(expr, env)
    result = converter(result)
    contextPop()
    return result



#
# compile2
#

compile2 = multimethod(errorMessage="invalid expression")

@compile2.register(BoolLiteral)
def foo(x, env) :
    return boolToValue(x.value)

@compile2.register(IntLiteral)
def foo(x, env) :
    return intToValue(x.value)

@compile2.register(NameRef)
def foo(x, env) :
    return compileNameRef(lookupIdent(env, x.name))

@compile2.register(Tuple)
def foo(x, env) :
    assert len(x.args) > 0
    cargs = [compile(y, env) for y in x.args]
    if len(x.args) == 1 :
        return cargs[0]
    if isType(cargs[0]) or isCell(cargs[0]) :
        elementTypes = convertObjects(toTypeOrCell, cargs, x.args)
        return tupleType(elementTypes)
    else :
        argRefs = convertObjects(toRTReference, cargs, x.args)
        return rtMakeTuple(argRefs)

@compile2.register(Indexing)
def foo(x, env) :
    thing = compile(x.expr, env)
    return compileIndexing(thing, x.args, env)

@compile2.register(Call)
def foo(x, env) :
    thing = compile(x.expr, env)
    return compileCall(thing, x.args, env)

@compile2.register(FieldRef)
def foo(x, env) :
    thing = compile(x.expr, env)
    thingRef = convertObject(toRTRecordReference, thing, x.expr)
    return rtRecordFieldRef(thingRef, recordFieldIndex(thing.type, x.name))

@compile2.register(TupleRef)
def foo(x, env) :
    thing = compile(x.expr, env)
    toRTTupleReference = toRTReferenceWithTag(tupleTag)
    thingRef = convertObject(toRTTupleReference, thing, x.expr)
    return rtTupleFieldRef(thingRef, x.index)

@compile2.register(Dereference)
def foo(x, env) :
    return compileCall(primitives.pointerDereference(), [x.expr], env)

@compile2.register(AddressOf)
def foo(x, env) :
    return compileCall(primitives.addressOf(), [x.expr], env)

@compile2.register(UnaryOpExpr)
def foo(x, env) :
    return compile(convertUnaryOpExpr(x), env)

@compile2.register(BinaryOpExpr)
def foo(x, env) :
    return compile(convertBinaryOpExpr(x), env)

@compile2.register(NotExpr)
def foo(x, env) :
    v, = rtLoadLLVM([x.expr], env, [boolType])
    zero = llvm.Constant.int(llvmType(boolType), 0)
    flag = llvmBuilder.icmp(llvm.ICMP_EQ, v, zero)
    flag = llvmBuilder.zext(flag, llvmType(boolType))
    return rtResult(boolType, flag)

@compile2.register(AndExpr)
def foo(x, env) :
    result = tempRTValue(boolType)
    trueBlock = llvmFunction.append_basic_block("andOne")
    falseBlock = llvmFunction.append_basic_block("andTwo")
    mergeBlock = llvmFunction.append_basic_block("andMerge")

    v1Ref = compile(x.expr1, env, toRTReferenceOfType(boolType))
    v1 = llvmBuilder.load(v1Ref.llvmValue)
    zero = llvm.Constant.int(llvmType(boolType), 0)
    b1 = llvmBuilder.icmp(llvm.ICMP_NE, v1, zero)
    llvmBuilder.cbranch(b1, trueBlock, falseBlock)

    llvmBuilder.position_at_end(trueBlock)
    v2Ref = compile(x.expr2, env, toRTReferenceOfType(boolType))
    v2 = llvmBuilder.load(v2Ref.llvmValue)
    llvmBuilder.store(v2, result.llvmValue)
    llvmBuilder.branch(mergeBlock)

    llvmBuilder.position_at_end(falseBlock)
    llvmBuilder.store(v1, result.llvmValue)
    llvmBuilder.branch(mergeBlock)

    llvmBuilder.position_at_end(mergeBlock)
    return result

@compile2.register(OrExpr)
def foo(x, env) :
    result = tempRTValue(boolType)
    trueBlock = llvmFunction.append_basic_block("orOne")
    falseBlock = llvmFunction.append_basic_block("orTwo")
    mergeBlock = llvmFunction.append_basic_block("orMerge")

    v1Ref = compile(x.expr1, env, toRTReferenceOfType(boolType))
    v1 = llvmBuilder.load(v1Ref.llvmValue)
    zero = llvm.Constant.int(llvmType(boolType), 0)
    b1 = llvmBuilder.icmp(llvm.ICMP_NE, v1, zero)
    llvmBuilder.cbranch(b1, trueBlock, falseBlock)

    llvmBuilder.position_at_end(trueBlock)
    llvmBuilder.store(v1, result.llvmValue)
    llvmBuilder.branch(mergeBlock)

    llvmBuilder.position_at_end(falseBlock)
    v2Ref = compile(x.expr2, env, toRTReferenceOfType(boolType))
    v2 = llvmBuilder.load(v2Ref.llvmValue)
    llvmBuilder.store(v2, result.llvmValue)
    llvmBuilder.branch(mergeBlock)

    llvmBuilder.position_at_end(mergeBlock)
    return result

@compile2.register(StaticExpr)
def foo(x, env) :
    return evaluate(x.expr, env, toStatic)

@compile2.register(SCExpression)
def foo(x, env) :
    return compile(x.expr, x.env)



#
# compileNameRef
#

compileNameRef = multimethod(defaultProc=(lambda x : x))

@compileNameRef.register(Reference)
def foo(x) :
    return toValue(x)

@compileNameRef.register(RTValue)
def foo(x) :
    return toRTReference(x)



#
# compileIndexing
#

compileIndexing = multimethod(errorMessage="invalid indexing")

@compileIndexing.register(Record)
def foo(x, args, env) :
    ensureArity(args, len(x.typeVars))
    typeParams = [compile(y, env, toStaticOrCell) for y in args]
    return recordType(x, typeParams)

@compileIndexing.register(primitives.Tuple)
def foo(x, args, env) :
    ensure(len(args) > 1, "tuple types need atleast two member types")
    elementTypes = [compile(y, env, toTypeOrCell) for y in args]
    return tupleType(elementTypes)

@compileIndexing.register(primitives.Array)
def foo(x, args, env) :
    ensureArity(args, 2)
    elementType = compile(args[0], env, toTypeOrCell)
    sizeValue = compile(args[1], env, toValueOrCell)
    return arrayType(elementType, sizeValue)

@compileIndexing.register(primitives.Pointer)
def foo(x, args, env) :
    ensureArity(args, 1)
    pointeeType = compile(args[0], env, toTypeOrCell)
    return pointerType(pointeeType)



#
# compileCall
#

compileCall = multimethod(errorMessage="invalid call")

@compileCall.register(Type)
def foo(x, args, env) :
    ensure(isRecordType(x), "only record type constructors are supported")
    fieldTypes = recordFieldTypes(x)
    ensureArity(args, len(fieldTypes))
    argRefs = []
    for arg, fieldType in zip(args, fieldTypes) :
        argRef = compile(arg, env, toRTReferenceOfType(fieldType))
        argRefs.append(argRef)
    return rtMakeRecord(x, argRefs)

@compileCall.register(Record)
def foo(x, args, env) :
    actualArgs = [RTActualArgument(y, env) for y in args]
    result = matchRecordInvoke(x, actualArgs)
    if type(result) is InvokeError :
        result.signalError()
    assert type(result) is InvokeBindings
    recType = recordType(x, result.typeParams)
    return rtMakeRecord(recType, result.params)

@compileCall.register(Procedure)
def foo(x, args, env) :
    actualArgs = [RTActualArgument(y, env) for y in args]
    result = matchInvoke(x.code, x.env, actualArgs)
    if type(result) is InvokeError :
        result.signalError()
    assert type(result) is InvokeBindings
    return compileInvoke(x.name.s, x.code, x.env, result)

@compileCall.register(Overloadable)
def foo(x, args, env) :
    actualArgs = [RTActualArgument(y, env) for y in args]
    for y in x.overloads :
        result = matchInvoke(y.code, y.env, actualArgs)
        if type(result) is InvokeError :
            continue
        assert type(result) is InvokeBindings
        return compileInvoke(x.name.s, y.code, y.env, result)
    error("no matching overload")



#
# utility methods for compiling primitives
#

def rtLoadRefs(args, env, types) :
    ensureArity(args, len(types))
    argRefs = []
    for arg, type_ in zip(args, types) :
        argRef = compile(arg, env, toRTReferenceOfType(type_))
        argRefs.append(argRef)
    return argRefs

def rtLoadLLVM(args, env, types) :
    argRefs = rtLoadRefs(args, env, types)
    return [llvmBuilder.load(x.llvmValue) for x in argRefs]

def rtResult(type_, llvmValue) :
    result = tempRTValue(type_)
    llvmBuilder.store(llvmValue, result.llvmValue)
    return result



#
# compilePrimitiveCall
#

def compilePrimitiveCall(primitive, inRefs, outputType) :
    func = primitiveFunc(primitive, [x.type for x in inRefs], outputType)
    llvmArgs = [inRef.llvmValue for inRef in inRefs]
    if not isVoidType(outputType) :
        result = tempRTValue(outputType)
        llvmArgs.append(result.llvmValue)
    else :
        result = voidValue
    llvmBuilder.call(func, llvmArgs)
    return result



#
# compile primitives
#

@compileCall.register(primitives._print)
def foo(x, args, env) :
    ensureArity(args, 1)
    x = compile(args[0], env, toRTReference)
    if x.type == boolType :
        f = llvmModule().get_function_named("_clay_print_bool")
    elif x.type == nativeIntType :
        f = llvmModule().get_function_named("_clay_print_int")
    else :
        error("printing support not available for this type")
    llvmBuilder.call(f, [x.llvmValue])
    return voidValue

@compileCall.register(primitives.default)
def foo(x, args, env) :
    ensureArity(args, 1)
    t = compile(args[0], env, toType)
    v = tempRTValue(t)
    rtValueInit(v)
    return v

@compileCall.register(primitives.typeSize)
def foo(x, args, env) :
    ensureArity(args, 1)
    t = compile(args[0], env, toType)
    ptr = llvm.Constant.null(llvmType(pointerType(t)))
    one = llvm.Constant.int(llvmType(nativeIntType), 1)
    offsetPtr = llvmBuilder.gep(ptr, [one])
    offsetInt = llvmBuilder.ptrtoint(offsetPtr, llvmType(nativeIntType))
    v = tempRTValue(nativeIntType)
    llvmBuilder.store(offsetInt, v.llvmValue)
    return v

@compileCall.register(primitives.primitiveCopy)
def foo(x, args, env) :
    ensureArity(args, 2)
    cell = Cell()
    destRef = compile(args[0], env, toRTReferenceOfType(cell))
    srcRef = compile(args[1], env, toRTReferenceOfType(cell))
    ensure(isSimpleType(cell.param), "expected simple type")
    return compilePrimitiveCall(x, [destRef, srcRef], voidType)



#
# compile pointer primitives
#

@compileCall.register(primitives.addressOf)
def foo(x, args, env) :
    ensureArity(args, 1)
    valueRef = compile(args[0], env, toRTLValue)
    ptrValue = tempRTValue(pointerType(valueRef.type))
    llvmBuilder.store(valueRef.llvmValue, ptrValue.llvmValue)
    return ptrValue

@compileCall.register(primitives.pointerDereference)
def foo(x, args, env) :
    cell = Cell()
    ptr, = rtLoadLLVM(args, env, [pointerType(cell)])
    return RTReference(cell.param, ptr)

@compileCall.register(primitives.pointerToInt)
def foo(x, args, env) :
    ensureArity(args, 2)
    cell = Cell()
    ptrRef = compile(args[0], env, toRTReferenceOfType(pointerType(cell)))
    outType = compile(args[1], env, toIntegerType)
    return compilePrimitiveCall(x, [ptrRef], outType)

@compileCall.register(primitives.intToPointer)
def foo(x, args, env) :
    ensureArity(args, 2)
    intRef = compile(args[0], env, toRTIntegerReference)
    pointeeType = compile(args[1], env, toType)
    return compilePrimitiveCall(x, [intRef], pointerType(pointeeType))

@compileCall.register(primitives.pointerCast)
def foo(x, args, env) :
    ensureArity(args, 2)
    cell = Cell()
    targetType = compile(args[0], env, toType)
    targetPtrType = pointerType(targetType)
    ptrRef = compile(args[1], env, toRTReferenceOfType(pointerType(cell)))
    ptr = llvmBuilder.load(ptrRef.llvmValue)
    ptr = llvmBuilder.bitcast(ptr, llvmType(targetPtrType))
    return rtResult(targetPtrType, ptr)

@compileCall.register(primitives.allocateMemory)
def foo(x, args, env) :
    ensureArity(args, 2)
    type_ = compile(args[0], env, toType)
    nRef = compile(args[1], env, toRTReferenceOfType(nativeIntType))
    return compilePrimitiveCall(x, [nRef], pointerType(type_))

@compileCall.register(primitives.freeMemory)
def foo(x, args, env) :
    ensureArity(args, 1)
    cell = Cell()
    ptrRef = compile(args[0], toRTReferenceOfType(pointerType(cell)))
    return compilePrimitiveCall(x, [ptrRef], voidType)



#
# compile tuple primitives
#

@compileCall.register(primitives.TupleType)
def foo(x, args, env) :
    ensureArity(args, 1)
    t = compile(args[0], env, toType)
    return toRTValue(boolToValue(isTupleType(t)))

@compileCall.register(primitives.tuple)
def foo(x, args, env) :
    ensure(len(args) > 1, "tuples need atleast two members")
    cargs = [compile(y, env) for y in args]
    argRefs = convertObjects(toRTReference, cargs, args)
    return rtMakeTuple(argRefs)

@compileCall.register(primitives.tupleFieldCount)
def foo(x, args, env) :
    ensureArity(args, 1)
    t = compile(args[0], env, toTypeWithTag(tupleTag))
    return toRTValue(intToValue(len(t.params)))

@compileCall.register(primitives.tupleFieldRef)
def foo(x, args, env) :
    ensureArity(args, 2)
    cargs = [compile(y, env) for y in args]
    converter = toRTReferenceWithTag(tupleTag)
    tupleRef = convertObject(converter, cargs[0], args[0])
    i = convertObject(toNativeInt, cargs[1], args[1])
    return rtTupleFieldRef(tupleRef, i)



#
# compile array primitives
#

@compileCall.register(primitives.array)
def foo(x, args, env) :
    ensureArity(args, 2)
    cargs = [compile(y, env) for y in args]
    elementType = convertObject(toType, cargs[0], args[0])
    n = convertObject(toNativeInt, cargs[1], args[1])
    a = tempRTValue(arrayType(elementType, intToValue(n)))
    rtValueInit(a)
    return a

@compileCall.register(primitives.arrayRef)
def foo(x, args, env) :
    ensureArity(args, 2)
    cargs = [compile(y, env) for y in args]
    converter = toRTReferenceWithTag(arrayTag)
    aRef = convertObject(converter, cargs[0], args[0])
    iRef = convertObject(toRTReferenceOfType(nativeIntType), cargs[1], args[1])
    i = llvmBuilder.load(iRef.llvmValue)
    zero = llvm.Constant.int(llvmType(nativeIntType), 0)
    element = llvmBuilder.gep(aRef.llvmValue, [zero, i])
    return RTReference(aRef.type.params[0], element)



#
# compile record primitives
#

@compileCall.register(primitives.RecordType)
def foo(x, args, env) :
    ensureArity(args, 1)
    t = compile(args[0], env, toType)
    return toRTValue(boolToValue(isRecordType(t)))

@compileCall.register(primitives.recordFieldCount)
def foo(x, args, env) :
    ensureArity(args, 1)
    t = compile(args[0], env, toRecordType)
    return toRTValue(intToValue(len(t.tag.fields)))

@compileCall.register(primitives.recordFieldRef)
def foo(x, args, env) :
    ensureArity(args, 2)
    cargs = [compile(y, env) for y in args]
    recRef = convertObject(toRTRecordReference, cargs[0], args[0])
    i = convertObject(toNativeInt, cargs[1], args[1])
    return rtRecordFieldRef(recRef, i)



#
# compile numeric primitives
#

def _compile2NumericArgs(args, env) :
    ensureArity(args, 2)
    a, b = [compile(x, env, toRTNumericReference) for x in args]
    ensure(a.type == b.type, "argument types mismatch")
    return (a, b)
    
@compileCall.register(primitives.numericEquals)
def foo(x, args, env) :
    x1, x2 = _compile2NumericArgs(args, env)
    return compilePrimitiveCall(x, [x1, x2], boolType)

@compileCall.register(primitives.numericLesser)
def foo(x, args, env) :
    x1, x2 = _compile2NumericArgs(args, env)
    return compilePrimitiveCall(x, [x1, x2], boolType)

@compileCall.register(primitives.numericAdd)
def foo(x, args, env) :
    x1, x2 = _compile2NumericArgs(args, env)
    return compilePrimitiveCall(x, [x1, x2], x1.type)

@compileCall.register(primitives.numericSubtract)
def foo(x, args, env) :
    x1, x2 = _compile2NumericArgs(args, env)
    return compilePrimitiveCall(x, [x1, x2], x1.type)

@compileCall.register(primitives.numericMultiply)
def foo(x, args, env) :
    x1, x2 = _compile2NumericArgs(args, env)
    return compilePrimitiveCall(x, [x1, x2], x1.type)

@compileCall.register(primitives.numericDivide)
def foo(x, args, env) :
    x1, x2 = _compile2NumericArgs(args, env)
    return compilePrimitiveCall(x, [x1, x2], x1.type)

@compileCall.register(primitives.numericRemainder)
def foo(x, args, env) :
    x1, x2 = _compile2NumericArgs(args, env)
    return compilePrimitiveCall(x, [x1, x2], x1.type)

@compileCall.register(primitives.numericNegate)
def foo(x, args, env) :
    ensureArity(args, 1)
    x1 = compile(args[0], env, toRTNumericReference)
    return compilePrimitiveCall(x, [x1], x1.type)

@compileCall.register(primitives.numericConvert)
def foo(x, args, env) :
    ensureArity(args, 2)
    destType = compile(args[0], env, toNumericType)
    src = compile(args[1], env, toRTNumericReference)
    return compilePrimitiveCall(x, [src], destType)



#
# compile actual arguments
#

class RTActualArgument(object) :
    def __init__(self, expr, env) :
        self.expr = expr
        self.env = env
        self.result_ = compile(self.expr, self.env)

    def asReference(self) :
        return withContext(self.expr, lambda : toRTReference(self.result_))

    def asStatic(self) :
        return withContext(self.expr, lambda : toStatic(self.result_))



#
# compileInvoke
#

def compileInvoke(name, code, env, bindings) :
    compiledCode = compileCode(name, code, env, bindings)
    llvmArgs = []
    for p in bindings.params :
        llvmArgs.append(p.llvmValue)
    if isVoidType(compiledCode.returnType) :
        llvmBuilder.call(compiledCode.llvmFunc, llvmArgs)
        return voidValue
    else :
        t = compiledCode.returnType
        if compiledCode.returnByRef :
            t = pointerType(t)
        retVal = tempRTValue(t)
        llvmArgs.append(retVal.llvmValue)
        llvmBuilder.call(compiledCode.llvmFunc, llvmArgs)
        if compiledCode.returnByRef :
            ptr = llvmBuilder.load(retVal.llvmValue)
            return RTReference(compiledCode.returnType, ptr)
        else :
            return retVal



#
# compileCode
#

class CompiledCode(object) :
    def __init__(self, returnByRef, returnType, llvmFunc) :
        self.returnByRef = returnByRef
        self.returnType = returnType
        self.llvmFunc = llvmFunc

_compiledCodeTable = {}

def _cleanupCompiledCodeTable() :
    global _compiledCodeTable
    _compiledCodeTable = {}

installGlobalsCleanupHook(_cleanupCompiledCodeTable)

def compileCode(name, code, env, bindings) :
    key = tuple([code] + bindings.typeParams +
                [p.type for p in bindings.params])
    compiledCode = _compiledCodeTable.get(key)
    if compiledCode is None :
        compiledCode = compileCodeHeader(name, code, env, bindings)
        _compiledCodeTable[key] = compiledCode
        compileCodeBody(code, env, bindings, compiledCode)
    return compiledCode



#
# compileCodeHeader
#

def compileCodeHeader(name, code, env, bindings) :
    if not llvmModuleInitialized :
        initLLVMModule()
    llvmArgTypes = []
    for param in bindings.params :
        llt = llvm.Type.pointer(llvmType(param.type))
        llvmArgTypes.append(llt)
    compiledCode = analyzeCodeToCompile(code, env, bindings)
    if not isVoidType(compiledCode.returnType) :
        llvmReturnType = llvmType(compiledCode.returnType)
        if compiledCode.returnByRef :
            llvmReturnType = llvm.Type.pointer(llvmReturnType)
        llvmArgTypes.append(llvm.Type.pointer(llvmReturnType))
    funcType = llvm.Type.function(llvm.Type.void(), llvmArgTypes)
    func = llvmModule().add_function(funcType, "clay_" + name)
    compiledCode.llvmFunc = func
    for i, var in enumerate(bindings.vars) :
        func.args[i].name = var.s
    return compiledCode

def analyzeCodeToCompile(code, env, bindings) :
    bindings2 = bindingsForAnalysis(bindings)
    result = analyzer.analyzeInvoke(code, env, bindings2)
    if analyzer.isRTValue(result) :
        returnByRef = False
        returnType = result.type
    elif analyzer.isRTReference(result) :
        returnByRef = True
        returnType = result.type
    elif isVoidValue(result) :
        returnByRef = False
        returnType = voidType
    else :
        assert False, result
    return CompiledCode(returnByRef, returnType, None)

def bindingsForAnalysis(bindings) :
    params = []
    for p in bindings.params :
        if isRTValue(p) :
            p = analyzer.RTValue(p.type)
        elif isRTReference(p) :
            p = analyzer.RTReference(p.type)
        else :
            assert False, p
        params.append(p)
    bindings2 = InvokeBindings(
        bindings.typeVars, bindings.typeParams,
        bindings.vars, params)
    return bindings2



#
# CompilerCodeContext
#

class ScopeMarker(object) :
    pass

def isScopeMarker(x) : return type(x) is ScopeMarker

class CompilerCodeContext(object) :
    def __init__(self, compiledCode) :
        self.returnByRef = compiledCode.returnByRef
        self.returnType = compiledCode.returnType
        self.llvmFunc = compiledCode.llvmFunc
        self.scopeStack = []
        self.labels = {}
        self.breakInfo = []
        self.continueInfo = []

    def pushValue(self, value) :
        assert isRTValue(value)
        self.scopeStack.append(value)

    def pushMarker(self) :
        marker = ScopeMarker()
        self.scopeStack.append(marker)
        return marker

    def cleanAll(self) :
        for x in reversed(self.scopeStack) :
            if isRTValue(x) :
                rtValueDestroy(x)

    def cleanUpto(self, marker) :
        assert isScopeMarker(marker)
        for x in reversed(self.scopeStack) :
            if isRTValue(x) :
                rtValueDestroy(x)
            if x is marker :
                return
        assert False

    def popUpto(self, marker) :
        assert isScopeMarker(marker)
        while True :
            thing = self.scopeStack.pop()
            if thing is marker :
                break

    def addLabel(self, name, marker) :
        if name.s in self.labels :
            withContext(name, lambda : error("label redefinition"))
        llvmBlock = self.llvmFunc.append_basic_block(name.s)
        self.labels[name.s] = (llvmBlock, marker)

    def lookupLabel(self, name) :
        result = self.labels.get(name.s)
        if result is None :
            withContext(name, lambda : error("label not found"))
        llvmBlock, marker = result
        return llvmBlock, marker

    def lookupLabelBlock(self, name) :
        llvmBlock, _ = self.lookupLabel(name)
        return llvmBlock

    def pushLoopInfo(self, breakBlock, breakMarker,
                    continueBlock, continueMarker) :
        self.breakInfo.append((breakBlock, breakMarker))
        self.continueInfo.append((continueBlock, continueMarker))

    def popLoopInfo(self) :
        self.breakInfo.pop()
        self.continueInfo.pop()

    def lookupBreak(self) :
        if not self.breakInfo :
            error("invalid break statement")
        llvmBlock, marker = self.breakInfo[-1]
        return llvmBlock, marker

    def lookupContinue(self) :
        if not self.continueInfo :
            error("invalid continue statement")
        llvmBlock, marker = self.continueInfo[-1]
        return llvmBlock, marker



#
# compileCodeBody
#

def compileCodeBody(code, env, bindings, compiledCode) :
    func = compiledCode.llvmFunc
    initBlock = func.append_basic_block("entry")
    codeBlock = func.append_basic_block("code")
    global llvmFunction, llvmBuilder, llvmInitBuilder
    savedLLVMFunction = llvmFunction
    savedLLVMBuilder = llvmBuilder
    savedLLVMInitBuilder = llvmInitBuilder
    llvmFunction = func
    llvmInitBuilder = llvm.Builder.new(initBlock)
    llvmBuilder = llvm.Builder.new(codeBlock)
    params = []
    for i, p in enumerate(bindings.params) :
        if isRTValue(p) :
            p = RTValue(p.type, func.args[i])
        elif isRTReference(p) :
            p = RTReference(p.type, func.args[i])
        else :
            assert False, p
        params.append(p)
    env = extendEnv(env, bindings.typeVars + bindings.vars,
                    bindings.typeParams + params)
    codeContext = CompilerCodeContext(compiledCode)
    isTerminated = compileStatement(code.body, env, codeContext)
    if not isTerminated :
        llvmBuilder.ret_void()
    llvmInitBuilder.branch(codeBlock)
    llvmFunction = savedLLVMFunction
    llvmBuilder = savedLLVMBuilder
    llvmInitBuilder = savedLLVMInitBuilder



#
# compileStatement
#

def compileStatement(x, env, codeContext) :
    contextPush(x) # error context
    pushTempsBlock()
    result = compileStatement2(x, env, codeContext)
    popTempsBlock()
    contextPop() # error context
    return result



#
# compileStatement2
#

compileStatement2 = multimethod(errorMessage="invalid statement")

@compileStatement2.register(Block)
def foo(x, env, codeContext) :
    env = Environment(env)
    blockMarker = codeContext.pushMarker()
    marker = blockMarker
    compilerCollectLabels(x.statements, 0, marker, codeContext)
    isTerminated = False
    for i, y in enumerate(x.statements) :
        if type(y) is Label :
            labelBlock = codeContext.lookupLabelBlock(y.name)
            llvmBuilder.branch(labelBlock)
            llvmBuilder.position_at_end(labelBlock)
        elif isTerminated :
            withContext(y, lambda : error("unreachable code"))
        elif type(y) is LocalBinding :
            converter = toRTValueOrReference
            if y.type is not None :
                declaredType = compile(y.type, env, toType)
                converter = toRTValueOrReferenceOfType(declaredType)
            pushRTTempsBlock()
            right = compile(y.expr, env, converter)
            if not y.byRef :
                right = toRTValue(right)
            if isRTValue(right) :
                detachFromRTTempsBlock(right)
                codeContext.pushValue(right)
            popRTTempsBlock()
            addIdent(env, y.name, right)
            marker = codeContext.pushMarker()
            compilerCollectLabels(x.statements, i+1, marker, codeContext)
        else :
            isTerminated = compileStatement(y, env, codeContext)
    if not isTerminated :
        codeContext.cleanUpto(blockMarker)
    codeContext.popUpto(blockMarker)
    return isTerminated

def compilerCollectLabels(statements, i, marker, codeContext) :
    while i < len(statements) :
        stmt = statements[i]
        if type(stmt) is Label :
            codeContext.addLabel(stmt.name, marker)
        elif type(stmt) is LocalBinding :
            break
        i += 1

@compileStatement2.register(Assignment)
def foo(x, env, codeContext) :
    pushRTTempsBlock()
    left = compile(x.left, env, toRTLValue)
    right = compile(x.right, env, toRTReferenceOfType(left.type))
    rtValueAssign(left, right)
    popRTTempsBlock()
    return False

@compileStatement2.register(Goto)
def foo(x, env, codeContext) :
    llvmBlock, marker = codeContext.lookupLabel(x.labelName)
    codeContext.cleanUpto(marker)
    llvmBuilder.branch(llvmBlock)
    return True

@compileStatement2.register(Return)
def foo(x, env, codeContext) :
    retType = codeContext.returnType
    if isVoidType(retType) :
        ensure(x.expr is None, "void return expected")
        codeContext.cleanAll()
        llvmBuilder.ret_void()
        return True
    ensure(x.expr is not None, "return value expected")
    pushRTTempsBlock()
    if codeContext.returnByRef :
        result = compile(x.expr, env, toRTLValueOfType(retType))
        llvmBuilder.store(result.llvmValue, codeContext.llvmFunc.args[-1])
    else :
        result = compile(x.expr, env, toRTReferenceOfType(retType))
        returnRef = RTReference(retType, codeContext.llvmFunc.args[-1])
        rtValueCopy(returnRef, result)
    popRTTempsBlock()
    codeContext.cleanAll()
    llvmBuilder.ret_void()
    return True

@compileStatement2.register(IfStatement)
def foo(x, env, codeContext) :
    pushRTTempsBlock()
    condRef = compile(x.condition, env, toRTReferenceOfType(boolType))
    cond = llvmBuilder.load(condRef.llvmValue)
    zero = llvm.Constant.int(llvmType(boolType), 0)
    condResult = llvmBuilder.icmp(llvm.ICMP_NE, cond, zero)
    popRTTempsBlock()
    thenBlock = codeContext.llvmFunc.append_basic_block("then")
    elseBlock = codeContext.llvmFunc.append_basic_block("else")
    mergeBlock = None
    llvmBuilder.cbranch(condResult, thenBlock, elseBlock)
    llvmBuilder.position_at_end(thenBlock)
    thenTerminated = compileStatement(x.thenPart, env, codeContext)
    if not thenTerminated :
        if mergeBlock is None :
            mergeBlock = codeContext.llvmFunc.append_basic_block("merge")
        llvmBuilder.branch(mergeBlock)
    elseTerminated = False
    llvmBuilder.position_at_end(elseBlock)
    if x.elsePart is not None :
        elseTerminated = compileStatement(x.elsePart, env, codeContext)
    if not elseTerminated :
        if mergeBlock is None :
            mergeBlock = codeContext.llvmFunc.append_basic_block("merge")
        llvmBuilder.branch(mergeBlock)
    if mergeBlock is not None :
        assert not (thenTerminated and elseTerminated)
        llvmBuilder.position_at_end(mergeBlock)
        return False
    assert thenTerminated and elseTerminated
    return True

@compileStatement2.register(ExprStatement)
def foo(x, env, codeContext) :
    pushRTTempsBlock()
    compile(x.expr, env)
    popRTTempsBlock()
    return False

@compileStatement2.register(While)
def foo(x, env, codeContext) :
    condBlock = codeContext.llvmFunc.append_basic_block("while")
    bodyBlock = codeContext.llvmFunc.append_basic_block("body")
    exitBlock = codeContext.llvmFunc.append_basic_block("exit")
    marker = codeContext.pushMarker()
    codeContext.pushLoopInfo(exitBlock, marker, condBlock, marker)
    llvmBuilder.branch(condBlock)
    llvmBuilder.position_at_end(condBlock)
    pushRTTempsBlock()
    condRef = compile(x.condition, env, toRTReferenceOfType(boolType))
    cond = llvmBuilder.load(condRef.llvmValue)
    zero = llvm.Constant.int(llvmType(boolType), 0)
    condResult = llvmBuilder.icmp(llvm.ICMP_NE, cond, zero)
    popRTTempsBlock()
    llvmBuilder.cbranch(condResult, bodyBlock, exitBlock)
    llvmBuilder.position_at_end(bodyBlock)
    bodyTerminated = compileStatement(x.body, env, codeContext)
    if not bodyTerminated :
        llvmBuilder.branch(condBlock)
    llvmBuilder.position_at_end(exitBlock)
    codeContext.popLoopInfo()
    codeContext.popUpto(marker)
    return False

@compileStatement2.register(Break)
def foo(x, env, codeContext) :
    llvmBlock, marker = codeContext.lookupBreak()
    codeContext.cleanUpto(marker)
    llvmBuilder.branch(llvmBlock)
    return True

@compileStatement2.register(Continue)
def foo(x, env, codeContext) :
    llvmBlock, marker = codeContext.lookupContinue()
    codeContext.cleanUpto(marker)
    llvmBuilder.branch(llvmBlock)
    return True

@compileStatement2.register(For)
def foo(x, env, codeContext) :
    return compileStatement(convertForStatement(x), env, codeContext)



#
# remove temp name used for multimethod instances
#

del foo