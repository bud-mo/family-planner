"""Per-component drawing for the Pillow-native e-ink renderer.

Each module draws one section of the Home view onto a shared
:class:`~app.renderer.components.context.RenderContext`, which also tracks a
dither mask so the e-ink post-processor can dither only the elements that need
it (see :mod:`app.renderer.palette` and :class:`app.renderer.eink_renderer.EinkRenderer`).
"""
