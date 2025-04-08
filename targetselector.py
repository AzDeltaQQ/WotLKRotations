from object_manager import ObjectManager
from wow_object import WowObject
from typing import Optional

class TargetSelector:
    """Manages target selection logic."""

    def __init__(self, om: ObjectManager):
        """Initializes the TargetSelector.

        Args:
            om: The ObjectManager instance.
        """
        self.om = om

    def get_selected_target(self) -> Optional[WowObject]:
        """Returns the currently selected target based on some logic.

        Currently, just returns the ObjectManager's current target.
        Future logic could include focus target, mouseover, nearest enemy, etc.

        Returns:
            The selected WowObject target, or None if no valid target.
        """
        # Basic implementation: Return current target from ObjectManager
        if self.om and self.om.target and self.om.target.is_valid():
            return self.om.target
        return None

    # Add other methods as needed, e.g.:
    # def set_focus_target(self, guid):
    # def get_focus_target(self):
    # def find_nearest_enemy(self):
