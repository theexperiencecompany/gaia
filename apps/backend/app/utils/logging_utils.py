from pathlib import Path


def shorten_path(record):
    """Custom function to shorten file paths for cleaner logs."""
    file_path = (
        record["file"].path if hasattr(record["file"], "path") else str(record["file"])
    )
    # Get just the filename without extension, or last 2 parts of path
    path_parts = Path(file_path).parts
    if len(path_parts) >= 2:
        record["short_file"] = f"{path_parts[-2]}/{Path(file_path).stem}"
    else:
        record["short_file"] = Path(file_path).stem
    return record["short_file"]
