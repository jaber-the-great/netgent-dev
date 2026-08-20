"""Runtime parameter resolution: static (caller/default) + dynamic (extracted from the page).

Substitutes ${name} in an action's fields just before it is dispatched, so a value observed
earlier in the run can feed a later step. A dynamic param is extracted from the live page
with a small retry, then checked against its `guard` regex. A missing required value or a
guard failure raises ParamError — the typed drift signal the healing ladder acts on.
"""

import asyncio
import re

from pydantic import TypeAdapter

from netgent.core.errors import ParamError
from netgent.core.logger import get_logger
from netgent.schema.actions import Action
from netgent.schema.control import Param

logger = get_logger(__name__)
_REF = re.compile(r"\$\{(\w+)\}")
_ACTION = TypeAdapter(Action)
EXTRACT_RETRIES = 3
EXTRACT_RETRY_DELAY_S = 0.3


class ParamContext:
    """Resolves and caches parameter values for one run."""

    def __init__(self, params: list[Param], provided: dict[str, str] | None, session):
        self._params = {p.name: p for p in params}
        self._session = session
        self._values: dict[str, str] = {}
        provided = provided or {}
        for p in params:
            if p.source is not None:
                continue  # dynamic — resolved lazily from the page when first referenced
            if p.name in provided:
                self._check(p, provided[p.name])
                self._values[p.name] = provided[p.name]
            elif p.default is not None:
                self._values[p.name] = p.default
            elif p.required:
                raise ParamError(f"missing required param {p.name!r}")

    def _check(self, p: Param, value: str | None) -> None:
        if p.guard and (value is None or re.search(p.guard, value) is None):
            shown = "<secret>" if p.secret else repr(value)
            raise ParamError(f"param {p.name!r} value {shown} fails guard /{p.guard}/")

    async def value(self, name: str) -> str:
        if name in self._values:
            return self._values[name]
        p = self._params.get(name)
        if p is None:
            raise ParamError(f"unknown param {name!r}")
        if p.source is None:
            if p.default is not None:
                return p.default
            raise ParamError(f"param {name!r} was not provided")

        # dynamic: extract from the live page, retrying (the value may appear after a beat)
        extracted: str | None = None
        for attempt in range(EXTRACT_RETRIES):
            extracted = await self._session.extract_value(p.source)
            if extracted:
                break
            if attempt < EXTRACT_RETRIES - 1:
                await asyncio.sleep(EXTRACT_RETRY_DELAY_S)
        if not extracted:
            if p.default is not None:
                extracted = p.default
            elif p.required:
                raise ParamError(f"could not extract dynamic param {name!r} from the page")
        self._check(p, extracted)
        self._values[name] = extracted or ""
        logger.debug("param %s resolved to %s", name, "<secret>" if p.secret else repr(extracted))
        return self._values[name]

    async def substitute_text(self, text: str) -> str:
        for name in _REF.findall(text):
            text = text.replace("${" + name + "}", await self.value(name))
        return text

    async def _walk(self, node: object) -> object:
        if isinstance(node, str):
            return await self.substitute_text(node) if "${" in node else node
        if isinstance(node, list):
            return [await self._walk(x) for x in node]
        if isinstance(node, dict):
            return {k: await self._walk(v) for k, v in node.items()}
        return node

    async def resolve_action(self, action: Action) -> Action:
        """Return `action` with every ${name} in its fields substituted."""
        data = action.model_dump()
        return _ACTION.validate_python(await self._walk(data))
