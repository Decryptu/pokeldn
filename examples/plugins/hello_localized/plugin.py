"""An English catalog belongs to its functional plugin's namespace."""
from pokeldn.app.i18n import ref, text
from pokeldn.plugins import Tool


def register(api):
    api.register_localization({
        "hello-localized.tool.name": "Localized example",
        "hello-localized.tool.summary": "Shows text from a plugin-owned catalog.",
        "hello-localized.tool.step": "Run this example to display a message.",
        "hello-localized.result": "Hello, {name}!",
    })
    api.add_tool("sv", Tool("hello-localized", ref("hello-localized.tool.name"), "example.py",
                           ref("hello-localized.tool.summary"), (ref("hello-localized.tool.step"),)))
