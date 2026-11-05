"""Keep renderer erases on the workspace background instead of terminal defaults."""
from prompt_toolkit.output.vt100 import Vt100_Output

from . import screen


class WorkspaceOutput(Vt100_Output):
    def reset_attributes(self):
        super().reset_attributes()
        self.write_raw(screen.workspace_background())

    def erase_down(self):
        self.write_raw(screen.workspace_background())
        super().erase_down()

    def erase_end_of_line(self):
        self.write_raw(screen.workspace_background())
        super().erase_end_of_line()
