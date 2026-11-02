"""Tiny DOM helper for page tests (stdlib only): find elements by tag/id/class and read their text."""

from collections.abc import Iterator
from html.parser import HTMLParser

VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}


class Node:
    def __init__(self, tag: str, attrs: dict[str, str | None], parent: "Node | None" = None):
        self.tag, self.attrs, self.parent = tag, attrs, parent
        self.children: list[Node | str] = []

    def walk(self) -> Iterator["Node"]:
        for child in self.children:
            if isinstance(child, Node):
                yield child
                yield from child.walk()

    def find_all(self, tag: str | None = None, **attrs: str) -> list["Node"]:
        return [
            n
            for n in self.walk()
            if (tag is None or n.tag == tag) and all(n.attrs.get(k) == v for k, v in attrs.items())
        ]

    def find(self, tag: str | None = None, **attrs: str) -> "Node | None":
        found = self.find_all(tag, **attrs)
        return found[0] if found else None

    def by_class(self, cls: str) -> list["Node"]:
        return [n for n in self.walk() if cls in (n.attrs.get("class") or "").split()]

    def inside(self, ancestor: "Node") -> bool:
        node = self.parent
        while node is not None:
            if node is ancestor:
                return True
            node = node.parent
        return False

    @property
    def text(self) -> str:
        parts = [c if isinstance(c, str) else c.text for c in self.children]
        return " ".join("".join(parts).split())


class _Builder(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = Node("#root", {})
        self.cur = self.root

    def handle_starttag(self, tag, attrs):
        node = Node(tag, dict(attrs), self.cur)
        self.cur.children.append(node)
        if tag not in VOID:
            self.cur = node

    def handle_startendtag(self, tag, attrs):
        self.cur.children.append(Node(tag, dict(attrs), self.cur))

    def handle_endtag(self, tag):
        node = self.cur
        while node is not self.root and node.tag != tag:
            node = node.parent
        if node is not self.root:
            self.cur = node.parent

    def handle_data(self, data):
        if self.cur.tag not in ("script", "style"):
            self.cur.children.append(data)


def parse(html: str) -> Node:
    builder = _Builder()
    builder.feed(html)
    return builder.root


def by_id(root: Node, element_id: str) -> Node | None:
    return root.find(id=element_id)
