import argparse
from .client import RpcnClient


def main():
	parser = argparse.ArgumentParser(description="RPCN client smoke test")
	parser.add_argument("--host",     default="rpcn.mynarco.xyz")
	parser.add_argument("--port",     type=int, default=31313)
	parser.add_argument("--user",     required=True, help="RPCN username")
	parser.add_argument("--password", required=True, help="RPCN password")
	parser.add_argument("--token",    default="", help="RPCN token (leave blank if not required)")
	args = parser.parse_args()

	client = RpcnClient(host=args.host, port=args.port)

	print(f"Connecting to {args.host}:{args.port} ...")
	version = client.connect()
	print(f"  Protocol version: {version}")

	print(f"Logging in as {args.user!r} ...")
	info = client.login(args.user, args.password, args.token)
	print(f"  online_name : {info.online_name}")
	print(f"  avatar_url  : {info.avatar_url}")
	print(f"  user_id     : {info.npid}")

	client.disconnect()
	print("Done.")


if __name__ == "__main__":
	main()
