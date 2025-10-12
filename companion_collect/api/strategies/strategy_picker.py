"""
Strategy Picker for Version Selection
======================================

Central strategy picker based on game version.

Pattern inspired by madden-franchise repository's StrategyPicker.
"""

from typing import Dict, Type, Optional
from . import VersionStrategy
from .m25_strategy import M25Strategy
from .m26_strategy import M26Strategy


class StrategyPicker:
    """
    Pick version strategy based on game year.
    
    Usage:
        # Get strategy for specific version
        m25 = StrategyPicker.pick(25)
        m26 = StrategyPicker.pick(26)
        
        # Get default version
        default = StrategyPicker.pick()
        
        # Register new version
        StrategyPicker.register(27, M27Strategy)
    """
    
    # Version strategy registry
    _strategies: Dict[int, Type[VersionStrategy]] = {
        25: M25Strategy,
        26: M26Strategy,
    }
    
    # Default version (most recent stable)
    _default_version = 26
    
    @classmethod
    def pick(cls, version: Optional[int] = None) -> VersionStrategy:
        """
        Get strategy for given version.
        
        Args:
            version: Game year (25, 26, etc.). If None, uses default.
            
        Returns:
            VersionStrategy instance
            
        Examples:
            >>> m25 = StrategyPicker.pick(25)
            >>> m25.blaze_id
            'madden-2025-xbsx-gen5'
            
            >>> m26 = StrategyPicker.pick(26)
            >>> m26.version
            26
        """
        # Use default if not specified
        if version is None:
            version = cls._default_version
        
        # Get strategy class (fallback to M25 for unknown versions)
        strategy_class = cls._strategies.get(version, M25Strategy)
        
        # Return instantiated strategy
        return strategy_class()
    
    @classmethod
    def register(cls, version: int, strategy_class: Type[VersionStrategy]):
        """
        Register a new version strategy.
        
        Args:
            version: Game year
            strategy_class: VersionStrategy subclass
            
        Example:
            >>> class M27Strategy(M26Strategy):
            ...     def __init__(self):
            ...         super().__init__()
            ...         self.version = 27
            ...         self.blaze_id = "madden-2027-xbsx-gen5"
            >>> StrategyPicker.register(27, M27Strategy)
        """
        cls._strategies[version] = strategy_class
    
    @classmethod
    def set_default(cls, version: int):
        """
        Set default version.
        
        Args:
            version: Game year to use as default
            
        Example:
            >>> StrategyPicker.set_default(26)
        """
        cls._default_version = version
    
    @classmethod
    def supported_versions(cls) -> list:
        """
        Get list of supported versions.
        
        Returns:
            List of supported game years
            
        Example:
            >>> StrategyPicker.supported_versions()
            [25, 26]
        """
        return sorted(cls._strategies.keys())
    
    @classmethod
    def get_default_version(cls) -> int:
        """
        Get default version number.
        
        Returns:
            Default game year
        """
        return cls._default_version


__all__ = ['StrategyPicker']
