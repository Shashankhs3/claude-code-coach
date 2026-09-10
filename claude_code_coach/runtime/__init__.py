"""V4 runtime layer: observes real Claude Code hook events, when configured.

Kept deliberately minimal here (no eager submodule imports) — hook_receiver.py
must stay import-light and fast, and importing it indirectly through this
package's __init__ would slow down every single hook invocation.
"""
