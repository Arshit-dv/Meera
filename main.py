"""
Meera - Main Entry Point
Supports interactive terminal mode and Agent API server mode.
"""
import argparse
import atexit
import logging
import sys

from agent.core import AgentCore
from api.server import MeeraAPIServer
from config.settings import DEFAULT_MODEL_KEY, ServerConfig
from model.manager import ModelManager

# Configure root logger
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("meera.main")


def run_cli(agent: AgentCore):
    """Interactive streaming CLI session."""
    print("=" * 60)
    print("  MEERA - Personal AI Agent (Local-First Edge Architecture)")
    print("  Type 'exit', 'quit', or 'q' to end the session.")
    print("  Type '/reset' to clear conversation context.")
    print("  Type '/status' to check RAM and model health.")
    print("=" * 60)

    while True:
        try:
            user_input = input("\nYou > ").strip()
            if not user_input:
                continue

            if user_input.lower() in ("exit", "quit", "q"):
                print("\nShutting down Meera...")
                break

            if user_input.lower() == "/reset":
                agent.reset_conversation()
                print("[INFO] Conversation context reset.")
                continue

            if user_input.lower() == "/status":
                status = agent.status()
                print(f"[STATUS] {status}")
                continue

            print("\nMeera > ", end="", flush=True)
            for chunk in agent.chat_stream(user_input):
                print(chunk, end="", flush=True)
            print()

        except KeyboardInterrupt:
            print("\n\nSession interrupted. Exiting...")
            break
        except Exception as e:
            print(f"\n▲ Error: {e}")


def run_server(agent: AgentCore, config: ServerConfig):
    """Starts the Agent API Server."""
    import threading

    if getattr(config, "prewarm", True):
        logger.info("Pre-warming model runtime in background for instant first prompt...")
        t = threading.Thread(target=agent.model_manager.ensure_loaded, daemon=True)
        t.start()

    # Automatically synchronize Teams assignments & announcements in background on launch if authenticated
    def _bg_teams_startup_sync():
        try:
            token = agent.teams_connector.get_valid_access_token()
            if token:
                logger.info("[STARTUP] Auto-syncing Teams assignments and announcements...")
                d_list, _ = agent.teams_connector.sync_teams_assignments()
                a_list = agent.teams_connector.monitor_channel_announcements()
                logger.info(f"[STARTUP] Teams sync finished: {len(d_list)} assignments, {len(a_list)} announcements.")
        except Exception as e:
            logger.warning(f"[STARTUP] Background Teams sync error: {e}")

    threading.Thread(target=_bg_teams_startup_sync, daemon=True).start()

    server = MeeraAPIServer(agent_core=agent, config=config)
    atexit.register(server.stop)
    server.start()


def main():
    parser = argparse.ArgumentParser(description="Meera - Personal AI Agent")
    parser.add_argument(
        "--server",
        action="store_true",
        help="Start the Agent API server for Open WebUI / external clients",
    )
    parser.add_argument(
        "--model",
        type=str,
        default=DEFAULT_MODEL_KEY,
        help=f"Model key to use (default: {DEFAULT_MODEL_KEY})",
    )
    parser.add_argument(
        "--host",
        type=str,
        default="127.0.0.1",
        help="API host address (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="API port (default: 8000)",
    )

    args = parser.parse_args()

    server_config = ServerConfig(api_host=args.host, api_port=args.port)
    model_manager = ModelManager(default_model_key=args.model, server_config=server_config)
    agent = AgentCore(model_manager=model_manager)

    # Ensure model runtime is properly unloaded on process exit
    atexit.register(model_manager.unload)

    if args.server:
        run_server(agent, server_config)
    else:
        run_cli(agent)


if __name__ == "__main__":
    main()
