from __future__ import annotations

import shlex
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import cast


class Command(ABC):
    @abstractmethod
    def to_shell(self, pretty: bool, indent: int = 0) -> str:
        pass

    def to_shell_bash_minusc(self) -> list[str]:
        return ["bash", "-c", self.to_shell(pretty=False)]


class Expandable(ABC):
    @abstractmethod
    def to_shell(self) -> str:
        pass

    @staticmethod
    def arg_to_shell(arg: str | Expandable) -> str:
        if isinstance(arg, str):
            return shlex.quote(arg)
        else:
            return arg.to_shell()


@dataclass
class Parameter(Expandable):
    name: str

    def to_shell(self) -> str:
        return f'"${self.name}"'


@dataclass
class Concat(Expandable):
    parts: list[str | Expandable]

    def to_shell(self) -> str:
        if not self.parts:
            return "''"

        return "".join([Expandable.arg_to_shell(part) for part in self.parts])


class Redirect(ABC):
    @abstractmethod
    def to_shell(self) -> str:
        pass

    @staticmethod
    def to_shell_words(redirects: Redirect | list[Redirect] | None) -> list[str]:
        if not redirects:
            return []
        elif isinstance(redirects, list):
            return [redirect.to_shell() for redirect in redirects]
        else:
            return [redirects.to_shell()]

    @staticmethod
    def apply_redirects(shell: str, redirects: Redirect | list[Redirect] | None) -> str:
        if redirects:
            return " ".join([shell, *Redirect.to_shell_words(redirects)])

        return shell


@dataclass
class InputRedirect(Redirect):
    path: str | Expandable
    fd: int = 0

    def to_shell(self) -> str:
        return f"{self.fd if self.fd != 0 else ''}< {Expandable.arg_to_shell(self.path)}"


@dataclass
class OutputRedirect(Redirect):
    path: str | Expandable
    fd: int = 1
    append: bool = False

    def to_shell(self) -> str:
        return f"{self.fd if self.fd != 1 else ''}{'>>' if self.append else '>'} {Expandable.arg_to_shell(self.path)}"


@dataclass
class SimpleCommand(Command):
    command: list[str | Expandable]

    assignments: dict[str, str | Expandable] | None = None
    redirects: Redirect | list[Redirect] | None = None

    def to_shell(self, pretty: bool, indent: int = 0) -> str:
        words = []

        if self.assignments:
            words.extend(f"{name}={Expandable.arg_to_shell(value)}" for name, value in self.assignments.items())

        words.extend(Expandable.arg_to_shell(arg) for arg in self.command)

        words.extend(Redirect.to_shell_words(self.redirects))

        return " ".join(words)


@dataclass
class Pipeline(Command):
    commands: list[Command]

    def to_shell(self, pretty: bool, indent: int = 0) -> str:
        assert len(self.commands) > 1, self.commands

        return " | ".join([(Group(command) if isinstance(command, CommandList) else command).to_shell(pretty, indent) for command in self.commands])


@dataclass
class CommandList(Command, ABC):
    commands: list[Command]

    def to_shell(self, pretty: bool, indent: int = 0) -> str:
        return self._operator().join([self._maybe_group_command(command).to_shell(pretty, indent) for command in self.commands])

    @abstractmethod
    def _operator(self) -> str:
        pass

    def _maybe_group_command(self, command: Command) -> Command:
        if isinstance(command, CommandList) and not isinstance(command, self.__class__):
            return Group(cast(CommandList, command))
        else:
            return command


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
    command: Command

    redirects: Redirect | list[Redirect] | None = None

    def to_shell(self, pretty: bool, indent: int = 0) -> str:
        result = f"( {self.command.to_shell(pretty, indent)} )"
        return Redirect.apply_redirects(result, self.redirects)


@dataclass
class Group(CompoundCommand):
    command: Command

    redirects: Redirect | list[Redirect] | None = None

    def to_shell(self, pretty: bool, indent: int = 0) -> str:
        result = f"{{ {self.command.to_shell(pretty, indent)}; }}"
        return Redirect.apply_redirects(result, self.redirects)
