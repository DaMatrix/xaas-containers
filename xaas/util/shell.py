from __future__ import annotations

import shlex
from abc import ABC, abstractmethod
from dataclasses import dataclass


class Command(ABC):
    @abstractmethod
    def to_shell(self, pretty: bool, indent: int = 0) -> str:
        pass


class Expandable(ABC):
    @abstractmethod
    def to_shell(self) -> str:
        pass

    @staticmethod
    def of(arg: str | Expandable) -> Expandable:
        if isinstance(arg, str):
            return Literal(arg)
        else:
            return arg


@dataclass
class Literal(Expandable):
    text: str

    def to_shell(self) -> str:
        return shlex.quote(self.text)


@dataclass
class Parameter(Expandable):
    name: str

    def to_shell(self) -> str:
        return f'"${self.name}"'


@dataclass
class Concat(Expandable):
    parts: list[Expandable]

    def to_shell(self) -> str:
        assert len(self.parts) > 1, self.parts

        return "".join([part.to_shell() for part in self.parts])


@dataclass
class SimpleCommand(Command):
    command: list[str | Expandable]

    assignments: dict[str, str | Expandable] | None = None

    def to_shell(self, pretty: bool, indent: int = 0) -> str:
        words = []

        if self.assignments:
            words.extend(f"{name}={Expandable.of(value).to_shell()}" for name, value in self.assignments.items())

        words.extend(Expandable.of(arg).to_shell() for arg in self.command)

        return " ".join(words)


@dataclass
class Pipeline(Command):
    commands: list[Command]

    def to_shell(self, pretty: bool, indent: int = 0) -> str:
        assert len(self.commands) > 1, self.commands

        return " | ".join([command.to_shell(pretty, indent) for command in self.commands])


@dataclass
class CommandList(Command, ABC):
    commands: list[Command]

    def to_shell(self, pretty: bool, indent: int = 0) -> str:
        return self._operator().join([command.to_shell(pretty, indent) for command in self.commands])

    @abstractmethod
    def _operator(self) -> str:
        pass


@dataclass
class ListAnd(CommandList):
    def _operator(self) -> str:
        return " && "


@dataclass
class ListOr(CommandList):
    def _operator(self) -> str:
        return " || "


class CompoundCommand(Command, ABC):
    pass


@dataclass
class Subshell(CompoundCommand):
    list: CommandList

    def to_shell(self, pretty: bool, indent: int = 0) -> str:
        return f"( {self.list.to_shell(pretty, indent)} )"


@dataclass
class Group(CompoundCommand):
    list: CommandList

    def to_shell(self, pretty: bool, indent: int = 0) -> str:
        return f"{{ {self.list.to_shell(pretty, indent)}; }}"
