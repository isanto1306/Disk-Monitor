import entrypoint


app = entrypoint.app
app.version = "0.22.33"
entrypoint.main.app.version = "0.22.33"


# entrypoint.py injects the runtime header style before serving the root page.
# The static frontend contains a later rule with `width: 100% !important` on
# `#app > header`, so a plain `header { width: 100vw; }` cannot win the cascade.
# Replace only that injected rule with the exact selector and matching
# importance. Nothing else in the generated page is changed.
if entrypoint._index_html is not None:
    entrypoint._index_html = entrypoint._index_html.replace(
        "header {\n    width: 100vw;\n}",
        "#app > header {\n    width: 100vw !important;\n}",
        1,
    )
