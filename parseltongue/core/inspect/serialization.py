"""Serialize / deserialize CoreToConsequenceStructure for bench caching."""

from ..serialization.serializers import deserialize_sexp, serialize_sexp
from .probe_core_to_consequence import (
    Consumer,
    ConsumerInput,
    CoreToConsequenceStructure,
    InputType,
    Layer,
    Node,
    NodeKind,
)


def serialize_node(node: Node) -> dict:
    return {
        "name": node.name,
        "kind": node.kind.value,
        "value": serialize_sexp(node.value),
        "inputs": node.inputs,
    }


def deserialize_node(data: dict) -> Node:
    return Node(
        name=data["name"],
        kind=NodeKind(data["kind"]),
        value=deserialize_sexp(data["value"]),
        inputs=data["inputs"],
        atom=None,
    )


def serialize_consumer_input(ci: ConsumerInput) -> dict:
    return {"name": ci.name, "input_type": ci.input_type.value, "source_depth": ci.source_depth}


def deserialize_consumer_input(data: dict) -> ConsumerInput:
    return ConsumerInput(
        name=data["name"], input_type=InputType(data["input_type"]), source_depth=data.get("source_depth", 0)
    )


def serialize_consumer(c: Consumer) -> dict:
    return {
        "node": c.node.name,
        "uses": [serialize_consumer_input(ci) for ci in c.uses],
        "declares": [serialize_consumer_input(ci) for ci in c.declares],
        "pulls": [serialize_consumer_input(ci) for ci in c.pulls],
    }


def serialize_layer(layer: Layer) -> dict:
    return {"depth": layer.depth, "consumers": [serialize_consumer(c) for c in layer.consumers]}


def serialize_structure(s: CoreToConsequenceStructure) -> dict:
    return {
        "graph": {name: serialize_node(node) for name, node in s.graph.items()},
        "layers": [serialize_layer(layer) for layer in s.layers],
        "depths": s.depths,
        "max_depth": s.max_depth,
    }


def deserialize_structure(data: dict) -> CoreToConsequenceStructure:
    graph = {name: deserialize_node(d) for name, d in data["graph"].items()}

    layers = []
    for layer_data in data["layers"]:
        consumers = []
        for cd in layer_data["consumers"]:
            node = graph[cd["node"]]
            consumers.append(
                Consumer(
                    node=node,
                    uses=[deserialize_consumer_input(ci) for ci in cd["uses"]],
                    declares=[deserialize_consumer_input(ci) for ci in cd["declares"]],
                    pulls=[deserialize_consumer_input(ci) for ci in cd["pulls"]],
                )
            )
        layers.append(Layer(depth=layer_data["depth"], consumers=consumers))

    return CoreToConsequenceStructure(
        layers=layers,
        graph=graph,
        depths=data["depths"],
        max_depth=data["max_depth"],
    )
