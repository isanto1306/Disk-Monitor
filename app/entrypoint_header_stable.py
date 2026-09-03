import entrypoint


app = entrypoint.app
app.version = "0.22.34"
entrypoint.main.app.version = "0.22.34"


# entrypoint.py injects the runtime header style before serving the root page.
# The static frontend contains a later rule with `width: 100% !important` on
# `#app > header`, so a plain `header { width: 100vw; }` cannot win the cascade.
# Replace only that injected rule with the exact selector and matching
# importance.
#
# The global background scroll lock also adds right padding equal to the
# browser scrollbar width. Since the 0.22.29+ runtime layout compensation has
# already widened the body while the scrollbar is present, that padding would
# compensate the same gap a second time when Settings/Info/modal panels lock
# the page. Skip that extra padding only when the body-width compensation is
# already active. The scroll lock itself and all panel behavior stay unchanged.
if entrypoint._index_html is not None:
    entrypoint._index_html = entrypoint._index_html.replace(
        "header {\n    width: 100vw;\n}",
        "#app > header {\n    width: 100vw !important;\n}",
        1,
    )

    old_scrollbar_padding = '''        if (scrollbarGap > 0) {

            const currentPaddingRight =
                Number.parseFloat(
                    window.getComputedStyle(
                        body
                    ).paddingRight
                ) || 0;

            body.style.paddingRight =
                `${currentPaddingRight + scrollbarGap}px`;

        }
'''

    new_scrollbar_padding = '''        const bodyWidthAlreadyCompensated = Boolean(
            bodyInline.width
            && bodyInline.width.includes(
                "calc(100% +"
            )
        );

        if (
            scrollbarGap > 0
            && !bodyWidthAlreadyCompensated
        ) {

            const currentPaddingRight =
                Number.parseFloat(
                    window.getComputedStyle(
                        body
                    ).paddingRight
                ) || 0;

            body.style.paddingRight =
                `${currentPaddingRight + scrollbarGap}px`;

        }
'''

    entrypoint._index_html = entrypoint._index_html.replace(
        old_scrollbar_padding,
        new_scrollbar_padding,
        1,
    )
