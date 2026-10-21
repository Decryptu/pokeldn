from pokeldn import plugins
from pokeldn.app import i18n, settings

plugins.load()
selected = settings.load()
i18n.select(selected.app_language, selected.app_locale or None)
print(i18n.text("hello-localized.result", name="POKELDN"))
