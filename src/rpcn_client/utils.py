from datetime import datetime, timezone


def _format_epoch(epoch_us: int) -> str:
	"""Convert a microsecond epoch timestamp to a readable UTC datetime string."""
	if epoch_us == 0:
		return "N/A"
	try:
		dt = datetime.fromtimestamp(epoch_us / 1_000_000, tz=timezone.utc)
		return dt.strftime("%Y-%m-%d %H:%M:%S UTC")
	except (OSError, ValueError):
		return f"epoch={epoch_us}"
