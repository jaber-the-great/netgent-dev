"""Infer workflow parameters from prompt VARIATIONS (ReUseIt's variation-task idea).

Give several variations of the same task and the parts that differ become parameters, so
the workflow generalizes. This is deterministic (a token diff across the variations) — more
reliable than an LLM for the common "same structure, different values" case; an LLM pass can
later refine names/grouping.

    infer_params([
        "book a Delta flight from NYC to LA on Dec 1",
        "book a United flight from Boston to Chicago on Jan 15",
    ])
    -> template: "book a ${p1} flight from ${p2} to ${p3} on ${p4}"
       params:   p1..p4, each with the observed values as samples
"""

import difflib

from pydantic import BaseModel, Field

from netgent.schema.control import Param


class InferredTemplate(BaseModel):
    template: str  # the prompt with ${p1}, ${p2}, ... in place of the varying values
    params: list[Param]
    samples: dict[str, list[str]] = Field(default_factory=dict)  # param name -> value per variation


def _variable_indices(base: list[str], others: list[list[str]]) -> set[int]:
    """Base token indices that differ in ANY variation."""
    variable: set[int] = set()
    for other in others:
        for tag, i1, i2, _j1, _j2 in difflib.SequenceMatcher(None, base, other, autojunk=False).get_opcodes():
            if tag in ("replace", "delete"):
                variable.update(range(i1, i2))
            elif tag == "insert" and base:  # extra tokens in `other` — mark the boundary token
                variable.add(min(i1, len(base) - 1))
    return variable


def _span_value(base: list[str], var: list[str], span: tuple[int, int]) -> str:
    """The tokens of `var` aligned to base[span[0]:span[1]]."""
    s, e = span
    js = je = None
    for _tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, base, var, autojunk=False).get_opcodes():
        if i1 < e and i2 > s:  # opcode overlaps the span
            js = j1 if js is None else js
            je = j2
    return " ".join(var[js:je]) if js is not None else ""


def infer_params(variations: list[str], prefix: str = "p") -> InferredTemplate:
    """Diff the variations; each varying span becomes a ${prefix}N parameter."""
    if len(variations) < 2:
        raise ValueError("provide at least two prompt variations to infer parameters")
    base = variations[0].split()
    variable = _variable_indices(base, [v.split() for v in variations[1:]])

    # group consecutive variable indices into contiguous spans
    spans: list[tuple[int, int]] = []
    for idx in sorted(variable):
        if spans and idx == spans[-1][1]:
            spans[-1] = (spans[-1][0], idx + 1)
        else:
            spans.append((idx, idx + 1))

    out: list[str] = []
    params: list[Param] = []
    samples: dict[str, list[str]] = {}
    last = 0
    for n, span in enumerate(spans, 1):
        out.extend(base[last : span[0]])
        name = f"{prefix}{n}"
        out.append("${" + name + "}")
        # the base's own value is its span; align the other variations to it
        values = [" ".join(base[span[0] : span[1]])] + [_span_value(base, v.split(), span) for v in variations[1:]]
        params.append(Param(name=name, description=f"e.g. {values[0]!r}", default=values[0], required=True))
        samples[name] = values
        last = span[1]
    out.extend(base[last:])
    return InferredTemplate(template=" ".join(out), params=params, samples=samples)
