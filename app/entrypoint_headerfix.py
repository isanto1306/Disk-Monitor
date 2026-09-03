from fastapi.responses import HTMLResponse

import entrypoint as base


app = base.app
app.version = "0.22.30"

HEADER_SCROLLBAR_PATCH = r"""
<script id="disk-monitor-fixed-header-scrollbar-sync">
(() => {
    let frame = null;
    let lastScrollbarWidth = null;

    const getHeader = () => document.querySelector("#app > header, header");

    const restoreHeaderWidth = () => {
        const header = getHeader();
        if (!header) return;
        header.style.removeProperty("width");
    };

    const syncHeaderWidth = () => {
        const header = getHeader();
        if (!header) return;

        const scrollbarWidth = Math.max(
            0,
            window.innerWidth - document.documentElement.clientWidth
        );

        if (
            lastScrollbarWidth !== null
            && Math.abs(scrollbarWidth - lastScrollbarWidth) < 0.01
        ) {
            return;
        }

        lastScrollbarWidth = scrollbarWidth;

        if (scrollbarWidth > 0) {
            header.style.setProperty(
                "width",
                "calc(100% + " + scrollbarWidth + "px)",
                "important"
            );
        }
        else {
            restoreHeaderWidth();
        }
    };

    const schedule = () => {
        if (frame !== null) return;
        frame = window.requestAnimationFrame(() => {
            frame = null;
            syncHeaderWidth();
        });
    };

    if (typeof ResizeObserver === "function") {
        const observer = new ResizeObserver(schedule);
        observer.observe(document.documentElement);
    }

    window.addEventListener("resize", () => {
        lastScrollbarWidth = null;
        schedule();
    });

    schedule();
    window.setInterval(schedule, 250);
})();
</script>
"""

try:
    _index_html = base._index_html
    if (
        _index_html
        and "disk-monitor-fixed-header-scrollbar-sync" not in _index_html
    ):
        _index_html = _index_html.replace(
            "</body>",
            HEADER_SCROLLBAR_PATCH + "\n</body>",
            1,
        )
except Exception:
    _index_html = None


@app.middleware("http")
async def serve_root_with_fixed_header_scrollbar_sync(request, call_next):
    if (
        request.method == "GET"
        and request.url.path == "/"
        and _index_html is not None
    ):
        return HTMLResponse(
            content=_index_html,
            headers={"Cache-Control": "no-store"},
        )

    return await call_next(request)
