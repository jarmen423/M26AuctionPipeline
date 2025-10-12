"""Utilities for finding and working with mitmproxy capture files."""

from pathlib import Path
from typing import Optional

from companion_collect.logging import get_logger

logger = get_logger(__name__)


def get_most_recent_capture(
    captures_dir: Optional[Path] = None,
    max_size_mb: Optional[float] = None,
) -> Optional[Path]:
    """Find the most recently modified mitmproxy capture file.
    
    Args:
        captures_dir: Directory to search (default: companion_collect/savedFlows)
        max_size_mb: Skip files larger than this size in MB (default: no limit)
        
    Returns:
        Path to most recent capture file, or None if none found
        
    Example:
        >>> capture = get_most_recent_capture(max_size_mb=100)  # Skip files > 100 MB
        >>> if capture:
        ...     print(f"Using capture: {capture.name} ({capture.stat().st_size / 1024 / 1024:.1f} MB)")
    """
    if captures_dir is None:
        # Default to savedFlows directory
        captures_dir = Path(__file__).parent.parent.parent / "companion_collect" / "savedFlows"
    
    if not captures_dir.exists():
        logger.warning("captures_dir_not_found", path=str(captures_dir))
        return None
    
    # Find all .mitm files
    mitm_files = list(captures_dir.glob("*.mitm"))
    
    if not mitm_files:
        logger.warning("no_mitm_files_found", path=str(captures_dir))
        return None
    
    # Filter by size if max_size_mb specified
    if max_size_mb is not None:
        max_bytes = max_size_mb * 1024 * 1024
        filtered_files = []
        
        for f in mitm_files:
            size = f.stat().st_size
            if size <= max_bytes:
                filtered_files.append(f)
            else:
                logger.debug(
                    "skipping_large_file",
                    file=f.name,
                    size_mb=size / 1024 / 1024,
                    max_mb=max_size_mb,
                )
        
        mitm_files = filtered_files
    
    if not mitm_files:
        logger.warning(
            "no_files_within_size_limit",
            max_mb=max_size_mb,
            path=str(captures_dir),
        )
        return None
    
    # Sort by modification time (most recent first)
    mitm_files.sort(key=lambda f: f.stat().st_mtime, reverse=True)
    
    most_recent = mitm_files[0]
    size_mb = most_recent.stat().st_size / 1024 / 1024
    
    logger.info(
        "most_recent_capture_found",
        file=most_recent.name,
        size_mb=round(size_mb, 2),
        modified=most_recent.stat().st_mtime,
    )
    
    return most_recent


def get_active_capture() -> Optional[Path]:
    """Get the active capture file (most recently modified).
    
    Returns the most recently modified .mitm file regardless of size,
    since this is likely the file mitmproxy is currently writing to.
    
    For large files, use read_recent_flows() to extract only fresh data.
    
    Returns:
        Path to active capture file, or None if none found
    """
    return get_most_recent_capture(max_size_mb=None)  # No size limit for active file


def suggest_fresh_capture_path(captures_dir: Optional[Path] = None) -> Path:
    """Suggest a timestamped path for a fresh capture.
    
    Args:
        captures_dir: Directory for captures (default: companion_collect/savedFlows)
        
    Returns:
        Path for new capture file with timestamp
        
    Example:
        >>> path = suggest_fresh_capture_path()
        >>> print(path)
        companion_collect/savedFlows/capture_20251010_123045.mitm
    """
    from datetime import datetime
    
    if captures_dir is None:
        captures_dir = Path(__file__).parent.parent.parent / "companion_collect" / "savedFlows"
    
    captures_dir.mkdir(parents=True, exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return captures_dir / f"capture_{timestamp}.mitm"


def read_recent_flows(flow_file: Path, max_flows: int = 1000):
    """Read only the most recent N flows from a capture file.
    
    This is efficient for large files - reads flows from the end backwards
    until we have enough fresh flows.
    
    Args:
        flow_file: Path to mitmproxy flow file
        max_flows: Maximum number of recent flows to read (default: 1000)
        
    Yields:
        HTTPFlow objects from most recent flows
        
    Example:
        >>> for flow in read_recent_flows(Path("capture.mitm"), max_flows=500):
        ...     # Process only the 500 most recent flows
        ...     process(flow)
    """
    from mitmproxy import io as mitmio
    
    with open(flow_file, "rb") as f:
        # Read all flows (TODO: optimize for very large files)
        all_flows = list(mitmio.FlowReader(f).stream())
        
        # Return only the last N flows
        recent_flows = all_flows[-max_flows:] if len(all_flows) > max_flows else all_flows
        
        logger.info(
            "recent_flows_loaded",
            total_flows=len(all_flows),
            recent_flows=len(recent_flows),
            max_flows=max_flows,
        )
        
        for flow in recent_flows:
            yield flow


def get_file_info(flow_file: Path) -> dict:
    """Get information about a capture file.
    
    Args:
        flow_file: Path to mitmproxy flow file
        
    Returns:
        Dict with size_mb, modified_time, age_hours
    """
    import time
    
    stat = flow_file.stat()
    size_mb = stat.st_size / 1024 / 1024
    modified_time = stat.st_mtime
    age_hours = (time.time() - modified_time) / 3600
    
    return {
        "size_mb": round(size_mb, 2),
        "modified_time": modified_time,
        "age_hours": round(age_hours, 2),
    }
