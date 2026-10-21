"""Serializable localization identities; no translations happen when importing this module."""
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Mapping


class Game(StrEnum):
    FRLG = "frlg"
    RSE = "rse"
    LGPE = "lgpe"
    SWSH = "swsh"
    BDSP = "bdsp"
    PLA = "pla"
    SV = "sv"
    ZA = "za"


class EntityKind(StrEnum):
    SPECIES = "species"
    MOVE = "move"
    ITEM = "item"
    ABILITY = "ability"
    TYPE = "type"
    NATURE = "nature"
    BALL = "ball"


@dataclass(frozen=True)
class EntityRef:
    game: str
    kind: EntityKind
    id: int
    form: int = 0

    def __post_init__(self):
        object.__setattr__(self, "kind", EntityKind(self.kind))
        import re
        if not isinstance(self.game, str) or not re.fullmatch(r"[a-z][a-z0-9_-]*", self.game):
            raise ValueError("An entity needs a registered game identifier.")
        if not isinstance(self.id, int) or isinstance(self.id, bool) or self.id < 0:
            raise ValueError("An entity ID must be a nonnegative integer.")
        if not isinstance(self.form, int) or isinstance(self.form, bool) or not 0 <= self.form <= 255:
            raise ValueError("A form must be an integer from 0 to 255.")
        if self.kind != EntityKind.SPECIES and self.form:
            raise ValueError("Only species references have forms.")


@dataclass(frozen=True)
class NameTable:
    by_id: Mapping[int, str]
    by_form: Mapping[tuple[int, int], str] = field(default_factory=dict)

    def __post_init__(self):
        object.__setattr__(self, "by_id", MappingProxyType(dict(self.by_id)))
        object.__setattr__(self, "by_form", MappingProxyType(dict(self.by_form)))


@dataclass(frozen=True)
class MessageRef:
    key: str
    params: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self):
        object.__setattr__(self, "params", MappingProxyType(dict(self.params)))

    def __str__(self):
        from . import i18n
        return i18n.text(self.key, **self.params)

    def __reduce__(self):
        return MessageRef, (self.key, dict(self.params))

    def to_wire(self):
        def encode(value):
            if isinstance(value, MessageRef):
                return value.to_wire()
            if isinstance(value, EntityRef):
                return {"$entity": {"game": str(value.game), "kind": str(value.kind),
                                    "id": value.id, "form": value.form}}
            if value is None or isinstance(value, (str, int, float, bool)):
                return value
            raise TypeError("Message parameters must be scalars, entities or messages.")
        return {"$message": self.key, "params": {k: encode(v) for k, v in self.params.items()}}

    @classmethod
    def from_wire(cls, value, _depth=0):
        if _depth > 8 or not isinstance(value, dict):
            raise ValueError("Invalid structured message.")
        def decode(part):
            if isinstance(part, dict) and "$message" in part:
                return cls.from_wire(part, _depth + 1)
            if isinstance(part, dict) and set(part) == {"$entity"}:
                return EntityRef(**part["$entity"])
            if part is None or isinstance(part, (str, int, float, bool)):
                return part
            raise ValueError("Invalid message parameter.")
        if set(value) != {"$message", "params"} or not isinstance(value["$message"], str):
            raise ValueError("Invalid structured message.")
        if not isinstance(value["params"], dict) or any(not isinstance(k, str) or not k.isidentifier() for k in value["params"]):
            raise ValueError("Invalid structured message parameters.")
        return cls(value["$message"], {k: decode(v) for k, v in value["params"].items()})


class MessageError(ValueError):
    def __init__(self, key, **params):
        self.message = MessageRef(key, params)
        super().__init__(self.message)


class TextRef(str):
    """A stable catalog reference with canonical text for non-display consumers.

    The str payload preserves the public catalog's CLI/export contract. Display code
    resolves key, never the payload. References remain valid across language changes.
    """
    def __new__(cls, key, canonical):
        instance = str.__new__(cls, canonical)
        instance.key = key
        return instance

    def __reduce__(self):
        return TextRef, (self.key, str(self))

    def __add__(self, other):
        return DisplayText(str(self) + str(other), ("concat", self, other))

    def __radd__(self, other):
        return DisplayText(str(other) + str(self), ("concat", other, self))

    def join(self, values):
        values = tuple(values)
        return DisplayText(str(self).join(map(str, values)), ("join", self, values))


class DisplayText(str):
    """Rendered text retaining its identity so mounted controls can be relabeled."""
    def __new__(cls, value, reference):
        instance = str.__new__(cls, value)
        instance.reference = reference
        return instance

    def __reduce__(self):
        return DisplayText, (str(self), self.reference)

    def __add__(self, other):
        return DisplayText(str(self) + str(other), ("concat", self, other))

    def __radd__(self, other):
        return DisplayText(str(other) + str(self), ("concat", other, self))

    def join(self, values):
        values = tuple(values)
        return DisplayText(str(self).join(map(str, values)), ("join", self, values))

    def split(self, sep=None, maxsplit=-1):
        return [DisplayText(value, ("split", self, sep, index, maxsplit))
                for index, value in enumerate(str(self).split(sep, maxsplit))]


@dataclass(frozen=True)
class DocumentSection:
    id: str
    title: str
    level: int


@dataclass(frozen=True)
class LocalizedDocument:
    id: str
    locale: str
    title: str
    path: object
    sections: tuple[DocumentSection, ...]
    parent: str = ""
    order: int = 99
