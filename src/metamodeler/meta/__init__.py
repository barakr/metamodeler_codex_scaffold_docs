"""Metamodel IR, builder, and compiler."""

from metamodeler.meta.builder import build_ir_from_metamodel_spec
from metamodeler.meta.compiler import CompiledMetaModel, compile_metamodel
from metamodeler.meta.ir import (
    CouplingFactorIR,
    MetamodelIR,
    PriorFactorIR,
    SurrogateLikelihoodFactorIR,
    VariableIR,
    ir_from_json_dict,
    ir_to_json_dict,
)

__all__ = [
    "CompiledMetaModel",
    "CouplingFactorIR",
    "MetamodelIR",
    "PriorFactorIR",
    "SurrogateLikelihoodFactorIR",
    "VariableIR",
    "build_ir_from_metamodel_spec",
    "compile_metamodel",
    "ir_from_json_dict",
    "ir_to_json_dict",
]
